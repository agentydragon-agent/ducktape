// Package routing manages nftables rules and ip policy routing for KubeSpan.
package routing

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math/rand/v2"
	"net"
	"net/netip"
	"syscall"
	"time"

	"github.com/google/nftables"
	"github.com/google/nftables/binaryutil"
	"github.com/google/nftables/expr"
	"github.com/jsimonetti/rtnetlink/v2"
	"github.com/siderolabs/talos/pkg/machinery/constants"
	"github.com/vishvananda/netlink"
	"go.uber.org/zap"
	"go4.org/netipx"
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
	nftDiagDone  bool
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
	// Clean up stale ip rules from a prior crash. Nftables cleanup is
	// handled inline by installNftables (single atomic batch).
	if err := rm.rulesManager.Cleanup(); err != nil {
		rm.logger.Warn("ip rules cleanup failed (may be first run)", zap.Error(err))
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
// Retries on EBUSY (nft_commit_mutex contention) before propagating the error.
//
// The kernel's nf_tables_commit_mutex uses mutex_trylock, returning EBUSY
// immediately when the mutex is held. The kernel's deferred commit_release
// work item holds the mutex (blocking) after a successful commit, so rapid
// sequential commits can hit EBUSY. Exponential backoff with random jitter
// handles this gracefully.
//
// Ref: talos/internal/app/machined/pkg/controllers/kubespan/manager.go
func (rm *Manager) installNftables(routedPrefixes []netip.Prefix) error {
	const (
		maxTimeout = 30 * time.Second
		baseDelay  = 50 * time.Millisecond
		maxDelay   = 2 * time.Second
	)

	// Log existing nftables state on first call for diagnostics.
	if !rm.nftDiagDone {
		rm.nftDiagDone = true
		rm.logNftablesDiag()
	}

	// Skip nftables entirely when there are no prefixes to route.
	// Without prefixes, the mark rules have nothing to match, so the table
	// is unnecessary. More importantly, this avoids a kernel nftables Flush
	// (commit) whose deferred commit_release holds the commit_mutex, causing
	// EBUSY on the next Flush that installs the actual routed prefixes.
	if len(routedPrefixes) == 0 {
		rm.logger.Debug("nftables skipped (no routed prefixes)")
		return nil
	}

	deadline := time.Now().Add(maxTimeout)
	delay := baseDelay

	var lastErr error
	for attempt := 0; time.Now().Before(deadline); attempt++ {
		if attempt > 0 {
			// Exponential backoff with random jitter to desynchronize
			// from other nftables users (other kubespand instances, Docker).
			jitter := time.Duration(rand.Int64N(int64(delay)))
			time.Sleep(delay + jitter)
			delay = min(delay*2, maxDelay)
		}
		lastErr = rm.tryInstallNftables(routedPrefixes)
		if lastErr == nil {
			if attempt > 0 {
				rm.logger.Info("nftables installed after EBUSY retries", zap.Int("attempts", attempt+1))
			}
			return nil
		}
		if !errors.Is(lastErr, syscall.EBUSY) {
			return lastErr
		}
		if attempt == 0 || (attempt+1)%10 == 0 {
			rm.logger.Debug("nftables EBUSY, retrying",
				zap.Int("attempt", attempt+1),
				zap.Duration("next_delay", delay),
			)
		}
	}
	rm.logger.Error("nftables install failed after retries", zap.Error(lastErr))
	return lastErr
}

// logNftablesDiag logs diagnostic info about the current nftables state.
func (rm *Manager) logNftablesDiag() {
	listConn, err := nftables.New()
	if err != nil {
		rm.logger.Warn("nftables diag: cannot create conn", zap.Error(err))
		return
	}
	tables, err := listConn.ListTables()
	if err != nil {
		rm.logger.Warn("nftables diag: ListTables failed", zap.Error(err))
	} else {
		for _, t := range tables {
			rm.logger.Info("nftables diag: existing table", zap.String("name", t.Name), zap.Uint8("family", uint8(t.Family)))
		}
		if len(tables) == 0 {
			rm.logger.Info("nftables diag: no existing tables")
		}
	}
}

// tryInstallNftables performs a single attempt to install nftables rules.
// Everything is committed in a single atomic Flush() to avoid issues with
// anonymous sets needing to be in the same batch as their referencing rules,
// and to avoid EBUSY from the kernel's nf_tables_commit_mutex between two
// separate commits (the kernel's deferred commit_release holds the mutex
// after a successful commit, causing the next commit to fail with EBUSY).
//
// Approach: ListChains (read-only, no commit_mutex) to discover existing state,
// then AddTable + conditional FlushChain + AddChain + AddSet + AddRule in ONE
// Flush. A single commit_mutex acquisition, no prior Flush to trigger
// commit_release.
//
// We use FlushChain (NFT_MSG_DELRULE per chain) instead of FlushTable
// (NFT_MSG_DELTABLE) because FlushTable deactivates the table within the
// transaction, causing subsequent AddChain to fail with the table invisible.
//
// Matches Talos's NfTablesChainController approach:
//   - Anonymous interval sets are ONLY created when there are prefixes for
//     that address family. Empty/nil prefix lists skip set creation entirely.
//   - The kernel rejects anonymous sets that have no rule bindings (EINVAL
//     on kernel 6.14+, "nftables ruleset with unbound set" warning).
//
// Ref: talos/internal/app/machined/pkg/controllers/network/nftables_chain.go
// Ref: talos/internal/app/machined/pkg/adapters/network/nftables_rule.go
func (rm *Manager) tryInstallNftables(routedPrefixes []netip.Prefix) error {
	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables conn: %w", err)
	}

	// Check which of our chains already exist. ListChains is a read-only
	// netlink dump — it does NOT acquire commit_mutex, so it cannot cause
	// EBUSY or trigger commit_release.
	existingChains, _ := conn.ListChains()
	ourChains := map[string]bool{}
	for _, c := range existingChains {
		if c.Table != nil && c.Table.Name == tableName && c.Table.Family == nftables.TableFamilyINet {
			ourChains[c.Name] = true
		}
	}

	// AddTable: create the table if it doesn't exist, or no-op update if it
	// does (NLM_F_CREATE without NLM_F_EXCL).
	table := conn.AddTable(&nftables.Table{
		Family: nftables.TableFamilyINet,
		Name:   tableName,
	})

	// If chains exist from a prior install, flush their rules (and bound
	// anonymous sets). FlushChain sends NFT_MSG_DELRULE which fails with
	// ENOENT if the chain doesn't exist — so only flush chains we know exist.
	if ourChains["kubespan_prerouting"] {
		conn.FlushChain(&nftables.Chain{Table: table, Name: "kubespan_prerouting"})
	}
	if ourChains["kubespan_outgoing"] {
		conn.FlushChain(&nftables.Chain{Table: table, Name: "kubespan_outgoing"})
	}

	// Build an IPSet and split by address family, matching Talos's approach:
	// manager.go builds IPSetBuilder → .IPSet() → .Prefixes()
	// nftables_rule.go Compile() → BuildIPSet() → SplitIPSet()
	// When SplitIPSet returns nil for an address family, no set or rules
	// are created for that family.
	// Ref: talos/internal/app/machined/pkg/adapters/network/ipset.go
	var builder netipx.IPSetBuilder
	for _, p := range routedPrefixes {
		builder.AddPrefix(p)
	}
	ipSet, err := builder.IPSet()
	if err != nil {
		return fmt.Errorf("building routed IP set: %w", err)
	}
	v4Ranges, v6Ranges := splitIPSet(ipSet)

	// Create sets only when there are addresses for that family.
	// Talos skips set+rule creation entirely when there are no addresses to match
	// (nftables_rule.go Compile() returns os.ErrNotExist → rule is dropped).
	var v4Set *intervalSet
	if v4Ranges != nil {
		v4Set = makeIPv4Set(table, v4Ranges)
		if err := conn.AddSet(v4Set.set, v4Set.elements); err != nil {
			return fmt.Errorf("adding v4 set: %w", err)
		}
	}

	var v6Set *intervalSet
	if v6Ranges != nil {
		v6Set = makeIPv6Set(table, v6Ranges)
		if err := conn.AddSet(v6Set.set, v6Set.elements); err != nil {
			return fmt.Errorf("adding v6 set: %w", err)
		}
	}

	// Create chains.
	policy := nftables.ChainPolicyAccept
	prerouteChain := conn.AddChain(&nftables.Chain{
		Name:     "kubespan_prerouting",
		Table:    table,
		Type:     nftables.ChainTypeFilter,
		Hooknum:  nftables.ChainHookPrerouting,
		Priority: nftables.ChainPriorityRaw,
		Policy:   &policy,
	})

	outputChain := conn.AddChain(&nftables.Chain{
		Name:     "kubespan_outgoing",
		Table:    table,
		Type:     nftables.ChainTypeRoute,
		Hooknum:  nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw,
		Policy:   &policy,
	})

	// Prerouting rules: always add skip-mark, conditionally add address matching.
	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: skipWGMarkExprs()})
	if v4Set != nil {
		conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: markIPv4Exprs(v4Set.set)})
	}
	if v6Set != nil {
		conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: markIPv6Exprs(v6Set.set)})
	}

	// Output rules: always add skip-mark and skip-loopback, conditionally add MSS clamp and address matching.
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipWGMarkExprs()})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipLoopbackExprs()})

	if v4Set != nil {
		mss4 := rm.mtu - 40
		if mss4 > 0 {
			conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: mssClampIPv4Exprs(v4Set.set, uint16(mss4))})
		}
		conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: markIPv4Exprs(v4Set.set)})
	}

	if v6Set != nil {
		mss6 := rm.mtu - 60
		if mss6 > 0 {
			conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: mssClampIPv6Exprs(v6Set.set, uint16(mss6))})
		}
		conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: markIPv6Exprs(v6Set.set)})
	}

	// Single atomic commit: table + chains + sets + rules.
	if err := conn.Flush(); err != nil {
		return fmt.Errorf("nftables install: %w", err)
	}
	rm.logger.Debug("nftables installed",
		zap.Int("v4_ranges", len(v4Ranges)),
		zap.Int("v6_ranges", len(v6Ranges)),
	)

	return nil
}

// splitIPSet splits the given IPSet into IPv4 and IPv6 ranges.
// Copied verbatim from Talos (internal, cannot import):
// Ref: talos/internal/app/machined/pkg/adapters/network/ipset.go (SplitIPSet)
func splitIPSet(set *netipx.IPSet) (ipv4, ipv6 []netipx.IPRange) {
	for _, rng := range set.Ranges() {
		if rng.From().Is4() {
			ipv4 = append(ipv4, rng)
		} else {
			ipv6 = append(ipv6, rng)
		}
	}

	return ipv4, ipv6
}

// intervalSet holds an nftables set and its pre-computed elements.
type intervalSet struct {
	set      *nftables.Set
	elements []nftables.SetElement
}

func makeIPv4Set(table *nftables.Table, ranges []netipx.IPRange) *intervalSet {
	set := &nftables.Set{
		Table:     table,
		Anonymous: true,
		Constant:  true,
		Interval:  true,
		KeyType:   nftables.TypeIPAddr,
	}
	return &intervalSet{
		set:      set,
		elements: rangesToSetElements(ranges),
	}
}

func makeIPv6Set(table *nftables.Table, ranges []netipx.IPRange) *intervalSet {
	set := &nftables.Set{
		Table:     table,
		Anonymous: true,
		Constant:  true,
		Interval:  true,
		KeyType:   nftables.TypeIP6Addr,
	}
	return &intervalSet{
		set:      set,
		elements: rangesToSetElements(ranges),
	}
}

// rangesToSetElements converts IP ranges into nftables interval set elements.
// Mirrors Talos's NfTablesSet.SetElements() for SetKindIPv4/SetKindIPv6:
// Ref: talos/internal/app/machined/pkg/adapters/network/nftables_rule.go (SetElements)
func rangesToSetElements(ranges []netipx.IPRange) []nftables.SetElement {
	elements := make([]nftables.SetElement, 0, len(ranges)*2)

	for _, r := range ranges {
		fromBin, _ := r.From().MarshalBinary()    //nolint:errcheck // doesn't fail
		toBin, _ := r.To().Next().MarshalBinary() //nolint:errcheck // doesn't fail

		elements = append(elements,
			nftables.SetElement{
				Key:         fromBin,
				IntervalEnd: false,
			},
			nftables.SetElement{
				Key:         toBin,
				IntervalEnd: true,
			},
		)
	}

	return elements
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
