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
	vmlinuzPath            = "cluster/kubespand/qemu/vmlinuz-virt"
	initramfsPath          = "cluster/kubespand/qemu/initramfs.cpio.gz"
	initramfsDiscoveryPath = "cluster/kubespand/qemu/initramfs-discovery.cpio.gz"
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

	args := []string{
		"-kernel", vmlinuz,
		"-initrd", initramfs,
		"-append", "console=ttyS0 panic=-1 quiet " + kernelArgs,
		"-nographic",
		"-no-reboot",
		"-m", "1024",
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

// mcastNIC returns QEMU args for a virtio-net NIC on a multicast socket bridge.
func mcastNIC(id, mcastAddr, mac string) []string {
	return []string{
		"-netdev", fmt.Sprintf("socket,id=%s,mcast=%s", id, mcastAddr),
		"-device", fmt.Sprintf("virtio-net-pci,netdev=%s,mac=%s", id, mac),
	}
}

// killAndWait kills all VMs and waits for them to exit.
func killAndWait(vms ...*vm) {
	for _, v := range vms {
		v.kill()
	}
	for _, v := range vms {
		<-v.done
	}
}

// saveLogs saves raw log and event artifacts for this VM using its name.
func (v *vm) saveLogs(t *testing.T, dir string) {
	t.Helper()
	saveArtifact(t, dir, v.name+".log", v.getRawLog())
	saveEventsArtifact(t, dir, v.name+"-events.jsonl", v.getEvents())
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
	runDoubleNATTopology(t)
}

func runTopology(t *testing.T, topology string) {
	vmlinuz := runfilePath(t, vmlinuzPath)
	initramfs := runfilePath(t, initramfsPath)
	initramfsDisc := runfilePath(t, initramfsDiscoveryPath)
	out := outputDir(t)

	// Generate random cluster parameters.
	clusterID := randomBase64(32)
	sharedSecret := randomBase64(32)
	mcastPort := randomPort()

	// Discovery VM IP depends on topology.
	var discIP string
	switch topology {
	case "flat", "discovery_only":
		discIP = "192.168.50.254"
	case "cross_subnet":
		discIP = "10.1.0.254"
	}
	discAddr := fmt.Sprintf("%s:3000", discIP)

	// Network args — all VMs on a single mcast bridge, no QEMU NAT.
	mcastAddr := fmt.Sprintf("230.0.0.1:%d", mcastPort)

	kernelBase := fmt.Sprintf("mode=kubespan cluster_id=%s shared_secret=%s discovery=%s topology=%s",
		clusterID, sharedSecret, discAddr, topology)

	// Boot discovery VM first (uses discovery initramfs — no kubespand needed).
	t.Log("booting discovery VM...")
	vmDisc := bootVM(t, "vm-disc", vmlinuz, initramfsDisc,
		fmt.Sprintf("mode=discovery role=discovery discovery_ip=%s/24", discIP),
		mcastNIC("net0", mcastAddr, "52:54:00:ff:00:01")...)
	time.Sleep(3 * time.Second) // Wait for discovery service to come up.

	// Boot VM-B (it waits for probes).
	t.Log("booting VM-B...")
	vmB := bootVM(t, "vm-b", vmlinuz, initramfs, kernelBase+" role=b",
		mcastNIC("net0", mcastAddr, "52:54:00:b0:00:01")...)
	time.Sleep(time.Second) // avoid mcast race

	// Boot VM-A (runs probes).
	t.Log("booting VM-A...")
	vmA := bootVM(t, "vm-a", vmlinuz, initramfs, kernelBase+" role=a",
		mcastNIC("net0", mcastAddr, "52:54:00:a0:00:01")...)

	// Wait for VM-A to complete.
	waitVMDone(t, vmA, 300*time.Second)

	killAndWait(vmB, vmDisc)

	// Save artifacts.
	vmA.saveLogs(t, out)
	vmB.saveLogs(t, out)
	vmDisc.saveLogs(t, out)

	// Save test summary.
	summary := map[string]interface{}{
		"topology":       topology,
		"cluster_id":     clusterID,
		"mcast_port":     mcastPort,
		"vm_a_events":    vmA.getEvents(),
		"vm_b_events":    vmB.getEvents(),
		"vm_disc_events": vmDisc.getEvents(),
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	saveArtifact(t, out, "test-summary.json", string(summaryJSON))

	// Verify probes.
	assertProbes(t, vmA.getEvents(), topology)
}

func runDoubleNATTopology(t *testing.T) {
	vmlinuz := runfilePath(t, vmlinuzPath)
	initramfs := runfilePath(t, initramfsPath)
	initramfsDisc := runfilePath(t, initramfsDiscoveryPath)
	out := outputDir(t)

	// Generate random cluster parameters.
	clusterID := randomBase64(32)
	sharedSecret := randomBase64(32)

	// 3 multicast bridges: internet, LAN-A, LAN-B.
	mcastPortInternet := randomPort()
	mcastPortLanA := randomPort()
	mcastPortLanB := randomPort()
	mcastInternet := fmt.Sprintf("230.0.0.1:%d", mcastPortInternet)
	mcastLanA := fmt.Sprintf("230.0.0.1:%d", mcastPortLanA)
	mcastLanB := fmt.Sprintf("230.0.0.1:%d", mcastPortLanB)

	// Discovery runs in a dedicated VM on the internet bridge.
	const discAddr = "192.168.50.254:3000"

	kubespanBase := fmt.Sprintf("mode=kubespan cluster_id=%s shared_secret=%s discovery=%s topology=double_nat",
		clusterID, sharedSecret, discAddr)

	// Boot discovery VM first (uses discovery initramfs — no kubespand needed).
	t.Log("booting Discovery...")
	vmDiscovery := bootVM(t, "vm-disc", vmlinuz, initramfsDisc,
		"mode=discovery role=discovery discovery_ip=192.168.50.254/24",
		mcastNIC("net0", mcastInternet, "52:54:00:ff:00:01")...)
	time.Sleep(3 * time.Second) // Wait for discovery service to come up.

	// Boot VPS (kubespand only, discovery runs in separate VM).
	t.Log("booting VPS...")
	vmVPS := bootVM(t, "vm-vps", vmlinuz, initramfs, kubespanBase+" role=vps",
		mcastNIC("net0", mcastInternet, "52:54:00:c0:00:01")...)

	// Boot routers (NAT only, dual-NIC: internet + LAN).
	t.Log("booting Router-A...")
	vmRouterA := bootVM(t, "vm-router-a", vmlinuz, initramfs,
		"mode=router role=router-a internet_ip=192.168.50.1/24 lan_ip=192.168.60.1/24",
		append(mcastNIC("net0", mcastInternet, "52:54:00:c1:00:01"),
			mcastNIC("net1", mcastLanA, "52:54:00:c1:00:02")...)...)
	t.Log("booting Router-B...")
	vmRouterB := bootVM(t, "vm-router-b", vmlinuz, initramfs,
		"mode=router role=router-b internet_ip=192.168.50.3/24 lan_ip=192.168.70.1/24",
		append(mcastNIC("net0", mcastInternet, "52:54:00:c2:00:01"),
			mcastNIC("net1", mcastLanB, "52:54:00:c2:00:02")...)...)
	time.Sleep(time.Second) // Let routers initialize.

	// Boot NAT1 and NAT2 (kubespand, connect to discovery through routers).
	t.Log("booting NAT1...")
	vmNAT1 := bootVM(t, "vm-nat1", vmlinuz, initramfs, kubespanBase+" role=nat1",
		mcastNIC("net0", mcastLanA, "52:54:00:d0:00:01")...)
	time.Sleep(time.Second)

	t.Log("booting NAT2...")
	vmNAT2 := bootVM(t, "vm-nat2", vmlinuz, initramfs, kubespanBase+" role=nat2",
		mcastNIC("net0", mcastLanB, "52:54:00:e0:00:01")...)

	// Wait for NAT2 to complete (it runs probes).
	waitVMDone(t, vmNAT2, 300*time.Second)

	killAndWait(vmVPS, vmRouterA, vmRouterB, vmNAT1, vmDiscovery)

	// Save artifacts.
	vmDiscovery.saveLogs(t, out)
	vmVPS.saveLogs(t, out)
	vmRouterA.saveLogs(t, out)
	vmRouterB.saveLogs(t, out)
	vmNAT1.saveLogs(t, out)
	vmNAT2.saveLogs(t, out)

	// Save test summary.
	summary := map[string]interface{}{
		"topology":            "double_nat",
		"cluster_id":          clusterID,
		"mcast_port_internet": mcastPortInternet,
		"mcast_port_lan_a":    mcastPortLanA,
		"mcast_port_lan_b":    mcastPortLanB,
		"vm_disc_events":      vmDiscovery.getEvents(),
		"vm_vps_events":       vmVPS.getEvents(),
		"vm_router_a_events":  vmRouterA.getEvents(),
		"vm_router_b_events":  vmRouterB.getEvents(),
		"vm_nat1_events":      vmNAT1.getEvents(),
		"vm_nat2_events":      vmNAT2.getEvents(),
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	saveArtifact(t, out, "test-summary.json", string(summaryJSON))

	// Verify probes from NAT2 VM.
	assertProbes(t, vmNAT2.getEvents(), "double_nat")
}

// ─ TestTalosKubeSpanDoubleNAT ────────────────────────────────────────────────
// Diagnostic test: boots real Talos VMs (kernel+initramfs) through double NAT
// to verify whether upstream KubeSpan can establish WireGuard tunnels. If this
// fails, the problem is in the protocol/discovery service, not kubespand.

// Runfile paths for Talos artifacts.
const (
	talosVmlinuzPath   = "talos_vmlinuz_amd64/file/vmlinuz-amd64"
	talosInitramfsPath = "talos_initramfs_amd64/file/initramfs-amd64.xz"
	talosctlPath       = "talosctl_amd64/file/talosctl"
)

func TestTalosKubeSpanDoubleNAT(t *testing.T) {
	talosVmlinuz := runfilePath(t, talosVmlinuzPath)
	talosInitramfs := runfilePath(t, talosInitramfsPath)
	talosctlBin := runfilePath(t, talosctlPath)
	alpineVmlinuz := runfilePath(t, vmlinuzPath)
	alpineInitramfs := runfilePath(t, initramfsPath)
	alpineInitramfsDisc := runfilePath(t, initramfsDiscoveryPath)

	out := outputDir(t)
	tmpDir := t.TempDir()

	// 1. Generate shared Talos secrets.
	secretsFile := filepath.Join(tmpDir, "secrets.yaml")
	runCmd(t, talosctlBin, "gen", "secrets", "--output-file", secretsFile)

	// 2. Generate per-node configs using talosctl gen config with --config-patch.
	// Each call shares the same secrets (cluster identity) but applies node-specific patches.
	vpsConfig := genTalosNodeConfig(t, talosctlBin, secretsFile, tmpDir, "vps", "controlplane",
		buildTalosPatch("vps", "192.168.50.2/24", "", "192.168.50.0/24"))
	nat1Config := genTalosNodeConfig(t, talosctlBin, secretsFile, tmpDir, "nat1", "worker",
		buildTalosPatch("nat1", "192.168.60.2/24", "192.168.60.1", "192.168.60.0/24"))
	nat2Config := genTalosNodeConfig(t, talosctlBin, secretsFile, tmpDir, "nat2", "worker",
		buildTalosPatch("nat2", "192.168.70.2/24", "192.168.70.1", "192.168.70.0/24"))

	// 3. Create CIDATA volumes.
	vpsCI := createCIDATA(t, tmpDir, "vps", vpsConfig)
	nat1CI := createCIDATA(t, tmpDir, "nat1", nat1Config)
	nat2CI := createCIDATA(t, tmpDir, "nat2", nat2Config)

	// 3 multicast bridges: internet, lan1, lan2.
	mcastPortInternet := randomPort()
	mcastPortLan1 := randomPort()
	mcastPortLan2 := randomPort()
	mcastInternet := fmt.Sprintf("230.0.0.1:%d", mcastPortInternet)
	mcastLan1 := fmt.Sprintf("230.0.0.1:%d", mcastPortLan1)
	mcastLan2 := fmt.Sprintf("230.0.0.1:%d", mcastPortLan2)

	// 4. Boot discovery VM (Alpine).
	t.Log("booting Discovery VM...")
	vmDiscovery := bootVM(t, "talos-disc", alpineVmlinuz, alpineInitramfsDisc,
		"mode=discovery role=discovery discovery_ip=192.168.50.254/24",
		mcastNIC("net0", mcastInternet, "52:54:00:ff:00:01")...)
	time.Sleep(3 * time.Second)

	// 5. Boot router VMs (Alpine, dual-NIC: internet + LAN).
	t.Log("booting Router-1...")
	vmRouter1 := bootVM(t, "talos-router-1", alpineVmlinuz, alpineInitramfs,
		"mode=router role=router-1 internet_ip=192.168.50.1/24 lan_ip=192.168.60.1/24",
		append(mcastNIC("net0", mcastInternet, "52:54:00:c1:00:01"),
			mcastNIC("net1", mcastLan1, "52:54:00:c1:00:02")...)...)

	t.Log("booting Router-2...")
	vmRouter2 := bootVM(t, "talos-router-2", alpineVmlinuz, alpineInitramfs,
		"mode=router role=router-2 internet_ip=192.168.50.3/24 lan_ip=192.168.70.1/24",
		append(mcastNIC("net0", mcastInternet, "52:54:00:c2:00:01"),
			mcastNIC("net1", mcastLan2, "52:54:00:c2:00:02")...)...)
	time.Sleep(time.Second)

	// 6. Boot Talos VMs.
	talosAPIPort := randomPort()
	t.Logf("booting Talos VPS (talosctl port %d)...", talosAPIPort)
	vmVPS := bootTalosVM(t, "talos-vps", talosVmlinuz, talosInitramfs, vpsCI,
		talosAPIPort, mcastNIC("net0", mcastInternet, "52:54:00:a0:00:01"))

	t.Log("booting Talos NAT1...")
	vmNAT1 := bootTalosVM(t, "talos-nat1", talosVmlinuz, talosInitramfs, nat1CI,
		0, mcastNIC("net0", mcastLan1, "52:54:00:a0:00:02"))

	t.Log("booting Talos NAT2...")
	vmNAT2 := bootTalosVM(t, "talos-nat2", talosVmlinuz, talosInitramfs, nat2CI,
		0, mcastNIC("net0", mcastLan2, "52:54:00:a0:00:03"))

	// 7. Poll talosctl get kubespanpeerstatuses on VPS.
	// Use the talosconfig from the VPS gen output.
	talosConfigPath := filepath.Join(tmpDir, "vps", "talosconfig")
	result := pollKubeSpanStatus(t, talosctlBin, talosConfigPath, talosAPIPort, 300*time.Second)

	killAndWait(vmVPS, vmNAT1, vmNAT2, vmRouter1, vmRouter2, vmDiscovery)

	// Save artifacts.
	vmVPS.saveLogs(t, out)
	vmNAT1.saveLogs(t, out)
	vmNAT2.saveLogs(t, out)
	vmRouter1.saveLogs(t, out)
	vmRouter2.saveLogs(t, out)
	vmDiscovery.saveLogs(t, out)
	statusJSON, _ := json.MarshalIndent(result, "", "  ")
	saveArtifact(t, out, "kubespan-status.json", string(statusJSON))

	summary := map[string]interface{}{
		"topology":            "talos_double_nat",
		"talos_api_port":      talosAPIPort,
		"mcast_port_internet": mcastPortInternet,
		"mcast_port_lan1":     mcastPortLan1,
		"mcast_port_lan2":     mcastPortLan2,
		"kubespan_result":     result,
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	saveArtifact(t, out, "test-summary.json", string(summaryJSON))

	// Verify results.
	if !result.success {
		t.Errorf("KubeSpan peer discovery failed: %s", result.failReason)
	}
	for _, peer := range result.peers {
		if peer.State != "up" {
			t.Errorf("peer %s state=%s (want up), endpoint=%s", peer.Label, peer.State, peer.Endpoint)
		}
	}
	if len(result.peers) < 2 {
		t.Errorf("expected 2 KubeSpan peers, got %d", len(result.peers))
	}
}

// runCmd runs a command, logging output and failing on error.
func runCmd(t *testing.T, name string, args ...string) {
	t.Helper()
	cmd := exec.Command(name, args...)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("%s %v failed: %v", filepath.Base(name), args, err)
	}
}

// buildTalosPatch creates a JSON strategic merge patch for talosctl gen config.
func buildTalosPatch(hostname, address, gateway, endpointFilter string) string {
	iface := map[string]interface{}{
		"interface": "eth0",
		"dhcp":      false,
		"addresses": []string{address},
	}
	if gateway != "" {
		iface["routes"] = []map[string]string{
			{"network": "0.0.0.0/0", "gateway": gateway},
		}
	}

	patch := map[string]interface{}{
		"machine": map[string]interface{}{
			"network": map[string]interface{}{
				"hostname":   hostname,
				"interfaces": []interface{}{iface},
				"kubespan": map[string]interface{}{
					"filters": map[string]interface{}{
						"endpoints": []string{endpointFilter},
					},
				},
			},
			"install": map[string]interface{}{
				"disk": "",
			},
		},
		"cluster": map[string]interface{}{
			"discovery": map[string]interface{}{
				"registries": map[string]interface{}{
					"service": map[string]interface{}{
						"endpoint": "http://192.168.50.254:3000",
					},
					"kubernetes": map[string]interface{}{
						"disabled": true,
					},
				},
			},
			"network": map[string]interface{}{
				"cni": map[string]interface{}{
					"name": "none",
				},
			},
		},
	}

	data, _ := json.Marshal(patch)
	return string(data)
}

// genTalosNodeConfig generates a Talos machine config for a specific node.
// Uses talosctl gen config with shared secrets and per-node patches.
// Returns the raw machine config YAML bytes for the requested configType
// ("controlplane" or "worker").
func genTalosNodeConfig(t *testing.T, talosctlBin, secretsFile, baseDir, name, configType, patchJSON string) []byte {
	t.Helper()

	nodeDir := filepath.Join(baseDir, name)
	os.MkdirAll(nodeDir, 0o755)

	// Write patch to file for --config-patch @file.
	patchFile := filepath.Join(nodeDir, "patch.json")
	os.WriteFile(patchFile, []byte(patchJSON), 0o644)

	cmd := exec.Command(talosctlBin, "gen", "config",
		"test-kubespan", "https://192.168.50.2:6443",
		"--with-kubespan",
		"--with-secrets", secretsFile,
		"--config-patch", "@"+patchFile,
		"--output-dir", nodeDir,
	)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("talosctl gen config for %s failed: %v", name, err)
	}

	// Read the relevant config file.
	configFile := filepath.Join(nodeDir, configType+".yaml")
	data, err := os.ReadFile(configFile)
	if err != nil {
		t.Fatalf("read %s: %v", configFile, err)
	}
	t.Logf("generated %s config for %s (%d bytes)", configType, name, len(data))
	return data
}

// createCIDATA creates a nocloud CIDATA volume containing Talos machine config.
func createCIDATA(t *testing.T, tmpDir, name string, machineConfig []byte) string {
	t.Helper()

	ciDir := filepath.Join(tmpDir, "cidata-"+name)
	os.MkdirAll(ciDir, 0o755)

	metaData := fmt.Sprintf("instance-id: %s\nlocal-hostname: %s\n", name, name)
	os.WriteFile(filepath.Join(ciDir, "meta-data"), []byte(metaData), 0o644)
	os.WriteFile(filepath.Join(ciDir, "user-data"), machineConfig, 0o644)

	imgPath := filepath.Join(tmpDir, fmt.Sprintf("cidata-%s.img", name))

	runCmd(t, "dd", "if=/dev/zero", "of="+imgPath, "bs=1M", "count=4")
	runCmd(t, "mkfs.vfat", "-n", "cidata", imgPath)
	runCmd(t, "mcopy", "-i", imgPath, filepath.Join(ciDir, "meta-data"), "::")
	runCmd(t, "mcopy", "-i", imgPath, filepath.Join(ciDir, "user-data"), "::")

	t.Logf("created CIDATA for %s: %s", name, imgPath)
	return imgPath
}

// bootTalosVM starts a Talos QEMU VM with kernel+initramfs+CIDATA.
// If mgmtPort > 0, adds a user-mode NIC with port forwarding for talosctl
// access to the Talos API (port 50000).
func bootTalosVM(t *testing.T, name string, vmlinuz, initramfs, cidataPath string, mgmtPort int, netArgs []string) *vm {
	t.Helper()

	qemuBin := "qemu-system-x86_64"

	args := []string{
		"-kernel", vmlinuz,
		"-initrd", initramfs,
		"-append", "talos.platform=nocloud console=ttyS0 panic=-1",
		"-nographic",
		// No -no-reboot: Talos may reboot during initialization.
		"-m", "2048",
		"-machine", "accel=tcg",
		"-cpu", "max",
		"-display", "none",
		"-drive", fmt.Sprintf("file=%s,if=virtio,format=raw,readonly=on", cidataPath),
	}

	args = append(args, netArgs...)

	if mgmtPort > 0 {
		args = append(args,
			"-netdev", fmt.Sprintf("user,id=mgmt,hostfwd=tcp::%d-:50000", mgmtPort),
			"-device", "virtio-net-pci,netdev=mgmt,mac=52:54:00:ab:00:01",
		)
	}

	cmd := exec.Command(qemuBin, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatalf("stdout pipe: %v", err)
	}
	cmd.Stderr = cmd.Stdout

	v := &vm{
		name: name,
		cmd:  cmd,
		done: make(chan struct{}),
	}

	if err := cmd.Start(); err != nil {
		t.Fatalf("start QEMU %s: %v", name, err)
	}

	go func() {
		defer close(v.done)
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 0, 256*1024), 256*1024)
		for scanner.Scan() {
			line := scanner.Text()
			v.mu.Lock()
			v.rawLog.WriteString(line)
			v.rawLog.WriteByte('\n')
			v.mu.Unlock()
		}
		cmd.Wait()
	}()

	return v
}

// kubespanPeerResult holds the parsed status of a KubeSpan peer.
type kubespanPeerResult struct {
	Label    string `json:"label"`
	State    string `json:"state"`
	Endpoint string `json:"endpoint"`
}

// talosResource is the COSI resource envelope returned by talosctl -o json.
type talosResource struct {
	Metadata struct {
		ID string `json:"id"`
	} `json:"metadata"`
	Spec struct {
		State    string `json:"state"`
		Endpoint string `json:"endpoint"`
		Label    string `json:"label"`
	} `json:"spec"`
}

// kubespanResult holds the overall result of KubeSpan status polling.
type kubespanResult struct {
	success    bool
	failReason string
	peers      []kubespanPeerResult
	rawOutput  string
}

func (r kubespanResult) MarshalJSON() ([]byte, error) {
	return json.Marshal(struct {
		Success    bool                 `json:"success"`
		FailReason string               `json:"fail_reason,omitempty"`
		Peers      []kubespanPeerResult `json:"peers"`
		RawOutput  string               `json:"raw_output"`
	}{r.success, r.failReason, r.peers, r.rawOutput})
}

// pollKubeSpanStatus polls talosctl for KubeSpan peer statuses via the
// port-forwarded Talos API on the VPS VM.
func pollKubeSpanStatus(t *testing.T, talosctlBin, talosConfigPath string, apiPort int, timeout time.Duration) kubespanResult {
	t.Helper()

	deadline := time.Now().Add(timeout)
	var lastOutput string
	var lastErr string

	endpoint := fmt.Sprintf("127.0.0.1:%d", apiPort)

	for time.Now().Before(deadline) {
		cmd := exec.Command(talosctlBin,
			"--talosconfig", talosConfigPath,
			"--endpoints", endpoint,
			"--nodes", endpoint,
			"get", "kubespanpeerstatuses",
			"-o", "json",
		)

		out, err := cmd.CombinedOutput()
		lastOutput = string(out)
		if err != nil {
			lastErr = err.Error()
			t.Logf("talosctl poll (waiting): %s: %s", lastErr, strings.TrimSpace(lastOutput))
			time.Sleep(10 * time.Second)
			continue
		}

		peers := parsePeerStatuses(lastOutput)
		t.Logf("talosctl poll: %d peers found", len(peers))

		allUp := len(peers) >= 2
		for _, p := range peers {
			if p.State != "up" {
				allUp = false
			}
		}

		if allUp {
			return kubespanResult{
				success:   true,
				peers:     peers,
				rawOutput: lastOutput,
			}
		}

		time.Sleep(10 * time.Second)
	}

	return kubespanResult{
		success:    false,
		failReason: fmt.Sprintf("timeout after %v, last error: %s", timeout, lastErr),
		rawOutput:  lastOutput,
	}
}

// parsePeerStatuses parses the JSON Lines output of talosctl get kubespanpeerstatuses.
func parsePeerStatuses(output string) []kubespanPeerResult {
	var peers []kubespanPeerResult

	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		var res talosResource
		if err := json.Unmarshal([]byte(line), &res); err != nil {
			continue
		}

		peers = append(peers, kubespanPeerResult{
			Label:    res.Metadata.ID,
			State:    res.Spec.State,
			Endpoint: res.Spec.Endpoint,
		})
	}
	return peers
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
			"peer 1 ULA tcp",
			"peer 2 ULA tcp",
		}
	default:
		requiredProbes = []string{
			"ipv6 ULA icmp",
			"ipv4 peer eth0 icmp",
			"ipv6 ULA tcp",
			"ipv4 peer eth0 tcp",
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
