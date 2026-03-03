// Binary testprobe provides test utilities for KubeSpan e2e tests:
//   - Default mode: sends ICMPv6 echo requests to verify tunnel connectivity
//   - -nft-smoke=LEVEL: graduated nftables tests (levels 1-6)
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"net"
	"os"
	"time"

	"github.com/google/nftables"
	"github.com/google/nftables/expr"
	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv6"
	"golang.org/x/sys/unix"
)

func main() {
	timeout := flag.Duration("timeout", 30*time.Second, "overall timeout for probe")
	nftSmoke := flag.Int("nft-smoke", 0, "nftables smoke test level (1-6, 0=disabled)")
	flag.Parse()

	if *nftSmoke > 0 {
		os.Exit(runNftSmoke(*nftSmoke))
	}

	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: testprobe [-timeout duration] <ipv6-address>")
		fmt.Fprintln(os.Stderr, "       testprobe -nft-smoke=LEVEL  (1-6)")
		os.Exit(2)
	}

	target := flag.Arg(0)
	deadline := time.Now().Add(*timeout)
	seq := 0

	for time.Now().Before(deadline) {
		seq++
		if ping6(target, seq) {
			fmt.Printf("ping %s succeeded (seq %d)\n", target, seq)
			os.Exit(0)
		}
		time.Sleep(time.Second)
	}

	fmt.Fprintf(os.Stderr, "timeout after %s: no ICMPv6 echo reply from %s\n", *timeout, target)
	os.Exit(1)
}

// runNftSmoke runs graduated nftables smoke tests. Each level adds one feature
// that kubespand uses, isolating which specific nftables operation triggers EBUSY.
//
// Levels (cumulative):
//
//	1: table + chains with hooks (separate batches) — baseline
//	2: table + chains + anonymous interval set + lookup rule (separate batches)
//	3: table + chains + set + multiple rules with mark exprs (separate batches)
//	4: all of level 3 in a SINGLE batch (one New+Flush)
//	5: single batch with FlushChain (simulating re-install over existing state)
//	6: full kubespand pattern: FlushChain + table + chains + sets + rules (single batch)
func runNftSmoke(level int) int {
	fmt.Printf("nft-smoke level %d\n", level)

	// List existing tables for diagnostics.
	if err := logExistingState(); err != nil {
		return 1
	}

	var err error
	switch level {
	case 1:
		err = smokeLevel1()
	case 2:
		err = smokeLevel2()
	case 3:
		err = smokeLevel3()
	case 4:
		err = smokeLevel4()
	case 5:
		err = smokeLevel5()
	case 6:
		err = smokeLevel6()
	default:
		fmt.Fprintf(os.Stderr, "unknown level %d (valid: 1-6)\n", level)
		return 2
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "FAIL: %v\n", err)
		return 1
	}

	// Clean up test table.
	cleanup()

	fmt.Printf("nft-smoke level %d: PASS\n", level)
	return 0
}

const smokeTableName = "testprobe_smoke"

func logExistingState() error {
	conn, err := nftables.New()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nftables.New: %v\n", err)
		return err
	}
	tables, _ := conn.ListTables()
	fmt.Printf("existing tables: %d\n", len(tables))
	for _, t := range tables {
		fmt.Printf("  table %s family=%d\n", t.Name, t.Family)
	}
	chains, _ := conn.ListChains()
	fmt.Printf("existing chains: %d\n", len(chains))
	for _, c := range chains {
		tbl := "<nil>"
		if c.Table != nil {
			tbl = c.Table.Name
		}
		fmt.Printf("  chain %s table=%s\n", c.Name, tbl)
	}
	return nil
}

func cleanup() {
	conn, _ := nftables.New()
	if conn != nil {
		conn.DelTable(&nftables.Table{Family: nftables.TableFamilyINet, Name: smokeTableName})
		_ = conn.Flush()
	}
}

// smokeLevel1: table + chains with hooks in separate batches.
// This is what the original nft-smoke test did. Baseline.
func smokeLevel1() error {
	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}
	table := conn.AddTable(&nftables.Table{
		Family: nftables.TableFamilyINet,
		Name:   smokeTableName,
	})
	if err := conn.Flush(); err != nil {
		return fmt.Errorf("Flush (AddTable): %w", err)
	}
	fmt.Println("  AddTable OK")

	conn2, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}
	policy := nftables.ChainPolicyAccept
	conn2.AddChain(&nftables.Chain{
		Name: "test_prerouting", Table: table,
		Type: nftables.ChainTypeFilter, Hooknum: nftables.ChainHookPrerouting,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})
	conn2.AddChain(&nftables.Chain{
		Name: "test_output", Table: table,
		Type: nftables.ChainTypeRoute, Hooknum: nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})
	if err := conn2.Flush(); err != nil {
		return fmt.Errorf("Flush (AddChains): %w", err)
	}
	fmt.Println("  AddChains OK")
	return nil
}

// smokeLevel2: table + chains + anonymous interval set + lookup rule.
// Tests anonymous sets, which kubespand uses but the baseline doesn't.
func smokeLevel2() error {
	if err := smokeLevel1(); err != nil {
		return err
	}

	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}
	table := &nftables.Table{Family: nftables.TableFamilyINet, Name: smokeTableName}
	chain := &nftables.Chain{Table: table, Name: "test_prerouting"}

	set := &nftables.Set{
		Table: table, Anonymous: true, Constant: true, Interval: true,
		KeyType: nftables.TypeIPAddr,
	}
	// 10.244.0.0/16 as interval set elements.
	elements := []nftables.SetElement{
		{Key: []byte{10, 244, 0, 0}, IntervalEnd: false},
		{Key: []byte{10, 245, 0, 0}, IntervalEnd: true},
	}
	if err := conn.AddSet(set, elements); err != nil {
		return fmt.Errorf("AddSet: %w", err)
	}

	// Rule: lookup destination IP in set.
	conn.AddRule(&nftables.Rule{
		Table: table, Chain: chain,
		Exprs: []expr.Any{
			&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
			&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.NFPROTO_IPV4}},
			&expr.Payload{DestRegister: 1, Base: expr.PayloadBaseNetworkHeader, Offset: 16, Len: 4},
			&expr.Lookup{SourceRegister: 1, SetName: set.Name, SetID: set.ID},
			&expr.Verdict{Kind: expr.VerdictAccept},
		},
	})
	if err := conn.Flush(); err != nil {
		return fmt.Errorf("Flush (set+rule): %w", err)
	}
	fmt.Println("  AddSet + AddRule (anonymous interval set + lookup) OK")
	return nil
}

// smokeLevel3: table + chains + set + multiple rules with mark expressions.
// Tests mark read/write expressions matching kubespand's pattern.
func smokeLevel3() error {
	if err := smokeLevel1(); err != nil {
		return err
	}

	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}
	table := &nftables.Table{Family: nftables.TableFamilyINet, Name: smokeTableName}
	prerouteChain := &nftables.Chain{Table: table, Name: "test_prerouting"}
	outputChain := &nftables.Chain{Table: table, Name: "test_output"}

	set := &nftables.Set{
		Table: table, Anonymous: true, Constant: true, Interval: true,
		KeyType: nftables.TypeIPAddr,
	}
	elements := []nftables.SetElement{
		{Key: []byte{10, 244, 0, 0}, IntervalEnd: false},
		{Key: []byte{10, 245, 0, 0}, IntervalEnd: true},
	}
	if err := conn.AddSet(set, elements); err != nil {
		return fmt.Errorf("AddSet: %w", err)
	}

	fwMark := uint32(0x00000060)
	fwMask := uint32(0x000000e0)

	// Prerouting: skip-mark rule + lookup+mark rule.
	conn.AddRule(&nftables.Rule{
		Table: table, Chain: prerouteChain,
		Exprs: skipMarkExprs(fwMark, fwMask),
	})
	conn.AddRule(&nftables.Rule{
		Table: table, Chain: prerouteChain,
		Exprs: lookupAndMarkExprs(set, fwMark, fwMask),
	})

	// Output: skip-mark + skip-loopback + lookup+mark.
	conn.AddRule(&nftables.Rule{
		Table: table, Chain: outputChain,
		Exprs: skipMarkExprs(fwMark, fwMask),
	})
	conn.AddRule(&nftables.Rule{
		Table: table, Chain: outputChain,
		Exprs: skipLoopbackExprs(),
	})
	conn.AddRule(&nftables.Rule{
		Table: table, Chain: outputChain,
		Exprs: lookupAndMarkExprs(set, fwMark, fwMask),
	})

	if err := conn.Flush(); err != nil {
		return fmt.Errorf("Flush (set+rules): %w", err)
	}
	fmt.Println("  AddSet + multiple rules (skip-mark, lookup, mark write) OK")
	return nil
}

// smokeLevel4: everything from level 3 in a SINGLE New()+Flush() batch.
// Tests whether batch size or single-transaction semantics trigger EBUSY.
func smokeLevel4() error {
	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}

	table := conn.AddTable(&nftables.Table{
		Family: nftables.TableFamilyINet, Name: smokeTableName,
	})

	policy := nftables.ChainPolicyAccept
	prerouteChain := conn.AddChain(&nftables.Chain{
		Name: "test_prerouting", Table: table,
		Type: nftables.ChainTypeFilter, Hooknum: nftables.ChainHookPrerouting,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})
	outputChain := conn.AddChain(&nftables.Chain{
		Name: "test_output", Table: table,
		Type: nftables.ChainTypeRoute, Hooknum: nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})

	set := &nftables.Set{
		Table: table, Anonymous: true, Constant: true, Interval: true,
		KeyType: nftables.TypeIPAddr,
	}
	elements := []nftables.SetElement{
		{Key: []byte{10, 244, 0, 0}, IntervalEnd: false},
		{Key: []byte{10, 245, 0, 0}, IntervalEnd: true},
	}
	if err := conn.AddSet(set, elements); err != nil {
		return fmt.Errorf("AddSet: %w", err)
	}

	fwMark := uint32(0x00000060)
	fwMask := uint32(0x000000e0)

	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: skipMarkExprs(fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: lookupAndMarkExprs(set, fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipMarkExprs(fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipLoopbackExprs()})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: lookupAndMarkExprs(set, fwMark, fwMask)})

	if err := conn.Flush(); err != nil {
		return fmt.Errorf("Flush (single batch): %w", err)
	}
	fmt.Println("  Single batch (table + chains + set + rules) OK")
	return nil
}

// smokeLevel5: install state from level 4, then re-install with FlushChain
// in a single batch. Tests the re-install path kubespand uses on update.
func smokeLevel5() error {
	// First install.
	if err := smokeLevel4(); err != nil {
		return err
	}

	// Re-install: flush existing chains, re-add everything.
	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}

	table := conn.AddTable(&nftables.Table{
		Family: nftables.TableFamilyINet, Name: smokeTableName,
	})

	conn.FlushChain(&nftables.Chain{Table: table, Name: "test_prerouting"})
	conn.FlushChain(&nftables.Chain{Table: table, Name: "test_output"})

	policy := nftables.ChainPolicyAccept
	prerouteChain := conn.AddChain(&nftables.Chain{
		Name: "test_prerouting", Table: table,
		Type: nftables.ChainTypeFilter, Hooknum: nftables.ChainHookPrerouting,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})
	outputChain := conn.AddChain(&nftables.Chain{
		Name: "test_output", Table: table,
		Type: nftables.ChainTypeRoute, Hooknum: nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})

	set := &nftables.Set{
		Table: table, Anonymous: true, Constant: true, Interval: true,
		KeyType: nftables.TypeIPAddr,
	}
	elements := []nftables.SetElement{
		{Key: []byte{10, 244, 0, 0}, IntervalEnd: false},
		{Key: []byte{10, 245, 0, 0}, IntervalEnd: true},
	}
	if err := conn.AddSet(set, elements); err != nil {
		return fmt.Errorf("AddSet: %w", err)
	}

	fwMark := uint32(0x00000060)
	fwMask := uint32(0x000000e0)

	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: skipMarkExprs(fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: lookupAndMarkExprs(set, fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipMarkExprs(fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipLoopbackExprs()})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: lookupAndMarkExprs(set, fwMark, fwMask)})

	if err := conn.Flush(); err != nil {
		return fmt.Errorf("Flush (re-install with FlushChain): %w", err)
	}
	fmt.Println("  Re-install (FlushChain + table + chains + set + rules) OK")
	return nil
}

// smokeLevel6: full kubespand pattern with both IPv4 and IPv6 sets.
// Single batch: table + FlushChain + chains + 2 sets + rules with mark + MSS clamp.
func smokeLevel6() error {
	// Pre-install to have chains to flush (like kubespand on second reconcile).
	if err := smokeLevel4(); err != nil {
		return err
	}

	conn, err := nftables.New()
	if err != nil {
		return fmt.Errorf("nftables.New: %w", err)
	}

	table := conn.AddTable(&nftables.Table{
		Family: nftables.TableFamilyINet, Name: smokeTableName,
	})

	conn.FlushChain(&nftables.Chain{Table: table, Name: "test_prerouting"})
	conn.FlushChain(&nftables.Chain{Table: table, Name: "test_output"})

	policy := nftables.ChainPolicyAccept
	prerouteChain := conn.AddChain(&nftables.Chain{
		Name: "test_prerouting", Table: table,
		Type: nftables.ChainTypeFilter, Hooknum: nftables.ChainHookPrerouting,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})
	outputChain := conn.AddChain(&nftables.Chain{
		Name: "test_output", Table: table,
		Type: nftables.ChainTypeRoute, Hooknum: nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw, Policy: &policy,
	})

	// IPv4 set: 10.244.0.0/16
	v4Set := &nftables.Set{
		Table: table, Anonymous: true, Constant: true, Interval: true,
		KeyType: nftables.TypeIPAddr,
	}
	if err := conn.AddSet(v4Set, []nftables.SetElement{
		{Key: []byte{10, 244, 0, 0}, IntervalEnd: false},
		{Key: []byte{10, 245, 0, 0}, IntervalEnd: true},
	}); err != nil {
		return fmt.Errorf("AddSet v4: %w", err)
	}

	// IPv6 set: fd50:cafe::/96
	v6Set := &nftables.Set{
		Table: table, Anonymous: true, Constant: true, Interval: true,
		KeyType: nftables.TypeIP6Addr,
	}
	v6Start := make([]byte, 16)
	v6Start[0], v6Start[1] = 0xfd, 0x50
	v6Start[2], v6Start[3] = 0xca, 0xfe
	v6End := make([]byte, 16)
	copy(v6End, v6Start)
	v6End[12] = 1 // fd50:cafe::1:0:0:0
	if err := conn.AddSet(v6Set, []nftables.SetElement{
		{Key: v6Start, IntervalEnd: false},
		{Key: v6End, IntervalEnd: true},
	}); err != nil {
		return fmt.Errorf("AddSet v6: %w", err)
	}

	fwMark := uint32(0x00000060)
	fwMask := uint32(0x000000e0)

	// Prerouting rules.
	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: skipMarkExprs(fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: lookupAndMarkIPv4Exprs(v4Set, fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: prerouteChain, Exprs: lookupAndMarkIPv6Exprs(v6Set, fwMark, fwMask)})

	// Output rules.
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipMarkExprs(fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: skipLoopbackExprs()})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: mssClampIPv4Exprs(v4Set, 1380)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: lookupAndMarkIPv4Exprs(v4Set, fwMark, fwMask)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: mssClampIPv6Exprs(v6Set, 1360)})
	conn.AddRule(&nftables.Rule{Table: table, Chain: outputChain, Exprs: lookupAndMarkIPv6Exprs(v6Set, fwMark, fwMask)})

	if err := conn.Flush(); err != nil {
		return fmt.Errorf("Flush (full kubespand pattern): %w", err)
	}
	fmt.Println("  Full kubespand pattern (dual-stack sets, mark, MSS clamp) OK")
	return nil
}

// Expression builders matching kubespand's routing.go patterns.

func skipMarkExprs(fwMark, fwMask uint32) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
		&expr.Bitwise{
			SourceRegister: 1, DestRegister: 1, Len: 4,
			Mask: nativeUint32(fwMask),
			Xor:  nativeUint32(0),
		},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: nativeUint32(fwMark)},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func skipLoopbackExprs() []expr.Any {
	loName := make([]byte, 16)
	copy(loName, "lo\x00")
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyOIFNAME, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: loName},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func lookupAndMarkExprs(set *nftables.Set, fwMark, fwMask uint32) []expr.Any {
	return lookupAndMarkIPv4Exprs(set, fwMark, fwMask)
}

func lookupAndMarkIPv4Exprs(set *nftables.Set, fwMark, fwMask uint32) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.NFPROTO_IPV4}},
		&expr.Payload{DestRegister: 1, Base: expr.PayloadBaseNetworkHeader, Offset: 16, Len: 4},
		&expr.Lookup{SourceRegister: 1, SetName: set.Name, SetID: set.ID},
		&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
		&expr.Bitwise{
			SourceRegister: 1, DestRegister: 1, Len: 4,
			Mask: nativeUint32(^fwMark),
			Xor:  nativeUint32(fwMark),
		},
		&expr.Meta{Key: expr.MetaKeyMARK, SourceRegister: true, Register: 1},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func lookupAndMarkIPv6Exprs(set *nftables.Set, fwMark, fwMask uint32) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.NFPROTO_IPV6}},
		&expr.Payload{DestRegister: 1, Base: expr.PayloadBaseNetworkHeader, Offset: 24, Len: 16},
		&expr.Lookup{SourceRegister: 1, SetName: set.Name, SetID: set.ID},
		&expr.Meta{Key: expr.MetaKeyMARK, Register: 1},
		&expr.Bitwise{
			SourceRegister: 1, DestRegister: 1, Len: 4,
			Mask: nativeUint32(^fwMark),
			Xor:  nativeUint32(fwMark),
		},
		&expr.Meta{Key: expr.MetaKeyMARK, SourceRegister: true, Register: 1},
		&expr.Verdict{Kind: expr.VerdictAccept},
	}
}

func mssClampIPv4Exprs(set *nftables.Set, mss uint16) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.NFPROTO_IPV4}},
		&expr.Payload{DestRegister: 1, Base: expr.PayloadBaseNetworkHeader, Offset: 16, Len: 4},
		&expr.Lookup{SourceRegister: 1, SetName: set.Name, SetID: set.ID},
		&expr.Meta{Key: expr.MetaKeyL4PROTO, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.IPPROTO_TCP}},
		&expr.Exthdr{DestRegister: 1, Type: 2, Offset: 2, Len: 2, Op: expr.ExthdrOpTcpopt},
		&expr.Cmp{Op: expr.CmpOpGt, Register: 1, Data: bigEndianUint16(mss)},
		&expr.Immediate{Register: 1, Data: bigEndianUint16(mss)},
		&expr.Exthdr{SourceRegister: 1, Type: 2, Offset: 2, Len: 2, Op: expr.ExthdrOpTcpopt},
	}
}

func mssClampIPv6Exprs(set *nftables.Set, mss uint16) []expr.Any {
	return []expr.Any{
		&expr.Meta{Key: expr.MetaKeyNFPROTO, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.NFPROTO_IPV6}},
		&expr.Payload{DestRegister: 1, Base: expr.PayloadBaseNetworkHeader, Offset: 24, Len: 16},
		&expr.Lookup{SourceRegister: 1, SetName: set.Name, SetID: set.ID},
		&expr.Meta{Key: expr.MetaKeyL4PROTO, Register: 1},
		&expr.Cmp{Op: expr.CmpOpEq, Register: 1, Data: []byte{unix.IPPROTO_TCP}},
		&expr.Exthdr{DestRegister: 1, Type: 2, Offset: 2, Len: 2, Op: expr.ExthdrOpTcpopt},
		&expr.Cmp{Op: expr.CmpOpGt, Register: 1, Data: bigEndianUint16(mss)},
		&expr.Immediate{Register: 1, Data: bigEndianUint16(mss)},
		&expr.Exthdr{SourceRegister: 1, Type: 2, Offset: 2, Len: 2, Op: expr.ExthdrOpTcpopt},
	}
}

func nativeUint32(v uint32) []byte {
	b := make([]byte, 4)
	binary.NativeEndian.PutUint32(b, v)
	return b
}

func bigEndianUint16(v uint16) []byte {
	b := make([]byte, 2)
	binary.BigEndian.PutUint16(b, v)
	return b
}

func ping6(target string, seq int) bool {
	conn, err := icmp.ListenPacket("ip6:ipv6-icmp", "::")
	if err != nil {
		fmt.Fprintf(os.Stderr, "listen: %v\n", err)
		return false
	}
	defer conn.Close()

	if err := conn.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		return false
	}

	msg := icmp.Message{
		Type: ipv6.ICMPTypeEchoRequest,
		Code: 0,
		Body: &icmp.Echo{
			ID:   os.Getpid() & 0xffff,
			Seq:  seq,
			Data: []byte("kubespan-probe"),
		},
	}
	wb, err := msg.Marshal(nil)
	if err != nil {
		return false
	}

	dst, err := net.ResolveIPAddr("ip6", target)
	if err != nil {
		fmt.Fprintf(os.Stderr, "resolve %s: %v\n", target, err)
		return false
	}

	if _, err := conn.WriteTo(wb, dst); err != nil {
		return false
	}

	rb := make([]byte, 1500)
	n, _, err := conn.ReadFrom(rb)
	if err != nil {
		return false
	}

	rm, err := icmp.ParseMessage(58, rb[:n]) // 58 = ICMPv6 protocol number
	if err != nil {
		return false
	}

	return rm.Type == ipv6.ICMPTypeEchoReply
}
