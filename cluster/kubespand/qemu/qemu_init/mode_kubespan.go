package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/agentydragon/ducktape/cluster/kubespand/agentconfig"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu"
	"gopkg.in/yaml.v3"
)

func modeKubespan(params map[string]string) {
	clusterID := params["cluster_id"]
	sharedSecret := params["shared_secret"]
	discovery := params["discovery"]
	topology := params["topology"]
	if topology == "" {
		topology = "flat"
	}

	if role == "" || role == "unknown" || clusterID == "" || sharedSecret == "" || discovery == "" {
		emitEvent(qemu.Event{
			Type:    qemu.EventError,
			Message: "missing kernel cmdline params",
			Error:   fmt.Sprintf("role=%s cluster_id=%s discovery=%s", role, clusterID, discovery),
		})
		poweroff()
	}

	emitEvent(qemu.Event{Type: qemu.EventBoot, Message: fmt.Sprintf("kubespan mode, role=%s, topology=%s", role, topology)})

	// Assign addresses based on role and topology.
	var linkIP, linkMask, peerBridgeIP, peerSubnet string
	var endpointFilters []string
	var listenPort int

	switch topology {
	case "flat", "discovery_only":
		linkMask = "24"
		switch role {
		case "a":
			linkIP = "192.168.50.1"
			peerBridgeIP = "192.168.50.2"
			listenPort = 51820
		case "b":
			linkIP = "192.168.50.2"
			peerBridgeIP = "192.168.50.1"
			listenPort = 51821
		default:
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s for topology=%s", role, topology)})
			poweroff()
		}
		endpointFilters = []string{"192.168.50.0/24"}
	case "cross_subnet":
		linkMask = "24"
		switch role {
		case "a":
			linkIP = "10.1.0.1"
			peerBridgeIP = "10.2.0.1"
			peerSubnet = "10.2.0.0/24"
			listenPort = 51820
		case "b":
			linkIP = "10.2.0.1"
			peerBridgeIP = "10.1.0.1"
			peerSubnet = "10.1.0.0/24"
			listenPort = 51821
		default:
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s for topology=%s", role, topology)})
			poweroff()
		}
		endpointFilters = []string{"10.0.0.0/8"}
	case "double_nat":
		linkMask = "24"
		switch role {
		case "vps":
			linkIP = "192.168.50.2"
			listenPort = 51820
		case "home":
			linkIP = "192.168.60.2"
			listenPort = 51821
		case "roaming":
			linkIP = "192.168.70.2"
			listenPort = 51822
		default:
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s for topology=double_nat", role)})
			poweroff()
		}
		// No endpoint filters — announce all addresses (auto-discovery).
	default:
		emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown topology=%s", topology), Error: "expected flat, cross_subnet, discovery_only, or double_nat"})
		poweroff()
	}

	// Load wireguard module.
	if err := runSilent("modprobe", "wireguard"); err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "modprobe wireguard failed", Error: err.Error()})
	}
	runSilent("modprobe", "virtio_net")
	emitEvent(qemu.Event{Type: qemu.EventModules, Message: "all modules loaded"})

	// Configure networking — all topologies use eth0 as the bridge interface.
	mustRun("ip", "link", "set", "lo", "up")
	waitForInterface("eth0")
	mustRun("ip", "link", "set", "eth0", "up")
	mustRun("ip", "addr", "add", linkIP+"/"+linkMask, "dev", "eth0")

	// Topology-specific routing.
	switch topology {
	case "double_nat":
		switch role {
		case "home":
			mustRun("ip", "route", "add", "default", "via", "192.168.60.1")
		case "roaming":
			mustRun("ip", "route", "add", "default", "via", "192.168.70.1")
		}
	case "cross_subnet":
		mustRun("ip", "route", "add", peerSubnet, "dev", "eth0")
		os.WriteFile("/proc/sys/net/ipv4/conf/eth0/rp_filter", []byte("1"), 0o644)
		os.WriteFile("/proc/sys/net/ipv4/conf/default/rp_filter", []byte("0"), 0o644)
	}

	// Enable IP forwarding (matches real NixOS VM with kubelet).
	// When ip_forward=1, the kernel sets rp_filter defaults and applies
	// stricter routing validation. We set rp_filter=2 (loose) on kubespan
	// to match NixOS defaults, and also set it on all/default to simulate
	// the real environment.
	os.WriteFile("/proc/sys/net/ipv4/ip_forward", []byte("1"), 0o644)
	os.WriteFile("/proc/sys/net/ipv4/conf/all/rp_filter", []byte("2"), 0o644)
	os.WriteFile("/proc/sys/net/ipv4/conf/default/rp_filter", []byte("2"), 0o644)

	emitEvent(qemu.Event{Type: qemu.EventNetwork, Message: fmt.Sprintf("link=%s/%s, topology=%s", linkIP, linkMask, topology)})

	// Build kubespand config.
	cfg := agentconfig.AgentConfig{
		Cluster: agentconfig.ClusterConfig{
			ID:     clusterID,
			Secret: sharedSecret,
		},
		Discovery: agentconfig.DiscoveryConfig{
			Endpoint:    discovery,
			Insecure:    true,
			MachineType: "worker",
		},
		Kubespan: agentconfig.KubespanConfig{
			ForceRouting:          true,
			ListenPort:            listenPort,
			MTU:                   1420,
			IdentityFile:          "/var/lib/kubespan/identity.yaml",
			EndpointFilters:       endpointFilters,
			HarvestExtraEndpoints: true,
		},
	}
	configData, err := yaml.Marshal(cfg)
	if err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "yaml marshal failed", Error: err.Error()})
		poweroff()
	}
	os.WriteFile("/etc/kubespan/agent.yaml", configData, 0o644)
	emitEvent(qemu.Event{Type: qemu.EventKubespand, Message: "config written"})

	// Start kubespand in the background.
	logFile, _ := os.Create("/tmp/kubespand.log")
	kubespandCmd := exec.Command("/kubespand", "-config", "/etc/kubespan/agent.yaml", "-debug")
	kubespandCmd.Stdout = logFile
	kubespandCmd.Stderr = logFile
	if err := kubespandCmd.Start(); err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "kubespand failed to start", Error: err.Error()})
		poweroff()
	}
	emitEvent(qemu.Event{Type: qemu.EventKubespand, Message: fmt.Sprintf("started pid=%d", kubespandCmd.Process.Pid)})

	const probePort = 9999

	if topology == "double_nat" {
		// 3-node topology: VPS and NAT1 listen, NAT2 probes.
		switch role {
		case "vps":
			cancel := serveTCP(probePort)
			defer cancel()
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "role=vps listening, waiting"})
			time.Sleep(300 * time.Second)
		case "nat1":
			cancel := serveTCP(probePort)
			defer cancel()
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "role=nat1 listening, waiting"})
			time.Sleep(300 * time.Second)
		case "nat2":
			peerAddrs := waitForPeers(kubespandCmd, 2)
			emitEvent(qemu.Event{Type: qemu.EventDiscovery, Message: fmt.Sprintf("discovered %d peers", len(peerAddrs))})
			runDoubleNATProbes(peerAddrs, probePort)
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "probes completed"})
		}
	} else {
		// 2-node topology.
		peerAddr := waitForPeer(kubespandCmd)
		emitEvent(qemu.Event{Type: qemu.EventDiscovery, Message: "peer discovered", PeerAddr: peerAddr, PeerIPv4: peerBridgeIP})

		if role == "b" {
			cancel := serveTCP(probePort)
			defer cancel()
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: fmt.Sprintf("role=b listening on tcp/%d, waiting (180s max)", probePort)})
			time.Sleep(180 * time.Second)
		} else {
			runProbes(peerAddr, peerBridgeIP, topology, probePort)
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "probes completed"})
		}
	}

	kubespandCmd.Process.Kill()
	poweroff()
}

func waitForPeer(kubespandCmd *exec.Cmd) string {
	deadline := time.Now().Add(180 * time.Second)
	for time.Now().Before(deadline) {
		if kubespandCmd.ProcessState != nil {
			emitEvent(qemu.Event{Type: qemu.EventError, Message: "kubespand exited prematurely", Error: "kubespand crashed"})
			dumpLog("/tmp/kubespand.log")
			poweroff()
		}
		addr := extractPeerAddr("/tmp/kubespand.log")
		if addr != "" {
			return addr
		}
		time.Sleep(2 * time.Second)
	}
	emitEvent(qemu.Event{Type: qemu.EventError, Message: "timed out waiting for peer discovery (180s)", Error: "peer discovery timeout"})
	dumpLog("/tmp/kubespand.log")
	kubespandCmd.Process.Kill()
	poweroff()
	return ""
}

func extractPeerAddr(logPath string) string {
	addrs := extractPeerAddrs(logPath)
	if len(addrs) == 0 {
		return ""
	}
	return addrs[len(addrs)-1]
}

func extractPeerAddrs(logPath string) []string {
	f, err := os.Open(logPath)
	if err != nil {
		return nil
	}
	defer f.Close()
	seen := map[string]struct{}{}
	var addrs []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.Contains(line, "configuring peer") {
			continue
		}
		if idx := strings.Index(line, `"address": "`); idx >= 0 {
			rest := line[idx+len(`"address": "`):]
			if end := strings.IndexByte(rest, '"'); end >= 0 {
				addr := rest[:end]
				if _, ok := seen[addr]; !ok {
					seen[addr] = struct{}{}
					addrs = append(addrs, addr)
				}
			}
		}
	}
	return addrs
}

func waitForPeers(kubespandCmd *exec.Cmd, n int) []string {
	deadline := time.Now().Add(180 * time.Second)
	for time.Now().Before(deadline) {
		if kubespandCmd.ProcessState != nil {
			emitEvent(qemu.Event{Type: qemu.EventError, Message: "kubespand exited prematurely", Error: "kubespand crashed"})
			dumpLog("/tmp/kubespand.log")
			poweroff()
		}
		addrs := extractPeerAddrs("/tmp/kubespand.log")
		if len(addrs) >= n {
			return addrs
		}
		time.Sleep(2 * time.Second)
	}
	emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("timed out waiting for %d peers (180s)", n), Error: "peer discovery timeout"})
	dumpLog("/tmp/kubespand.log")
	kubespandCmd.Process.Kill()
	poweroff()
	return nil
}

func runProbes(peerAddr, peerBridgeIP, topology string, tcpPort int) {
	// 1. ICMPv6 to peer's KubeSpan ULA address (WireGuard handles directly).
	emitProbe("ipv6 ULA icmp", peerAddr, probe(peerAddr, 60*time.Second))

	// 2. ICMPv4 to peer's bridge IP through KubeSpan.
	// In flat topology, this IP is also the WireGuard endpoint — tests
	// that the fwmark mechanism correctly avoids routing loops.
	emitProbe("ipv4 peer eth0 icmp", peerBridgeIP, probe(peerBridgeIP, 60*time.Second))

	// 3. TCP to peer's KubeSpan ULA address (tests L4 over WireGuard).
	emitProbe("ipv6 ULA tcp", fmt.Sprintf("[%s]:%d", peerAddr, tcpPort),
		tcpProbe(peerAddr, tcpPort, 30*time.Second))

	// 4. TCP to peer's bridge IPv4 through KubeSpan (tests the full stack:
	//    nftables mark → policy route → WireGuard → TCP handshake).
	emitProbe("ipv4 peer eth0 tcp", fmt.Sprintf("%s:%d", peerBridgeIP, tcpPort),
		tcpProbe(peerBridgeIP, tcpPort, 30*time.Second))
}

func runDoubleNATProbes(peerAddrs []string, tcpPort int) {
	// Probe each peer's ULA via ICMP and TCP (cross-NAT WireGuard tunnel).
	for i, addr := range peerAddrs {
		label := fmt.Sprintf("peer %d", i+1)
		emitProbe(label+" ULA icmp", addr, probe(addr, 60*time.Second))
		emitProbe(label+" ULA tcp", fmt.Sprintf("[%s]:%d", addr, tcpPort),
			tcpProbe(addr, tcpPort, 30*time.Second))
	}
}

func emitProbe(msg, target string, ok bool) {
	evt := qemu.Event{Type: qemu.EventProbe, Message: msg, Target: target, Success: &ok}
	if !ok {
		evt.Error = "probe failed"
		dumpLog("/tmp/kubespand.log")
	}
	emitEvent(evt)
}
