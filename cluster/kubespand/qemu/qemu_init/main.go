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
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu"
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
	var linkIP, linkMask, peerEth1IP, peerSubnet, endpointFilter string
	var listenPort int

	switch role {
	case "a":
		listenPort = 51820
	case "b":
		listenPort = 51821
	default:
		emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown role=%s", role)})
		poweroff()
	}

	switch topology {
	case "flat":
		linkMask = "24"
		endpointFilter = "192.168.50.0/24"
		switch role {
		case "a":
			linkIP = "192.168.50.1"
			peerEth1IP = "192.168.50.2"
		case "b":
			linkIP = "192.168.50.2"
			peerEth1IP = "192.168.50.1"
		}
	case "cross_subnet":
		linkMask = "24"
		endpointFilter = "10.0.0.0/8"
		switch role {
		case "a":
			linkIP = "10.1.0.1"
			peerEth1IP = "10.2.0.1"
			peerSubnet = "10.2.0.0/24"
		case "b":
			linkIP = "10.2.0.1"
			peerEth1IP = "10.1.0.1"
			peerSubnet = "10.1.0.0/24"
		}
	default:
		emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown topology=%s", topology), Error: "expected flat or cross_subnet"})
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

	emitEvent(qemu.Event{Type: qemu.EventNetwork, Message: fmt.Sprintf("eth1=%s/%s, topology=%s", linkIP, linkMask, topology)})

	// Write kubespand config.
	config := fmt.Sprintf(`cluster:
  id: "%s"
  secret: "%s"
discovery:
  endpoint: "%s"
  insecure: true
  machine_type: worker
kubespan:
  force_routing: true
  listen_port: %d
  mtu: 1420
  identity_file: /var/lib/kubespan/identity.yaml
  extra_endpoints:
    - "%s:%d"
  endpoint_filters:
    - "%s"
`, clusterID, sharedSecret, discovery, listenPort, linkIP, listenPort, endpointFilter)
	os.WriteFile("/etc/kubespan/agent.yaml", []byte(config), 0o644)
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

	// Wait for peer discovery.
	peerAddr := waitForPeer(kubespandCmd)
	emitEvent(qemu.Event{Type: qemu.EventDiscovery, Message: "peer discovered", PeerAddr: peerAddr, PeerIPv4: peerEth1IP})

	// Only VM-A runs probes. VM-B stays alive.
	if role == "a" {
		runProbes(peerAddr, peerEth1IP, topology)
		emitEvent(qemu.Event{Type: qemu.EventDone, Message: "probes completed"})
	} else {
		emitEvent(qemu.Event{Type: qemu.EventDone, Message: "role=b waiting for probe (180s max)"})
		time.Sleep(180 * time.Second)
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
	f, err := os.Open(logPath)
	if err != nil {
		return ""
	}
	defer f.Close()
	var lastAddr string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.Contains(line, "configuring peer") {
			continue
		}
		if idx := strings.Index(line, `"address": "`); idx >= 0 {
			rest := line[idx+len(`"address": "`):]
			if end := strings.IndexByte(rest, '"'); end >= 0 {
				lastAddr = rest[:end]
			}
		}
	}
	return lastAddr
}

func dumpLog(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	os.Stderr.Write(data)
}

func runProbes(peerAddr, peerEth1IP, topology string) {
	v6ok := probe(peerAddr, 60*time.Second)
	emitEvent(qemu.Event{Type: qemu.EventProbe, Message: "ipv6 ULA connectivity", Target: peerAddr, Success: &v6ok, Error: boolErr(!v6ok, "probe failed")})
	if !v6ok {
		dumpLog("/tmp/kubespand.log")
	}

	if topology == "cross_subnet" {
		v4ok := probe(peerEth1IP, 60*time.Second)
		emitEvent(qemu.Event{Type: qemu.EventProbe, Message: "ipv4 cross-subnet connectivity", Target: peerEth1IP, Success: &v4ok, Error: boolErr(!v4ok, "probe failed")})
		if !v4ok {
			dumpLog("/tmp/kubespand.log")
		}
	}
}

func boolErr(cond bool, msg string) string {
	if cond {
		return msg
	}
	return ""
}
