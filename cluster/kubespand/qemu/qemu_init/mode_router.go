package main

import (
	"fmt"
	"os"

	"github.com/google/nftables"
	"github.com/google/nftables/expr"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu"
)

func modeRouter(params map[string]string) {
	internetIP := params["internet_ip"]
	lanIP := params["lan_ip"]
	if internetIP == "" || lanIP == "" {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "missing internet_ip or lan_ip", Error: fmt.Sprintf("internet_ip=%s lan_ip=%s", internetIP, lanIP)})
		poweroff()
	}

	emitEvent(qemu.Event{Type: qemu.EventBoot, Message: fmt.Sprintf("router mode, internet=%s, lan=%s", internetIP, lanIP)})

	// Load NAT-related kernel modules.
	for _, mod := range []string{"nf_conntrack", "nf_nat", "nft_masq", "nft_chain_nat"} {
		runSilent("modprobe", mod)
	}
	runSilent("modprobe", "virtio_net")

	// Configure eth0 (internet bridge).
	waitForInterface("eth0")
	mustRun("ip", "link", "set", "lo", "up")
	mustRun("ip", "link", "set", "eth0", "up")
	mustRun("ip", "addr", "add", internetIP, "dev", "eth0")

	// Configure eth1 (LAN bridge).
	waitForInterface("eth1")
	mustRun("ip", "link", "set", "eth1", "up")
	mustRun("ip", "addr", "add", lanIP, "dev", "eth1")

	// Enable IP forwarding.
	os.WriteFile("/proc/sys/net/ipv4/ip_forward", []byte("1"), 0o644)

	// Set up nftables masquerade on eth0.
	conn, err := nftables.New()
	if err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "nftables.New() failed", Error: err.Error()})
		poweroff()
	}
	table := conn.AddTable(&nftables.Table{Family: nftables.TableFamilyIPv4, Name: "nat"})
	chain := conn.AddChain(&nftables.Chain{
		Name:     "postrouting",
		Table:    table,
		Type:     nftables.ChainTypeNAT,
		Hooknum:  nftables.ChainHookPostrouting,
		Priority: nftables.ChainPriorityNATSource,
	})
	conn.AddRule(&nftables.Rule{
		Table: table,
		Chain: chain,
		Exprs: []expr.Any{
			// Match oifname == "eth0".
			&expr.Meta{Key: expr.MetaKeyOIFNAME, Register: 1},
			&expr.Cmp{
				Op:       expr.CmpOpEq,
				Register: 1,
				Data:     []byte("eth0\x00"),
			},
			&expr.Masq{},
		},
	})
	if err := conn.Flush(); err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "nftables flush failed", Error: err.Error()})
		poweroff()
	}

	emitEvent(qemu.Event{Type: qemu.EventNetwork, Message: fmt.Sprintf("router ready, internet=%s, lan=%s", internetIP, lanIP)})
	emitEvent(qemu.Event{Type: qemu.EventDone, Message: "router running"})

	// Sleep forever (router stays up until killed).
	select {}
}
