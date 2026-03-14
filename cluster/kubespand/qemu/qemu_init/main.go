// Binary qemu_init is the PID-1 init process for QEMU test VMs.
// Emits structured JSON events to stdout for the Go test orchestrator.
// ICMP ping and nft-smoke tests are linked in directly.
//
// Dispatches on mode= kernel cmdline parameter:
//
//	mode=nft_smoke  - Load nftables modules, run nft-smoke levels
//	mode=kubespan   - Load all modules, configure networking, run kubespand
//	mode=router     - NAT router (masquerade + ip_forward), no kubespand
//	mode=discovery  - Run discovery service on configured IP
package main

import (
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

	// Load nftables modules (common to all modes except discovery).
	if mode != "discovery" {
		loadNftablesModules()
	}

	switch mode {
	case "nft_smoke":
		modeNftSmoke(params)
	case "kubespan":
		modeKubespan(params)
	case "router":
		modeRouter(params)
	case "discovery":
		modeDiscovery(params)
	default:
		emitEvent(qemu.Event{Type: qemu.EventError, Message: fmt.Sprintf("unknown mode=%s", mode), Error: "expected nft_smoke, kubespan, router, or discovery"})
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

func dumpLog(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	os.Stderr.Write(data)
}
