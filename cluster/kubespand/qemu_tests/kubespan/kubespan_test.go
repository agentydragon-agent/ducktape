package kubespan_test

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"gopkg.in/yaml.v3"

	h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
)

func TestFlat(t *testing.T) {
	t.Parallel()
	runTopology(t, "flat")
}

func TestCrossSubnet(t *testing.T) {
	t.Parallel()
	runTopology(t, "cross_subnet")
}

func TestDiscoveryOnly(t *testing.T) {
	t.Parallel()
	runTopology(t, "discovery_only")
}

// TestTrustdCSRFlow verifies that kubespand can obtain TLS certificates from
// a Talos controlplane node's trustd service via the standard CSR flow.
// Topology: discovery VM + Talos CP VM + kubespand VM on 192.168.50.0/24.
// The kubespand VM runs apid on port 50000 — if we can connect via Talos API,
// that proves the trustd CSR flow produced secrets.API successfully.
func TestTrustdCSRFlow(t *testing.T) {
	t.Parallel()
	sw := h.NewStopwatch(t)

	// Resolve runfiles.
	talosBaseImage := h.RunfilePath(t, h.TalosNocloudImagePath)
	vmlinuz := h.RunfilePath(t, h.VmlinuzPath)
	initramfsDisc := h.RunfilePath(t, h.DiscoveryInitramfs)
	initramfsTrustd := h.RunfilePath(t, h.TrustdInitramfs)
	sw.Lap("resolve runfiles")

	out := h.OutputDir(t)
	tmpDir := t.TempDir()

	// Parse Talos CP config to extract credentials for kubespand.
	vpsConfigData := h.ReadRunfile(t, h.TalosVPSConfig)
	var cfg talosConfig
	if err := yaml.Unmarshal(vpsConfigData, &cfg); err != nil {
		t.Fatalf("parse talos config: %v", err)
	}
	sw.Lap("parse talos config")

	// Create CIDATA for the Talos CP VM.
	vpsCI := h.CreateCIDATA(t, tmpDir, "vps", vpsConfigData)
	sw.Lap("create CIDATA")

	// All VMs on the same flat L2 segment.
	mcastPort := h.RandomPort()
	mcastAddr := fmt.Sprintf("230.0.0.1:%d", mcastPort)

	vmDisc := h.BootVM(t, "trustd-disc", vmlinuz, initramfsDisc,
		"mode=discovery role=discovery discovery_ip=192.168.50.254/24",
		h.McastNIC("net0", mcastAddr, "52:54:00:ff:00:01")...)
	sw.Lap("boot discovery VM")

	// Talos CP VM — provides trustd on port 50001.
	talosAPIPort := h.RandomPort()
	vmCP := h.BootTalosVM(t, "trustd-cp", talosBaseImage, vpsCI,
		talosAPIPort, h.McastNIC("net0", mcastAddr, "52:54:00:a0:00:01"))
	sw.Lap("boot Talos CP VM")

	// kubespand VM with CA cert + token for the trustd CSR flow.
	// mgmt NIC forwards apid port 50000 so the test can observe from outside.
	kubespandAPIPort := h.RandomPort()
	kernelArgs := fmt.Sprintf(
		"cluster_id=%s shared_secret=%s discovery=192.168.50.254:3000 ca_crt=%s token=%s cluster_endpoint=https://192.168.50.2:6443",
		cfg.Cluster.ID, cfg.Cluster.Secret, cfg.Machine.CA.Crt, cfg.Machine.Token,
	)
	mgmtNIC := []string{
		"-netdev", fmt.Sprintf("user,id=mgmt,hostfwd=tcp::%d-:50000", kubespandAPIPort),
		"-device", "virtio-net-pci,netdev=mgmt,mac=52:54:00:ab:00:01",
	}
	vmKubespand := h.BootVM(t, "trustd-kubespand", vmlinuz, initramfsTrustd, kernelArgs,
		append(h.McastNIC("net0", mcastAddr, "52:54:00:b0:00:01"), mgmtNIC...)...)
	sw.Lap("boot kubespand VM")

	allVMs := []*h.VM{vmCP, vmKubespand, vmDisc}
	h.CleanupVMs(t, allVMs, out)

	// Wait for discovery service.
	h.RequireEvent(t, vmDisc, h.EventDone, 30*time.Second)
	sw.Lap("discovery VM ready")

	// Wait for Talos CP API (boot takes ~60-120s on TCG).
	talosClient := h.NewTalosClient(t, h.RunfilePath(t, h.TalosConfig), fmt.Sprintf("127.0.0.1:%d", talosAPIPort))
	defer talosClient.Close()
	h.WaitForTalosAPI(t, talosClient, "192.168.50.2", 180*time.Second)
	sw.Lap("Talos CP API ready")

	// Connect to kubespand's apid — success proves the full chain:
	// kubespand → OSRootController → APICertSANsController → APIController
	// → trustd CSR → secrets.API → apid serves mTLS on :50000.
	kubespandClient := h.NewTalosClient(t, h.RunfilePath(t, h.TalosConfig), fmt.Sprintf("127.0.0.1:%d", kubespandAPIPort))
	defer kubespandClient.Close()
	h.WaitForTalosAPI(t, kubespandClient, "192.168.50.1", 300*time.Second)
	sw.Lap("kubespand apid ready (trustd CSR flow succeeded)")

	sw.Summary(out)
}

// talosConfig holds the subset of Talos machine config needed by TestTrustdCSRFlow.
type talosConfig struct {
	Machine struct {
		Token string `yaml:"token"`
		CA    struct {
			Crt string `yaml:"crt"`
		} `yaml:"ca"`
	} `yaml:"machine"`
	Cluster struct {
		ID     string `yaml:"id"`
		Secret string `yaml:"secret"`
	} `yaml:"cluster"`
}

func runTopology(t *testing.T, topology string) {
	sw := h.NewStopwatch(t)

	vmlinuz := h.RunfilePath(t, h.VmlinuzPath)
	initramfs := h.RunfilePath(t, h.KubespanInitramfs)
	initramfsDisc := h.RunfilePath(t, h.DiscoveryInitramfs)
	out := h.OutputDir(t)
	sw.Lap("resolve runfiles")

	clusterID := h.RandomBase64(32)
	sharedSecret := h.RandomBase64(32)
	mcastPort := h.RandomPort()

	var discIP string
	switch topology {
	case "flat", "discovery_only":
		discIP = "192.168.50.254"
	case "cross_subnet":
		discIP = "10.1.0.254"
	}
	discAddr := fmt.Sprintf("%s:3000", discIP)

	mcastAddr := fmt.Sprintf("230.0.0.1:%d", mcastPort)

	kernelBase := fmt.Sprintf("mode=kubespan cluster_id=%s shared_secret=%s discovery=%s topology=%s",
		clusterID, sharedSecret, discAddr, topology)

	vmDisc := h.BootVM(t, "vm-disc", vmlinuz, initramfsDisc,
		fmt.Sprintf("mode=discovery role=discovery discovery_ip=%s/24 topology=%s", discIP, topology),
		h.McastNIC("net0", mcastAddr, "52:54:00:ff:00:01")...)
	sw.Lap("boot discovery VM")

	vmB := h.BootVM(t, "vm-b", vmlinuz, initramfs, kernelBase+" role=b",
		h.McastNIC("net0", mcastAddr, "52:54:00:b0:00:01")...)
	sw.Lap("boot VM-B")

	vmA := h.BootVM(t, "vm-a", vmlinuz, initramfs, kernelBase+" role=a",
		h.McastNIC("net0", mcastAddr, "52:54:00:a0:00:01")...)
	sw.Lap("boot VM-A")

	allVMs := []*h.VM{vmA, vmB, vmDisc}
	h.CleanupVMs(t, allVMs, out)

	h.RequireEvent(t, vmDisc, h.EventDone, 30*time.Second)
	sw.Lap("discovery VM ready")

	h.WaitVMDone(t, vmA, 300*time.Second)
	sw.Lap("VM-A done (peer discovery + probes)")

	summary := map[string]interface{}{
		"topology":       topology,
		"cluster_id":     clusterID,
		"mcast_port":     mcastPort,
		"vm_a_events":    vmA.GetEvents(),
		"vm_b_events":    vmB.GetEvents(),
		"vm_disc_events": vmDisc.GetEvents(),
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	h.SaveArtifact(t, out, "test-summary.json", string(summaryJSON))

	h.AssertProbes(t, vmA.GetEvents(), topology)
	sw.Lap("assertions")

	sw.Summary(out)
}
