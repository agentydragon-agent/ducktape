// Binary qemu_init is the PID-1 init process for QEMU test VMs.
// Emits structured JSON events to stdout for the Go test orchestrator.
// ICMP ping and nft-smoke tests are linked in directly.
//
// Dispatches on mode= kernel cmdline parameter:
//
//	mode=nft_smoke  - Load nftables modules, run nft-smoke levels
//	mode=kubespan   - Load all modules, configure networking, run kubespand
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/netip"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/agentydragon/ducktape/cluster/kubespand/agentconfig"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu"
	"gopkg.in/yaml.v3"
)

var role = "unknown"

func emitEvent(evt qemu.Event) {
	evt.Timestamp = float64(uptime())
	evt.Role = role
	b, _ := json.Marshal(evt)
	fmt.Println(string(b))
}

func uptime() int64 {
	data, err := os.ReadFile("/proc/uptime")
	if err != nil {
		return 0
	}
	parts := strings.Fields(string(data))
	if len(parts) == 0 {
		return 0
	}
	dotIdx := strings.Index(parts[0], ".")
	if dotIdx < 0 {
		v, _ := strconv.ParseInt(parts[0], 10, 64)
		return v
	}
	v, _ := strconv.ParseInt(parts[0][:dotIdx], 10, 64)
	return v
}

func run(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func runSilent(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Stdout = nil
	cmd.Stderr = nil
	return cmd.Run()
}

func mustRun(name string, args ...string) {
	if err := run(name, args...); err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("%s failed: %v", name, err), Error: err.Error()})
		poweroff()
	}
}

func poweroff() {
	f, err := os.OpenFile("/proc/sysrq-trigger", os.O_WRONLY, 0)
	if err == nil {
		f.WriteString("o")
		f.Close()
	}
	time.Sleep(5 * time.Second)
	os.Exit(1)
}

func main() {
	// Set PATH for busybox symlinks in /sbin and /usr/sbin.
	os.Setenv("PATH", "/sbin:/usr/sbin:/bin:/usr/bin")

	// Mount essential filesystems.
	syscall.Mount("proc", "/proc", "proc", 0, "")
	syscall.Mount("sys", "/sys", "sysfs", 0, "")
	syscall.Mount("dev", "/dev", "devtmpfs", 0, "")
	os.MkdirAll("/tmp", 0o755)
	os.MkdirAll("/var/lib/kubespan", 0o755)
	os.MkdirAll("/etc/kubespan", 0o755)
	os.MkdirAll("/run", 0o755)

	// Suppress kernel messages on console.
	runSilent("dmesg", "-n", "1")

	// Parse kernel command line.
	params := parseCmdline()
	if v, ok := params["role"]; ok {
		role = v
	}

	mode := params["mode"]
	if mode == "" {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "no mode= on kernel cmdline", Error: "missing mode parameter"})
		poweroff()
	}

	// Enable EBUSY retry for all nftables operations (QEMU TCG is slow).
	ebusyRetry = true

	// Load nftables modules (common to both modes).
	loadNftablesModules()

	switch mode {
	case "nft_smoke":
		modeNftSmoke(params)
	case "kubespan":
		modeKubespan(params)
	default:
		emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown mode=%s", mode), Error: "expected nft_smoke or kubespan"})
		poweroff()
	}
}

func parseCmdline() map[string]string {
	data, _ := os.ReadFile("/proc/cmdline")
	params := make(map[string]string)
	for _, arg := range strings.Fields(string(data)) {
		if i := strings.IndexByte(arg, '='); i >= 0 {
			params[arg[:i]] = arg[i+1:]
		}
	}
	return params
}

func loadNftablesModules() {
	kvers, _ := os.ReadDir("/lib/modules")
	if len(kvers) == 0 {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "no kernel modules found", Error: "empty /lib/modules/"})
		poweroff()
	}
	kver := kvers[0].Name()

	// crc32c_generic must be loaded before libcrc32c.
	runSilent("modprobe", "crc32c_generic")
	if err := runSilent("modprobe", "nf_tables"); err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "modprobe nf_tables failed", Error: err.Error()})
	}
	emitEvent(qemu.Event{Type: qemu.EventModules, Message: fmt.Sprintf("nftables modules loaded, kver=%s", kver)})
}

func modeNftSmoke(params map[string]string) {
	levels := params["levels"]
	if levels == "" {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "no levels= on kernel cmdline", Error: "missing levels parameter"})
		poweroff()
	}

	emitEvent(qemu.Event{Type: qemu.EventBoot, Message: fmt.Sprintf("nft_smoke mode, levels=%s", levels)})

	anyFail := false
	for _, level := range strings.Split(levels, ",") {
		level = strings.TrimSpace(level)
		if level == "" {
			continue
		}
		levelNum, err := strconv.Atoi(level)
		if err != nil {
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("invalid level %q", level), Error: err.Error()})
			anyFail = true
			continue
		}
		exitCode := runNftSmokeLevel(levelNum)
		success := exitCode == 0
		if !success {
			anyFail = true
		}
		emitEvent(qemu.Event{Type: qemu.EventProbe, Message: fmt.Sprintf("level %s", level), Target: "nft-smoke-" + level, Success: &success})
	}

	if anyFail {
		emitEvent(qemu.Event{Type: qemu.EventDone, Message: "some levels failed", Error: "not all nft-smoke levels passed"})
	} else {
		emitEvent(qemu.Event{Type: qemu.EventDone, Message: "all levels passed"})
	}
	poweroff()
}

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
	var linkIP, linkMask, peerEth1IP, peerSubnet string
	var endpointFilters []string
	var extraEndpoints []netip.AddrPort
	var listenPort int

	switch topology {
	case "flat", "discovery_only":
		linkMask = "24"
		switch role {
		case "a":
			linkIP = "192.168.50.1"
			peerEth1IP = "192.168.50.2"
			listenPort = 51820
		case "b":
			linkIP = "192.168.50.2"
			peerEth1IP = "192.168.50.1"
			listenPort = 51821
		default:
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s for topology=%s", role, topology)})
			poweroff()
		}
		endpointFilters = []string{"192.168.50.0/24"}
		if topology == "flat" {
			extraEndpoints = []netip.AddrPort{
				netip.MustParseAddrPort(fmt.Sprintf("%s:%d", linkIP, listenPort)),
			}
		}
	case "cross_subnet":
		linkMask = "24"
		switch role {
		case "a":
			linkIP = "10.1.0.1"
			peerEth1IP = "10.2.0.1"
			peerSubnet = "10.2.0.0/24"
			listenPort = 51820
		case "b":
			linkIP = "10.2.0.1"
			peerEth1IP = "10.1.0.1"
			peerSubnet = "10.1.0.0/24"
			listenPort = 51821
		default:
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s for topology=%s", role, topology)})
			poweroff()
		}
		endpointFilters = []string{"10.0.0.0/8"}
		extraEndpoints = []netip.AddrPort{
			netip.MustParseAddrPort(fmt.Sprintf("%s:%d", linkIP, listenPort)),
		}
	case "double_nat":
		linkMask = "24"
		switch role {
		case "vps":
			linkIP = "192.168.50.3"
			listenPort = 51820
			endpointFilters = []string{"192.168.50.0/24", "192.168.60.0/24"}
		case "home":
			linkIP = "192.168.50.1"
			listenPort = 51821
			endpointFilters = []string{"192.168.50.0/24"}
			peerEth1IP = "192.168.50.1" // home's own eth1 for cross-bridge probe target
		case "roaming":
			linkIP = "192.168.60.2"
			listenPort = 51822
			endpointFilters = []string{"192.168.60.0/24"}
			peerEth1IP = "192.168.50.1" // home's eth1 for cross-bridge probe target
		default:
			emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s for topology=double_nat", role)})
			poweroff()
		}
		// No extra_endpoints — rely on discovery-based endpoint announcement.
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

	// Configure networking.
	waitForInterface("eth0")
	mustRun("ip", "link", "set", "lo", "up")
	mustRun("ip", "link", "set", "eth0", "up")
	mustRun("ip", "addr", "add", "10.0.2.15/24", "dev", "eth0")
	mustRun("ip", "route", "add", "default", "via", "10.0.2.2")

	waitForInterface("eth1")
	mustRun("ip", "link", "set", "eth1", "up")
	mustRun("ip", "addr", "add", linkIP+"/"+linkMask, "dev", "eth1")

	// Cross-subnet: add route to peer subnet and configure rpfilter.
	if topology == "cross_subnet" {
		mustRun("ip", "route", "add", peerSubnet, "dev", "eth1")
		os.WriteFile("/proc/sys/net/ipv4/conf/eth1/rp_filter", []byte("1"), 0o644)
		os.WriteFile("/proc/sys/net/ipv4/conf/default/rp_filter", []byte("0"), 0o644)
	}

	// Double-NAT: configure VPS second interface + cross-bridge routes.
	if topology == "double_nat" {
		if role == "vps" {
			waitForInterface("eth2")
			mustRun("ip", "link", "set", "eth2", "up")
			mustRun("ip", "addr", "add", "192.168.60.3/24", "dev", "eth2")
		}
		switch role {
		case "home":
			mustRun("ip", "route", "add", "192.168.60.0/24", "via", "192.168.50.3")
		case "roaming":
			mustRun("ip", "route", "add", "192.168.50.0/24", "via", "192.168.60.3")
		}
	}

	// Enable IP forwarding (matches real NixOS VM with kubelet).
	// When ip_forward=1, the kernel sets rp_filter defaults and applies
	// stricter routing validation. We set rp_filter=2 (loose) on kubespan
	// to match NixOS defaults, and also set it on all/default to simulate
	// the real environment.
	os.WriteFile("/proc/sys/net/ipv4/ip_forward", []byte("1"), 0o644)
	os.WriteFile("/proc/sys/net/ipv4/conf/all/rp_filter", []byte("2"), 0o644)
	os.WriteFile("/proc/sys/net/ipv4/conf/default/rp_filter", []byte("2"), 0o644)

	emitEvent(qemu.Event{Type: qemu.EventNetwork, Message: fmt.Sprintf("eth1=%s/%s, topology=%s", linkIP, linkMask, topology)})

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
			ForceRouting:    true,
			ListenPort:      listenPort,
			MTU:             1420,
			IdentityFile:    "/var/lib/kubespan/identity.yaml",
			EndpointFilters: endpointFilters,
			ExtraEndpoints:  extraEndpoints,
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
		// 3-node topology: VPS and Home listen, Roaming probes.
		switch role {
		case "vps":
			cancel := serveTCP(probePort)
			defer cancel()
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "role=vps listening, waiting"})
			time.Sleep(300 * time.Second)
		case "home":
			cancel := serveTCP(probePort)
			defer cancel()
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "role=home listening, waiting"})
			time.Sleep(300 * time.Second)
		case "roaming":
			peerAddrs := waitForPeers(kubespandCmd, 2)
			emitEvent(qemu.Event{Type: qemu.EventDiscovery, Message: fmt.Sprintf("discovered %d peers", len(peerAddrs))})
			runDoubleNATProbes(peerAddrs, peerEth1IP, probePort)
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "probes completed"})
		}
	} else {
		// 2-node topology.
		peerAddr := waitForPeer(kubespandCmd)
		emitEvent(qemu.Event{Type: qemu.EventDiscovery, Message: "peer discovered", PeerAddr: peerAddr, PeerIPv4: peerEth1IP})

		if role == "b" {
			cancel := serveTCP(probePort)
			defer cancel()
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: fmt.Sprintf("role=b listening on tcp/%d, waiting (180s max)", probePort)})
			time.Sleep(180 * time.Second)
		} else {
			runProbes(peerAddr, peerEth1IP, topology, probePort)
			emitEvent(qemu.Event{Type: qemu.EventDone, Message: "probes completed"})
		}
	}

	kubespandCmd.Process.Kill()
	poweroff()
}

func waitForInterface(name string) {
	path := "/sys/class/net/" + name
	for i := 0; i < 50; i++ {
		if _, err := os.Stat(path); err == nil {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("%s not found after 10s", name), Error: fmt.Sprintf("%s interface missing", name)})
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

func dumpLog(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	os.Stderr.Write(data)
}

func runProbes(peerAddr, peerEth1IP, topology string, tcpPort int) {
	// 1. ICMPv6 to peer's KubeSpan ULA address (WireGuard handles directly).
	emitProbe("ipv6 ULA icmp", peerAddr, probe(peerAddr, 60*time.Second))

	// 2. ICMPv4 to peer's eth1 IP through KubeSpan.
	// In flat topology, this IP is also the WireGuard endpoint — tests
	// that the fwmark mechanism correctly avoids routing loops.
	emitProbe("ipv4 peer eth1 icmp", peerEth1IP, probe(peerEth1IP, 60*time.Second))

	// 3. TCP to peer's KubeSpan ULA address (tests L4 over WireGuard).
	emitProbe("ipv6 ULA tcp", fmt.Sprintf("[%s]:%d", peerAddr, tcpPort),
		tcpProbe(peerAddr, tcpPort, 30*time.Second))

	// 4. TCP to peer's eth1 IPv4 through KubeSpan (tests the full stack:
	//    nftables mark → policy route → WireGuard → TCP handshake).
	emitProbe("ipv4 peer eth1 tcp", fmt.Sprintf("%s:%d", peerEth1IP, tcpPort),
		tcpProbe(peerEth1IP, tcpPort, 30*time.Second))
}

func runDoubleNATProbes(peerAddrs []string, homeEth1IP string, tcpPort int) {
	// Probe each peer's ULA via ICMP and TCP.
	for i, addr := range peerAddrs {
		label := fmt.Sprintf("peer %d", i+1)
		emitProbe(label+" ULA icmp", addr, probe(addr, 60*time.Second))
		emitProbe(label+" ULA tcp", fmt.Sprintf("[%s]:%d", addr, tcpPort),
			tcpProbe(addr, tcpPort, 30*time.Second))
	}
	// Probe Home's eth1 IP through kubespan (cross-bridge connectivity test).
	emitProbe("home eth1 icmp", homeEth1IP, probe(homeEth1IP, 60*time.Second))
	emitProbe("home eth1 tcp", fmt.Sprintf("%s:%d", homeEth1IP, tcpPort),
		tcpProbe(homeEth1IP, tcpPort, 30*time.Second))
}

func emitProbe(msg, target string, ok bool) {
	evt := qemu.Event{Type: qemu.EventProbe, Message: msg, Target: target, Success: &ok}
	if !ok {
		evt.Error = "probe failed"
		dumpLog("/tmp/kubespand.log")
	}
	emitEvent(evt)
}
