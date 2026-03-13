package qemu

import (
	"bufio"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/bazelbuild/rules_go/go/runfiles"
)

// Runfile paths for test data (relative to workspace root).
const (
	vmlinuzPath     = "cluster/kubespand/qemu/vmlinuz-virt"
	initramfsPath   = "cluster/kubespand/qemu/initramfs.cpio.gz"
	discTarballPath = "third_party/siderolabs/discovery_service_load/tarball.tar"
)

// runfilePath resolves a Bazel runfile path using rules_go's runfiles library.
func runfilePath(t *testing.T, path string) string {
	t.Helper()
	p, err := runfiles.Rlocation("_main/" + path)
	if err != nil {
		t.Fatalf("runfile not found: %s: %v", path, err)
	}
	if _, err := os.Stat(p); err != nil {
		t.Fatalf("runfile not found: %s (resolved to %s): %v", path, p, err)
	}
	return p
}

func outputDir(t *testing.T) string {
	t.Helper()
	dir := os.Getenv("TEST_UNDECLARED_OUTPUTS_DIR")
	if dir == "" {
		dir = t.TempDir()
	}
	return dir
}

// vm represents a running QEMU VM.
type vm struct {
	name   string
	cmd    *exec.Cmd
	events []Event
	rawLog strings.Builder
	mu     sync.Mutex
	done   chan struct{}
	cancel func()
}

func (v *vm) wait() {
	<-v.done
}

func (v *vm) kill() {
	if v.cmd != nil && v.cmd.Process != nil {
		v.cmd.Process.Kill()
	}
}

func (v *vm) getEvents() []Event {
	v.mu.Lock()
	defer v.mu.Unlock()
	return append([]Event{}, v.events...)
}

func (v *vm) getRawLog() string {
	v.mu.Lock()
	defer v.mu.Unlock()
	return v.rawLog.String()
}

// bootVM starts a QEMU VM with the given kernel cmdline args.
func bootVM(t *testing.T, name string, vmlinuz, initramfs string, kernelArgs string, extraQemuArgs ...string) *vm {
	t.Helper()

	qemu := "qemu-system-x86_64"
	if _, err := exec.LookPath(qemu); err != nil {
		t.Skipf("%s not found on PATH", qemu)
	}

	args := []string{
		"-kernel", vmlinuz,
		"-initrd", initramfs,
		"-append", "console=ttyS0 panic=-1 quiet " + kernelArgs,
		"-nographic",
		"-no-reboot",
		"-m", "512",
		"-machine", "accel=tcg",
		"-cpu", "max",
		"-display", "none",
	}
	args = append(args, extraQemuArgs...)

	cmd := exec.Command(qemu, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatalf("stdout pipe: %v", err)
	}
	cmd.Stderr = cmd.Stdout // merge stderr into stdout

	v := &vm{
		name: name,
		cmd:  cmd,
		done: make(chan struct{}),
	}

	if err := cmd.Start(); err != nil {
		t.Fatalf("start QEMU %s: %v", name, err)
	}

	// Stream stdout, parse JSON events.
	go func() {
		defer close(v.done)
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()
			v.mu.Lock()
			v.rawLog.WriteString(line)
			v.rawLog.WriteByte('\n')
			v.mu.Unlock()

			var evt Event
			if json.Unmarshal([]byte(line), &evt) == nil && evt.Type != "" {
				v.mu.Lock()
				v.events = append(v.events, evt)
				v.mu.Unlock()
				t.Logf("[%s] %s: %s", name, evt.Type, evt.Message)
			}
		}
		cmd.Wait()
	}()

	return v
}

func saveArtifact(t *testing.T, dir, name, content string) {
	t.Helper()
	path := filepath.Join(dir, name)
	os.WriteFile(path, []byte(content), 0o644)
}

func saveEventsArtifact(t *testing.T, dir, name string, events []Event) {
	t.Helper()
	var sb strings.Builder
	for _, e := range events {
		b, _ := json.Marshal(e)
		sb.Write(b)
		sb.WriteByte('\n')
	}
	saveArtifact(t, dir, name, sb.String())
}

func randomBase64(n int) string {
	buf := make([]byte, n)
	rand.Read(buf)
	return base64.StdEncoding.EncodeToString(buf)
}

func randomPort() int {
	n, _ := rand.Int(rand.Reader, big.NewInt(50000))
	return 10000 + int(n.Int64())
}

// waitVMDone waits for a VM to finish with a timeout.
func waitVMDone(t *testing.T, v *vm, timeout time.Duration) bool {
	t.Helper()
	select {
	case <-v.done:
		return true
	case <-time.After(timeout):
		t.Errorf("%s did not finish within %v", v.name, timeout)
		v.kill()
		<-v.done
		return false
	}
}

// ─ TestNftSmoke ─────────────────────────────────────────────────────────────

func TestNftSmoke(t *testing.T) {
	vmlinuz := runfilePath(t, vmlinuzPath)
	initramfs := runfilePath(t, initramfsPath)
	out := outputDir(t)

	levels := "1,2,3,4,5,6"
	v := bootVM(t, "nft-smoke", vmlinuz, initramfs,
		fmt.Sprintf("mode=nft_smoke levels=%s", levels))

	if !waitVMDone(t, v, 120*time.Second) {
		saveArtifact(t, out, "nft-smoke.log", v.getRawLog())
		t.FailNow()
	}

	saveArtifact(t, out, "nft-smoke.log", v.getRawLog())
	saveEventsArtifact(t, out, "nft-smoke-events.jsonl", v.getEvents())

	// Verify all levels passed.
	events := v.getEvents()
	for _, e := range events {
		if e.Type == EventProbe && e.Success != nil && !*e.Success {
			t.Errorf("nft-smoke probe failed: %s (target=%s)", e.Message, e.Target)
		}
	}

	// Check for done event.
	var foundDone bool
	for _, e := range events {
		if e.Type == EventDone {
			foundDone = true
			if e.Error != "" {
				t.Errorf("nft-smoke done with error: %s", e.Error)
			}
		}
	}
	if !foundDone {
		t.Error("no done event received from VM")
	}
}

// ─ TestKubeSpanFlat ─────────────────────────────────────────────────────────

func TestKubeSpanFlat(t *testing.T) {
	runTopology(t, "flat")
}

// ─ TestKubeSpanCrossSubnet ──────────────────────────────────────────────────

func TestKubeSpanCrossSubnet(t *testing.T) {
	runTopology(t, "cross_subnet")
}

// ─ TestKubeSpanDiscoveryOnly ────────────────────────────────────────────────

func TestKubeSpanDiscoveryOnly(t *testing.T) {
	runTopology(t, "discovery_only")
}

// ─ TestKubeSpanDoubleNAT ────────────────────────────────────────────────────

func TestKubeSpanDoubleNAT(t *testing.T) {
	runThreeNodeTopology(t, "double_nat")
}

func runTopology(t *testing.T, topology string) {
	vmlinuz := runfilePath(t, vmlinuzPath)
	initramfs := runfilePath(t, initramfsPath)
	discTarball := runfilePath(t, discTarballPath)
	out := outputDir(t)

	if _, err := exec.LookPath("docker"); err != nil {
		t.Skip("docker not found on PATH")
	}

	// Generate random cluster parameters.
	clusterID := randomBase64(32)
	sharedSecret := randomBase64(32)
	mcastPort := randomPort()
	discPort := 3000 // discovery service default

	// Start discovery service.
	t.Log("loading discovery service image...")
	loadCmd := exec.Command("docker", "load", "-i", discTarball)
	loadCmd.Stderr = os.Stderr
	if err := loadCmd.Run(); err != nil {
		t.Fatalf("docker load: %v", err)
	}

	containerName := fmt.Sprintf("kubespan-disc-%s-%d", topology, time.Now().UnixMilli()%100000)
	dockerRun := exec.Command("docker", "run", "-d", "--name", containerName,
		"--network=host",
		"ghcr.io/siderolabs/discovery-service:latest",
		"-debug")
	dockerRun.Stderr = os.Stderr
	if out, err := dockerRun.Output(); err != nil {
		t.Fatalf("docker run: %v\n%s", err, out)
	}
	t.Cleanup(func() {
		exec.Command("docker", "rm", "-f", containerName).Run()
	})

	// Wait for discovery service to be ready.
	t.Log("waiting for discovery service...")
	for i := 0; i < 30; i++ {
		check := exec.Command("curl", "-sf", "--connect-timeout", "1",
			fmt.Sprintf("http://localhost:%d/", discPort))
		if check.Run() == nil {
			break
		}
		time.Sleep(500 * time.Millisecond)
	}
	t.Log("discovery service ready")

	// Network args for VM-to-VM L2 (socket mcast).
	mcastAddr := fmt.Sprintf("230.0.0.1:%d", mcastPort)
	netArgsA := []string{
		"-netdev", "user,id=net0",
		"-device", "virtio-net-pci,netdev=net0,mac=52:54:00:a0:00:01",
		"-netdev", fmt.Sprintf("socket,id=net1,mcast=%s", mcastAddr),
		"-device", "virtio-net-pci,netdev=net1,mac=52:54:00:a1:00:01",
	}
	netArgsB := []string{
		"-netdev", "user,id=net0",
		"-device", "virtio-net-pci,netdev=net0,mac=52:54:00:b0:00:01",
		"-netdev", fmt.Sprintf("socket,id=net1,mcast=%s", mcastAddr),
		"-device", "virtio-net-pci,netdev=net1,mac=52:54:00:b1:00:01",
	}

	kernelBase := fmt.Sprintf("mode=kubespan cluster_id=%s shared_secret=%s discovery=10.0.2.2:%d topology=%s",
		clusterID, sharedSecret, discPort, topology)

	// Boot VM-B first (it waits for probes).
	t.Log("booting VM-B...")
	vmB := bootVM(t, "vm-b", vmlinuz, initramfs, kernelBase+" role=b", netArgsB...)
	time.Sleep(time.Second) // avoid mcast race

	// Boot VM-A (runs probes).
	t.Log("booting VM-A...")
	vmA := bootVM(t, "vm-a", vmlinuz, initramfs, kernelBase+" role=a", netArgsA...)

	// Wait for VM-A to complete.
	waitVMDone(t, vmA, 300*time.Second)

	// Kill VM-B.
	vmB.kill()
	<-vmB.done

	// Save artifacts.
	saveArtifact(t, out, "vm-a.log", vmA.getRawLog())
	saveArtifact(t, out, "vm-b.log", vmB.getRawLog())
	saveEventsArtifact(t, out, "vm-a-events.jsonl", vmA.getEvents())
	saveEventsArtifact(t, out, "vm-b-events.jsonl", vmB.getEvents())

	// Save discovery logs.
	discLogs, _ := exec.Command("docker", "logs", containerName).CombinedOutput()
	saveArtifact(t, out, "discovery.log", string(discLogs))

	// Save test summary.
	summary := map[string]interface{}{
		"topology":    topology,
		"cluster_id":  clusterID,
		"mcast_port":  mcastPort,
		"vm_a_events": vmA.getEvents(),
		"vm_b_events": vmB.getEvents(),
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	saveArtifact(t, out, "test-summary.json", string(summaryJSON))

	// Verify probes.
	assertProbes(t, vmA.getEvents(), topology)
}

func runThreeNodeTopology(t *testing.T, topology string) {
	vmlinuz := runfilePath(t, vmlinuzPath)
	initramfs := runfilePath(t, initramfsPath)
	discTarball := runfilePath(t, discTarballPath)
	out := outputDir(t)

	if _, err := exec.LookPath("docker"); err != nil {
		t.Skip("docker not found on PATH")
	}

	// Generate random cluster parameters.
	clusterID := randomBase64(32)
	sharedSecret := randomBase64(32)
	mcastPortA := randomPort()
	mcastPortB := randomPort()
	discPort := 3000

	// Start discovery service.
	t.Log("loading discovery service image...")
	loadCmd := exec.Command("docker", "load", "-i", discTarball)
	loadCmd.Stderr = os.Stderr
	if err := loadCmd.Run(); err != nil {
		t.Fatalf("docker load: %v", err)
	}

	containerName := fmt.Sprintf("kubespan-disc-%s-%d", topology, time.Now().UnixMilli()%100000)
	dockerRun := exec.Command("docker", "run", "-d", "--name", containerName,
		"--network=host",
		"ghcr.io/siderolabs/discovery-service:latest",
		"-debug")
	dockerRun.Stderr = os.Stderr
	if out, err := dockerRun.Output(); err != nil {
		t.Fatalf("docker run: %v\n%s", err, out)
	}
	t.Cleanup(func() {
		exec.Command("docker", "rm", "-f", containerName).Run()
	})

	// Wait for discovery service to be ready.
	t.Log("waiting for discovery service...")
	for i := 0; i < 30; i++ {
		check := exec.Command("curl", "-sf", "--connect-timeout", "1",
			fmt.Sprintf("http://localhost:%d/", discPort))
		if check.Run() == nil {
			break
		}
		time.Sleep(500 * time.Millisecond)
	}
	t.Log("discovery service ready")

	kernelBase := fmt.Sprintf("mode=kubespan cluster_id=%s shared_secret=%s discovery=10.0.2.2:%d topology=%s",
		clusterID, sharedSecret, discPort, topology)

	mcastAddrA := fmt.Sprintf("230.0.0.1:%d", mcastPortA)
	mcastAddrB := fmt.Sprintf("230.0.0.1:%d", mcastPortB)

	// VPS: eth0 (NAT) + eth1 (bridge A) + eth2 (bridge B)
	netArgsVPS := []string{
		"-netdev", "user,id=net0",
		"-device", "virtio-net-pci,netdev=net0,mac=52:54:00:c0:00:01",
		"-netdev", fmt.Sprintf("socket,id=net1,mcast=%s", mcastAddrA),
		"-device", "virtio-net-pci,netdev=net1,mac=52:54:00:c1:00:01",
		"-netdev", fmt.Sprintf("socket,id=net2,mcast=%s", mcastAddrB),
		"-device", "virtio-net-pci,netdev=net2,mac=52:54:00:c2:00:01",
	}
	// Home: eth0 (NAT) + eth1 (bridge A)
	netArgsHome := []string{
		"-netdev", "user,id=net0",
		"-device", "virtio-net-pci,netdev=net0,mac=52:54:00:d0:00:01",
		"-netdev", fmt.Sprintf("socket,id=net1,mcast=%s", mcastAddrA),
		"-device", "virtio-net-pci,netdev=net1,mac=52:54:00:d1:00:01",
	}
	// Roaming: eth0 (NAT) + eth1 (bridge B)
	netArgsRoaming := []string{
		"-netdev", "user,id=net0",
		"-device", "virtio-net-pci,netdev=net0,mac=52:54:00:e0:00:01",
		"-netdev", fmt.Sprintf("socket,id=net1,mcast=%s", mcastAddrB),
		"-device", "virtio-net-pci,netdev=net1,mac=52:54:00:e1:00:01",
	}

	// Boot VPS first (router between bridges).
	t.Log("booting VPS...")
	vmVPS := bootVM(t, "vm-vps", vmlinuz, initramfs, kernelBase+" role=vps", netArgsVPS...)
	time.Sleep(time.Second)

	// Boot Home.
	t.Log("booting Home...")
	vmHome := bootVM(t, "vm-home", vmlinuz, initramfs, kernelBase+" role=home", netArgsHome...)
	time.Sleep(time.Second)

	// Boot Roaming (runs probes).
	t.Log("booting Roaming...")
	vmRoaming := bootVM(t, "vm-roaming", vmlinuz, initramfs, kernelBase+" role=roaming", netArgsRoaming...)

	// Wait for Roaming to complete.
	waitVMDone(t, vmRoaming, 300*time.Second)

	// Kill VPS and Home.
	vmVPS.kill()
	vmHome.kill()
	<-vmVPS.done
	<-vmHome.done

	// Save artifacts.
	saveArtifact(t, out, "vm-vps.log", vmVPS.getRawLog())
	saveArtifact(t, out, "vm-home.log", vmHome.getRawLog())
	saveArtifact(t, out, "vm-roaming.log", vmRoaming.getRawLog())
	saveEventsArtifact(t, out, "vm-vps-events.jsonl", vmVPS.getEvents())
	saveEventsArtifact(t, out, "vm-home-events.jsonl", vmHome.getEvents())
	saveEventsArtifact(t, out, "vm-roaming-events.jsonl", vmRoaming.getEvents())

	// Save discovery logs.
	discLogs, _ := exec.Command("docker", "logs", containerName).CombinedOutput()
	saveArtifact(t, out, "discovery.log", string(discLogs))

	// Save test summary.
	summary := map[string]interface{}{
		"topology":          topology,
		"cluster_id":        clusterID,
		"mcast_port_a":      mcastPortA,
		"mcast_port_b":      mcastPortB,
		"vm_vps_events":     vmVPS.getEvents(),
		"vm_home_events":    vmHome.getEvents(),
		"vm_roaming_events": vmRoaming.getEvents(),
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	saveArtifact(t, out, "test-summary.json", string(summaryJSON))

	// Verify probes from roaming VM.
	assertProbes(t, vmRoaming.getEvents(), topology)
}

func assertProbes(t *testing.T, events []Event, topology string) {
	t.Helper()

	probes := map[string]*bool{} // target -> success
	for _, e := range events {
		if e.Type == EventProbe && e.Success != nil {
			s := *e.Success
			probes[e.Message] = &s
		}
	}

	var requiredProbes []string
	switch topology {
	case "double_nat":
		requiredProbes = []string{
			"peer 1 ULA icmp",
			"peer 2 ULA icmp",
			"home eth1 icmp",
			"peer 1 ULA tcp",
			"peer 2 ULA tcp",
			"home eth1 tcp",
		}
	default:
		requiredProbes = []string{
			"ipv6 ULA icmp",
			"ipv4 peer eth1 icmp",
			"ipv6 ULA tcp",
			"ipv4 peer eth1 tcp",
		}
	}
	for _, name := range requiredProbes {
		if s, ok := probes[name]; !ok {
			t.Errorf("missing probe event: %s", name)
		} else if !*s {
			t.Errorf("probe failed: %s", name)
		}
	}

	// Check for errors.
	for _, e := range events {
		if e.Type == EventError {
			t.Errorf("VM error: %s (%s)", e.Message, e.Error)
		}
	}
}
