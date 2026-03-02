// Package routing manages nftables rules and ip policy routing for KubeSpan.
package routing

import (
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"sort"
	"syscall"

	"github.com/google/nftables"
	"github.com/google/nftables/binaryutil"
	"github.com/google/nftables/expr"
	"github.com/jsimonetti/rtnetlink/v2"
	"github.com/siderolabs/gen/xslices"
	"github.com/siderolabs/talos/pkg/machinery/constants"
	"github.com/vishvananda/netlink"
	"go.uber.org/zap"
	"golang.org/x/sys/unix"
)

const tableName = "talos_kubespan"

// RulesManager manages IP policy routing rules for KubeSpan.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go
type RulesManager interface {
	Install() error
	Cleanup() error
}

type rulesManager struct {
	targetTable  uint8
	internalMark uint32
	markMask     uint32
}

// NewRulesManager creates a new IP rules manager matching Talos's routing_rules.go.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go (NewRulesManager)
func NewRulesManager(targetTable uint8, internalMark, markMask uint32) RulesManager {
	return &rulesManager{
		targetTable:  targetTable,
		internalMark: internalMark,
		markMask:     markMask,
	}
}

// Install adds fwmark-based policy routing rules for both IPv4 and IPv6.
// Uses jsimonetti/rtnetlink v2 for rule management.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go (Install)
func (rm *rulesManager) Install() error {
	nc, err := rtnetlink.Dial(nil)
	if err != nil {
		return fmt.Errorf("rtnetlink dial: %w", err)
	}
	defer nc.Close()

	for _, family := range []uint8{unix.AF_INET, unix.AF_INET6} {
		priority := nextRuleNumber(nc, family)
		table := uint32(rm.targetTable)

		if err := nc.Rule.Replace(&rtnetlink.RuleMessage{
			Family: family,
			Table:  rm.targetTable,
			Action: unix.FR_ACT_TO_TBL,
			Attributes: &rtnetlink.RuleAttributes{
				FwMark:   &rm.internalMark,
				FwMask:   &rm.markMask,
				Table:    &table,
				Priority: &priority,
			},
		}); err != nil {
			return fmt.Errorf("installing ip rule (family %d): %w", family, err)
		}
	}

	return nil
}

// Cleanup removes all fwmark-based policy routing rules matching our mark/mask/table.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go (Cleanup)
func (rm *rulesManager) Cleanup() error {
	nc, err := rtnetlink.Dial(nil)
	if err != nil {
		return fmt.Errorf("rtnetlink dial: %w", err)
	}
	defer nc.Close()

	rules, err := nc.Rule.List()
	if err != nil {
		return fmt.Errorf("listing rules: %w", err)
	}

	for _, rule := range rules {
		if rule.Table != rm.targetTable {
			continue
		}
		if rule.Attributes == nil || rule.Attributes.FwMark == nil || rule.Attributes.FwMask == nil {
			continue
		}
		if *rule.Attributes.FwMark != rm.internalMark || *rule.Attributes.FwMask != rm.markMask {
			continue
		}
		if err := nc.Rule.Delete(&rule); err != nil {
			return fmt.Errorf("deleting ip rule: %w", err)
		}
	}

	return nil
}

// nextRuleNumber finds the next available rule priority.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go (nextRuleNumber)
func nextRuleNumber(nc *rtnetlink.Conn, family uint8) uint32 {
	rules, err := nc.Rule.List()
	if err != nil {
		return 32500 // fallback
	}

	max := uint32(32499)
	for _, rule := range rules {
		if rule.Family != family {
			continue
		}
		if rule.Attributes != nil && rule.Attributes.Priority != nil {
			if *rule.Attributes.Priority > max && *rule.Attributes.Priority < 32766 {
				max = *rule.Attributes.Priority
			}
		}
	}
	return max + 1
}

// Manager manages nftables rules, ip policy routing rules, and routes for KubeSpan.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/manager.go (nftables setup)
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go (RulesManager)
type Manager struct {
	mtu          int
	logger       *zap.Logger
	rulesManager RulesManager
}

// NewManager creates a new routing manager.
func NewManager(mtu int, logger *zap.Logger) *Manager {
	return &Manager{
		mtu:    mtu,
		logger: logger,
		rulesManager: NewRulesManager(
			uint8(constants.KubeSpanDefaultRoutingTable),
			constants.KubeSpanDefaultForceFirewallMark,
			constants.KubeSpanDefaultFirewallMask,
		),
	}
}

// Install sets up nftables rules, ip policy routing rules, and default routes.
//
// nftables chains:
//   - kubespan_prerouting (filter/prerouting): mark incoming packets for peer IPs with 0x40
//   - kubespan_outgoing (route/output): mark outgoing packets for peer IPs with 0x40, MSS clamp
//
// Both chains skip packets already marked with 0x20 (WireGuard encrypted egress).
//
// ip rules:
//   - fwmark 0x40/0x60 → table 180 (dynamic priority) for both IPv4 and IPv6
//
// Routes:
//   - Default routes in table 180 via kubespan interface
//
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/manager.go
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/routing_rules.go
func (rm *Manager) Install(routedPrefixes []netip.Prefix) error {
	// Clean up stale rules from a prior crash before installing new ones.
	if err := rm.Cleanup(); err != nil {
		rm.logger.Warn("pre-install cleanup failed (may be first run)", zap.Error(err))
	}

	if err := rm.installNftables(routedPrefixes); err != nil {
		return fmt.Errorf("nftables: %w", err)
	}

	if err := rm.rulesManager.Install(); err != nil {
		return fmt.Errorf("ip rules: %w", err)
	}

	if err := rm.installRoutes(); err != nil {
		return fmt.Errorf("routes: %w", err)
	}

	return nil
}

// Update refreshes the nftables rules with the current set of routed prefixes.
func (rm *Manager) Update(routedPrefixes []netip.Prefix) error {
	return rm.installNftables(routedPrefixes)
}

// Cleanup removes all nftables rules, ip rules, and routes installed by kubespand.
func (rm *Manager) Cleanup() error {
	conn, err := nftables.New()
	if err != nil {
		rm.logger.Warn("nftables conn for cleanup failed, skipping", zap.Error(err))
	} else {
		conn.DelTable(&nftables.Table{
			Family: nftables.TableFamilyINet,
			Name:   tableName,
		})
		_ = conn.Flush() // ignore error if table doesn't exist
	}

	if err := rm.rulesManager.Cleanup(); err != nil {
		rm.logger.Warn("failed to cleanup ip rules", zap.Error(err))
	}

	// Routes in table 180 disappear when the kubespan interface is deleted.
	return nil
}

// installNftables creates the talos_kubespan nftables table with two chains.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/manager.go
func (rm *Manager) installNftables(routedPrefixes []netip.Prefix) error {
	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables conn: %w", err)
	}

	// Diagnostic: log existing nftables state.
	rm.logNftablesState(conn)

	// Canary: test if ANY nftables commit works in this namespace.
	if err := rm.nftablesCanary(); err != nil {
		rm.logger.Error("nftables canary failed: nftables commits do not work in this namespace",
			zap.Error(err))
		return fmt.Errorf("nftables canary: %w", err)
	}
	rm.logger.Info("nftables canary passed")

	table := &nftables.Table{
		Family: nftables.TableFamilyINet,
		Name:   tableName,
	}

	// Phase 1: Create/ensure our table exists. Matches Talos approach
	// (never DelTable, which would ENOENT on first run).
	existingTables, err := conn.ListTablesOfFamily(nftables.TableFamilyINet)
	if err != nil {
		return fmt.Errorf("listing nftables tables: %w", err)
	}
	for _, t := range existingTables {
		if t.Name == tableName {
			table = t
			break
		}
	}
	table = conn.AddTable(table)

	// Flush rules from existing chains in our table, then delete them.
	existingChains, err := conn.ListChains()
	if err != nil {
		rm.logger.Warn("failed to list nftables chains", zap.Error(err))
	}
	for _, chain := range existingChains {
		if chain.Table.Name == tableName {
			conn.FlushChain(chain)
			conn.DelChain(chain)
		}
	}

	if err := conn.Flush(); err != nil {
		rm.logger.Error("nftables phase 1 (table+cleanup) flush failed", zap.Error(err),
			zap.Bool("is_ebusy", errors.Is(err, syscall.EBUSY)))
		return fmt.Errorf("nftables phase 1 flush: %w", err)
	}
	rm.logger.Debug("nftables phase 1 (table+cleanup) committed")

	// Phase 2: Create sets, chains, and rules.
	// Each step uses a fresh connection and individual Flush() to identify
	// which operation causes EBUSY.

	// Re-fetch the table reference after phase 1 commit.
	table, err = rm.fetchTable(tableName)
	if err != nil {
		return fmt.Errorf("re-fetch table: %w", err)
	}

	v4Prefixes := xslices.Filter(routedPrefixes, func(p netip.Prefix) bool { return p.Addr().Is4() })
	v6Prefixes := xslices.Filter(routedPrefixes, func(p netip.Prefix) bool { return !p.Addr().Is4() })

	v4Set := makeIPv4Set(table, v4Prefixes)
	v6Set := makeIPv6Set(table, v6Prefixes)

	// Step 2a: Add sets.
	if err := rm.nftFlush("sets", func(c *nftables.Conn) error {
		if err := c.AddSet(v4Set.set, v4Set.elements); err != nil {
			return fmt.Errorf("adding v4 set: %w", err)
		}
		if err := c.AddSet(v6Set.set, v6Set.elements); err != nil {
			return fmt.Errorf("adding v6 set: %w", err)
		}
		return nil
	}); err != nil {
		return err
	}

	// Step 2b: Add prerouting chain.
	policy := nftables.ChainPolicyAccept
	if err := rm.nftFlush("prerouting chain", func(c *nftables.Conn) error {
		c.AddChain(&nftables.Chain{
			Name:     "kubespan_prerouting",
			Table:    table,
			Type:     nftables.ChainTypeFilter,
			Hooknum:  nftables.ChainHookPrerouting,
			Priority: nftables.ChainPriorityRaw,
			Policy:   &policy,
		})
		return nil
	}); err != nil {
		return err
	}

	// Step 2c: Add output chain.
	if err := rm.nftFlush("output chain", func(c *nftables.Conn) error {
		c.AddChain(&nftables.Chain{
			Name:     "kubespan_outgoing",
			Table:    table,
			Type:     nftables.ChainTypeRoute,
			Hooknum:  nftables.ChainHookOutput,
			Priority: nftables.ChainPriorityRaw,
			Policy:   &policy,
		})
		return nil
	}); err != nil {
		return err
	}

	// Re-fetch chains for AddRule references.
	prerouteChain, outputChain, err := rm.fetchChains(tableName)
	if err != nil {
		return fmt.Errorf("fetching chains: %w", err)
	}

	// Step 2d: Add prerouting rules.
	if err := rm.nftFlush("prerouting rules", func(c *nftables.Conn) error {
		c.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: skipWGMarkExprs()})
		c.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: markIPv4Exprs(v4Set.set)})
		c.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: markIPv6Exprs(v6Set.set)})
		return nil
	}); err != nil {
		return err
	}

	// Step 2e: Add output rules.
	if err := rm.nftFlush("output rules", func(c *nftables.Conn) error {
		c.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipWGMarkExprs()})
		c.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipLoopbackExprs()})
		mss4 := rm.mtu - 40
		if mss4 > 0 {
			c.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: mssClampIPv4Exprs(v4Set.set, uint16(mss4))})
		}
		mss6 := rm.mtu - 60
		if mss6 > 0 {
			c.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: mssClampIPv6Exprs(v6Set.set, uint16(mss6))})
		}
		c.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: markIPv4Exprs(v4Set.set)})
		c.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: markIPv6Exprs(v6Set.set)})
		return nil
	}); err != nil {
		return err
	}

	return nil
}

// nftablesCanary tests whether nftables commits work in the current network
// namespace, including hooked chains (which are needed for actual routing).
func (rm *Manager) nftablesCanary() error {
	canaryTable := &nftables.Table{
		Family: nftables.TableFamilyINet,
		Name:   "kubespand_canary",
	}

	// Step 1: create table only.
	c1, err := nftables.New()
	if err != nil {
		return fmt.Errorf("conn1: %w", err)
	}
	c1.AddTable(canaryTable)
	if err := c1.Flush(); err != nil {
		return fmt.Errorf("create table: %w (EBUSY=%v)", err, errors.Is(err, syscall.EBUSY))
	}
	rm.logger.Debug("canary: table created")

	// Step 2: add a hooked chain (route/output — same type we need for real routing).
	c2, err := nftables.New()
	if err != nil {
		return fmt.Errorf("conn2: %w", err)
	}
	policy := nftables.ChainPolicyAccept
	c2.AddChain(&nftables.Chain{
		Name:     "canary_output",
		Table:    canaryTable,
		Type:     nftables.ChainTypeRoute,
		Hooknum:  nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw,
		Policy:   &policy,
	})
	if err := c2.Flush(); err != nil {
		// This is the key test: can we create hooked chains?
		rm.logger.Error("canary: hooked chain creation FAILED",
			zap.Error(err),
			zap.Bool("is_ebusy", errors.Is(err, syscall.EBUSY)))
		// Still try to clean up.
		c2b, _ := nftables.New()
		if c2b != nil {
			c2b.DelTable(canaryTable)
			_ = c2b.Flush()
		}
		return fmt.Errorf("create hooked chain: %w (EBUSY=%v)", err, errors.Is(err, syscall.EBUSY))
	}
	rm.logger.Debug("canary: hooked chain created")

	// Step 3: add a set and a rule (matching real usage).
	c3, err := nftables.New()
	if err != nil {
		return fmt.Errorf("conn3: %w", err)
	}
	// Re-fetch table handle.
	tables, _ := c3.ListTablesOfFamily(nftables.TableFamilyINet)
	for _, t := range tables {
		if t.Name == "kubespand_canary" {
			canaryTable = t
			break
		}
	}
	chains, _ := c3.ListChains()
	var canaryChain *nftables.Chain
	for _, ch := range chains {
		if ch.Table.Name == "kubespand_canary" && ch.Name == "canary_output" {
			canaryChain = ch
			break
		}
	}
	if canaryChain != nil {
		c3.AddRule(&nftables.Rule{
			Table: canaryTable,
			Chain: canaryChain,
			Exprs: []expr.Any{
				&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
				&expr.Verdict{Kind: expr.VerdictAccept},
			},
		})
	}
	if err := c3.Flush(); err != nil {
		rm.logger.Error("canary: rule creation FAILED",
			zap.Error(err),
			zap.Bool("is_ebusy", errors.Is(err, syscall.EBUSY)))
	} else {
		rm.logger.Debug("canary: rule added")
	}

	// Step 4: cleanup.
	c4, err := nftables.New()
	if err != nil {
		return fmt.Errorf("conn4: %w", err)
	}
	c4.DelTable(canaryTable)
	if err := c4.Flush(); err != nil {
		return fmt.Errorf("delete canary table: %w", err)
	}
	rm.logger.Debug("canary: cleaned up")
	return nil
}

// nftFlush creates a fresh connection, runs the provided setup function to queue
// operations, then flushes. Logs the step name and any EBUSY errors.
func (rm *Manager) nftFlush(step string, setup func(c *nftables.Conn) error) error {
	c, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables conn for %s: %w", step, err)
	}
	if err := setup(c); err != nil {
		return fmt.Errorf("setup %s: %w", step, err)
	}
	if err := c.Flush(); err != nil {
		rm.logger.Error("nftables flush failed",
			zap.String("step", step),
			zap.Error(err),
			zap.Bool("is_ebusy", errors.Is(err, syscall.EBUSY)))
		return fmt.Errorf("nftables %s: %w", step, err)
	}
	rm.logger.Debug("nftables step committed", zap.String("step", step))
	return nil
}

// fetchTable returns the kernel's table handle for the named inet table.
func (rm *Manager) fetchTable(name string) (*nftables.Table, error) {
	c, err := nftables.New()
	if err != nil {
		return nil, fmt.Errorf("conn: %w", err)
	}
	tables, err := c.ListTablesOfFamily(nftables.TableFamilyINet)
	if err != nil {
		return nil, fmt.Errorf("list tables: %w", err)
	}
	for _, t := range tables {
		if t.Name == name {
			return t, nil
		}
	}
	return nil, fmt.Errorf("table %q not found", name)
}

// fetchChains returns the prerouting and output chain handles.
func (rm *Manager) fetchChains(tableName string) (*nftables.Chain, *nftables.Chain, error) {
	c, err := nftables.New()
	if err != nil {
		return nil, nil, fmt.Errorf("conn: %w", err)
	}
	chains, err := c.ListChains()
	if err != nil {
		return nil, nil, fmt.Errorf("list chains: %w", err)
	}
	var preroute, output *nftables.Chain
	for _, ch := range chains {
		if ch.Table.Name != tableName {
			continue
		}
		switch ch.Name {
		case "kubespan_prerouting":
			preroute = ch
		case "kubespan_outgoing":
			output = ch
		}
	}
	if preroute == nil {
		return nil, nil, fmt.Errorf("kubespan_prerouting chain not found")
	}
	if output == nil {
		return nil, nil, fmt.Errorf("kubespan_outgoing chain not found")
	}
	return preroute, output, nil
}

// logNftablesState dumps the existing nftables tables and chains for diagnostics.
func (rm *Manager) logNftablesState(conn *nftables.Conn) {
	for _, family := range []nftables.TableFamily{
		nftables.TableFamilyIPv4, nftables.TableFamilyIPv6, nftables.TableFamilyINet,
	} {
		tables, _ := conn.ListTablesOfFamily(family)
		for _, t := range tables {
			rm.logger.Debug("existing nftables table",
				zap.String("name", t.Name),
				zap.Uint8("family", uint8(t.Family)),
				zap.Uint32("use", t.Use),
				zap.Uint32("flags", t.Flags),
			)
		}
	}
	chains, err := conn.ListChains()
	if err != nil {
		rm.logger.Warn("failed to list nftables chains", zap.Error(err))
		return
	}
	for _, chain := range chains {
		rm.logger.Debug("existing nftables chain",
			zap.String("table", chain.Table.Name),
			zap.String("chain", chain.Name),
			zap.String("type", string(chain.Type)),
		)
	}
}

// intervalSet holds an nftables set and its pre-computed elements.
type intervalSet struct {
	set      *nftables.Set
	elements []nftables.SetElement
}

func makeIPv4Set(table *nftables.Table, prefixes []netip.Prefix) *intervalSet {
	set := &nftables.Set{
		Table:     table,
		Anonymous: true,
		Constant:  true,
		Interval:  true,
		KeyType:   nftables.TypeIPAddr,
	}
	return &intervalSet{
		set:      set,
		elements: prefixesToSetElements(prefixes, 4),
	}
}

func makeIPv6Set(table *nftables.Table, prefixes []netip.Prefix) *intervalSet {
	set := &nftables.Set{
		Table:     table,
		Anonymous: true,
		Constant:  true,
		Interval:  true,
		KeyType:   nftables.TypeIP6Addr,
	}
	return &intervalSet{
		set:      set,
		elements: prefixesToSetElements(prefixes, 16),
	}
}

// prefixesToSetElements converts IP prefixes into nftables interval set elements.
// Ref: talos/internal/app/machined/pkg/adapters/network/nftables_rule.go (SetElements)
func prefixesToSetElements(prefixes []netip.Prefix, addrLen int) []nftables.SetElement {
	if len(prefixes) == 0 {
		return nil
	}

	sorted := make([]netip.Prefix, len(prefixes))
	copy(sorted, prefixes)
	sort.Slice(sorted, func(i, j int) bool {
		ai, aj := sorted[i].Addr(), sorted[j].Addr()
		if c := ai.Compare(aj); c != 0 {
			return c < 0
		}
		return sorted[i].Bits() < sorted[j].Bits()
	})

	var elements []nftables.SetElement
	for _, p := range sorted {
		p = p.Masked()
		startBytes := p.Addr().As16()

		endAddr := prefixEnd(p)
		endBytes := endAddr.As16()

		var start, end []byte
		if addrLen == 4 {
			start = startBytes[12:16]
			end = endBytes[12:16]
		} else {
			start = startBytes[:]
			end = endBytes[:]
		}

		elements = append(elements,
			nftables.SetElement{Key: start, IntervalEnd: false},
			nftables.SetElement{Key: end, IntervalEnd: true},
		)
	}

	return elements
}

func prefixEnd(p netip.Prefix) netip.Addr {
	addr := p.Addr()
	bits := p.Bits()

	totalBits := 128
	if addr.Is4() {
		totalBits = 32
	}

	if bits == totalBits {
		return incrementAddr(addr)
	}

	if addr.Is4() {
		ip4 := addr.As4()
		for i := bits; i < 32; i++ {
			ip4[i/8] |= 1 << (7 - i%8)
		}
		return incrementAddr(netip.AddrFrom4(ip4))
	}

	b := addr.As16()
	for i := bits; i < 128; i++ {
		b[i/8] |= 1 << (7 - i%8)
	}
	return incrementAddr(netip.AddrFrom16(b))
}

func incrementAddr(addr netip.Addr) netip.Addr {
	b := addr.As16()
	for i := len(b) - 1; i >= 0; i-- {
		b[i]++
		if b[i] != 0 {
			break
		}
	}
	if addr.Is4() {
		return netip.AddrFrom4([4]byte{b[12], b[13], b[14], b[15]})
	}
	return netip.AddrFrom16(b)
}

func skipWGMarkExprs() []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
		&expr.Bitwise{
			SourceRegister: 1,
			DestRegister:   1,
			Len:            4,
			Mask:           binaryutil.NativeEndian.PutUint32(constants.KubeSpanDefaultFirewallMask),
			Xor:            binaryutil.NativeEndian.PutUint32(0),
		},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     binaryutil.NativeEndian.PutUint32(constants.KubeSpanDefaultFirewallMark),
		},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func skipLoopbackExprs() []expr.Any {
	loName := make([]byte, 16)
	copy(loName, "lo\x00")

	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyOIFNAME, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     loName,
		},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func markIPv4Exprs(set *nftables.Set) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{unix.NFPROTO_IPV4},
		},
		&expr.Payload{
			DestRegister: 1,
			Base:         expr.PayloadBaseNetworkHeader,
			Offset:       16,
			Len:          4,
		},
		&expr.Lookup{
			SourceRegister: 1,
			SetName:        set.Name,
			SetID:          set.ID,
		},
		&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
		&expr.Bitwise{
			SourceRegister: 1,
			DestRegister:   1,
			Len:            4,
			Mask:           binaryutil.NativeEndian.PutUint32(^uint32(constants.KubeSpanDefaultForceFirewallMark)),
			Xor:            binaryutil.NativeEndian.PutUint32(constants.KubeSpanDefaultForceFirewallMark),
		},
		&expr.Meta{Key: expr.MetaKeyMARK, SourceRegister: true, Register: 1},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func markIPv6Exprs(set *nftables.Set) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{unix.NFPROTO_IPV6},
		},
		&expr.Payload{
			DestRegister: 1,
			Base:         expr.PayloadBaseNetworkHeader,
			Offset:       24,
			Len:          16,
		},
		&expr.Lookup{
			SourceRegister: 1,
			SetName:        set.Name,
			SetID:          set.ID,
		},
		&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
		&expr.Bitwise{
			SourceRegister: 1,
			DestRegister:   1,
			Len:            4,
			Mask:           binaryutil.NativeEndian.PutUint32(^uint32(constants.KubeSpanDefaultForceFirewallMark)),
			Xor:            binaryutil.NativeEndian.PutUint32(constants.KubeSpanDefaultForceFirewallMark),
		},
		&expr.Meta{Key: expr.MetaKeyMARK, SourceRegister: true, Register: 1},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func mssClampIPv4Exprs(set *nftables.Set, mss uint16) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{unix.NFPROTO_IPV4},
		},
		&expr.Payload{
			DestRegister: 1,
			Base:         expr.PayloadBaseNetworkHeader,
			Offset:       16,
			Len:          4,
		},
		&expr.Lookup{
			SourceRegister: 1,
			SetName:        set.Name,
			SetID:          set.ID,
		},
		&expr.Meta{Key: expr.MetaKeyL4PROTO, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{unix.IPPROTO_TCP},
		},
		&expr.Payload{
			DestRegister: 1,
			Base:         expr.PayloadBaseTransportHeader,
			Offset:       13,
			Len:          1,
		},
		&expr.Bitwise{
			SourceRegister: 1,
			DestRegister:   1,
			Len:            1,
			Mask:           []byte{0x06},
			Xor:            []byte{0x00},
		},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{0x02},
		},
		&expr.Exthdr{
			DestRegister: 1,
			Type:         2,
			Offset:       2,
			Len:          2,
			Op:           expr.ExthdrOpTcpopt,
		},
		&expr.Cmp{
			Op:       expr.CmpOpGt,
			Register: 1,
			Data:     binary.BigEndian.AppendUint16(nil, mss),
		},
		&expr.Immediate{
			Register: 1,
			Data:     binary.BigEndian.AppendUint16(nil, mss),
		},
		&expr.Exthdr{
			SourceRegister: 1,
			Type:           2,
			Offset:         2,
			Len:            2,
			Op:             expr.ExthdrOpTcpopt,
		},
	}
}

func mssClampIPv6Exprs(set *nftables.Set, mss uint16) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{unix.NFPROTO_IPV6},
		},
		&expr.Payload{
			DestRegister: 1,
			Base:         expr.PayloadBaseNetworkHeader,
			Offset:       24,
			Len:          16,
		},
		&expr.Lookup{
			SourceRegister: 1,
			SetName:        set.Name,
			SetID:          set.ID,
		},
		&expr.Meta{Key: expr.MetaKeyL4PROTO, Register: 1},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{unix.IPPROTO_TCP},
		},
		&expr.Payload{
			DestRegister: 1,
			Base:         expr.PayloadBaseTransportHeader,
			Offset:       13,
			Len:          1,
		},
		&expr.Bitwise{
			SourceRegister: 1,
			DestRegister:   1,
			Len:            1,
			Mask:           []byte{0x06},
			Xor:            []byte{0x00},
		},
		&expr.Cmp{
			Op:       expr.CmpOpEq,
			Register: 1,
			Data:     []byte{0x02},
		},
		&expr.Exthdr{
			DestRegister: 1,
			Type:         2,
			Offset:       2,
			Len:          2,
			Op:           expr.ExthdrOpTcpopt,
		},
		&expr.Cmp{
			Op:       expr.CmpOpGt,
			Register: 1,
			Data:     binary.BigEndian.AppendUint16(nil, mss),
		},
		&expr.Immediate{
			Register: 1,
			Data:     binary.BigEndian.AppendUint16(nil, mss),
		},
		&expr.Exthdr{
			SourceRegister: 1,
			Type:           2,
			Offset:         2,
			Len:            2,
			Op:             expr.ExthdrOpTcpopt,
		},
	}
}

// installRoutes adds default routes in table 180 pointing to the kubespan interface.
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/manager.go (RouteSpec)
// TODO: consider aligning nftables with Talos NfTablesChain COSI resources
func (rm *Manager) installRoutes() error {
	link, err := netlink.LinkByName(constants.KubeSpanLinkName)
	if err != nil {
		return fmt.Errorf("finding %s for routes: %w", constants.KubeSpanLinkName, err)
	}

	v4Route := &netlink.Route{
		LinkIndex: link.Attrs().Index,
		Table:     constants.KubeSpanDefaultRoutingTable,
		Dst:       &net.IPNet{IP: net.IPv4zero, Mask: net.CIDRMask(0, 32)},
		MTU:       rm.mtu,
	}
	if err := netlink.RouteReplace(v4Route); err != nil {
		return fmt.Errorf("adding IPv4 default route to table %d: %w", constants.KubeSpanDefaultRoutingTable, err)
	}

	v6Route := &netlink.Route{
		LinkIndex: link.Attrs().Index,
		Table:     constants.KubeSpanDefaultRoutingTable,
		Dst:       &net.IPNet{IP: net.IPv6zero, Mask: net.CIDRMask(0, 128)},
		MTU:       rm.mtu,
	}
	if err := netlink.RouteReplace(v6Route); err != nil {
		return fmt.Errorf("adding IPv6 default route to table %d: %w", constants.KubeSpanDefaultRoutingTable, err)
	}

	return nil
}
