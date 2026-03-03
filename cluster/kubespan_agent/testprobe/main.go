// Binary testprobe provides test utilities for KubeSpan e2e tests:
//   - Default mode: sends ICMPv6 echo requests to verify tunnel connectivity
//   - -nft-smoke: tests nftables create/flush/delete to detect EBUSY issues
//   - -nft-flush: flushes entire nftables ruleset (removes Docker's nat table)
package main

import (
	"flag"
	"fmt"
	"net"
	"os"
	"time"

	"github.com/google/nftables"
	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv6"
)

func main() {
	timeout := flag.Duration("timeout", 30*time.Second, "overall timeout for probe")
	nftSmoke := flag.Bool("nft-smoke", false, "test nftables create/flush/delete instead of ping")
	nftFlush := flag.Bool("nft-flush", false, "flush entire nftables ruleset")
	flag.Parse()

	if *nftFlush {
		os.Exit(runNftFlush())
	}

	if *nftSmoke {
		os.Exit(runNftSmoke())
	}

	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: testprobe [-timeout duration] <ipv6-address>")
		fmt.Fprintln(os.Stderr, "       testprobe -nft-smoke")
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

// runNftSmoke tests that nftables operations work in this network namespace.
// Creates a test table, flushes it, and deletes it. Returns 0 on success, 1 on failure.
func runNftSmoke() int {
	// List existing tables for diagnostics.
	conn, err := nftables.New()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nftables.New: %v\n", err)
		return 1
	}
	tables, err := conn.ListTables()
	if err != nil {
		fmt.Fprintf(os.Stderr, "ListTables: %v\n", err)
	} else {
		fmt.Printf("existing tables: %d\n", len(tables))
		for _, t := range tables {
			fmt.Printf("  table %s family=%d\n", t.Name, t.Family)
		}
	}
	chains, err := conn.ListChains()
	if err != nil {
		fmt.Fprintf(os.Stderr, "ListChains: %v\n", err)
	} else {
		fmt.Printf("existing chains: %d\n", len(chains))
		for _, c := range chains {
			tbl := "<nil>"
			if c.Table != nil {
				tbl = c.Table.Name
			}
			fmt.Printf("  chain %s table=%s\n", c.Name, tbl)
		}
	}

	// Create a test table.
	conn2, err := nftables.New()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nftables.New (2): %v\n", err)
		return 1
	}
	table := conn2.AddTable(&nftables.Table{
		Family: nftables.TableFamilyINet,
		Name:   "testprobe_smoke",
	})
	fmt.Println("AddTable queued")
	if err := conn2.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "Flush (AddTable): %v\n", err)
		return 1
	}
	fmt.Println("AddTable flushed OK")

	// Add chains with hook registrations (matching kubespand's pattern).
	// This tests whether hook registration conflicts cause EBUSY.
	policy := nftables.ChainPolicyAccept
	conn2.AddChain(&nftables.Chain{
		Name:     "test_prerouting",
		Table:    table,
		Type:     nftables.ChainTypeFilter,
		Hooknum:  nftables.ChainHookPrerouting,
		Priority: nftables.ChainPriorityRaw,
		Policy:   &policy,
	})
	conn2.AddChain(&nftables.Chain{
		Name:     "test_output",
		Table:    table,
		Type:     nftables.ChainTypeRoute,
		Hooknum:  nftables.ChainHookOutput,
		Priority: nftables.ChainPriorityRaw,
		Policy:   &policy,
	})
	if err := conn2.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "Flush (AddChains): %v\n", err)
		return 1
	}
	fmt.Println("AddChains flushed OK")

	// Flush the table (remove all chains/rules).
	conn3, err := nftables.New()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nftables.New (3): %v\n", err)
		return 1
	}
	conn3.FlushTable(table)
	if err := conn3.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "Flush (FlushTable): %v\n", err)
		return 1
	}
	fmt.Println("FlushTable flushed OK")

	// Delete the table.
	conn4, err := nftables.New()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nftables.New (4): %v\n", err)
		return 1
	}
	conn4.DelTable(table)
	if err := conn4.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "Flush (DelTable): %v\n", err)
		return 1
	}
	fmt.Println("DelTable flushed OK")
	fmt.Println("nft-smoke: PASS")
	return 0
}

// runNftFlush flushes the entire nftables ruleset. Used to remove Docker's
// iptables-nft rules (nat table) from the container's network namespace before
// kubespand installs its own rules, avoiding EBUSY from conflicting nftables state.
func runNftFlush() int {
	conn, err := nftables.New()
	if err != nil {
		fmt.Fprintf(os.Stderr, "nftables.New: %v\n", err)
		return 1
	}

	tables, _ := conn.ListTables()
	fmt.Printf("tables before flush: %d\n", len(tables))
	for _, t := range tables {
		fmt.Printf("  table %s family=%d\n", t.Name, t.Family)
	}

	conn.FlushRuleset()
	if err := conn.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "FlushRuleset: %v\n", err)
		return 1
	}

	tables2, _ := conn.ListTables()
	fmt.Printf("tables after flush: %d\n", len(tables2))
	fmt.Println("nft-flush: OK")
	return 0
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
