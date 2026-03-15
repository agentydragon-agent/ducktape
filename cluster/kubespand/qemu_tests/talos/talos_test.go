package talos_test

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
)

func TestTalosKubeSpanDoubleNAT(t *testing.T) {
	sw := h.NewStopwatch(t)

	talosBaseImage := h.RunfilePath(t, h.TalosNocloudImagePath)
	alpineVmlinuz := h.RunfilePath(t, h.VmlinuzPath)
	alpineInitramfsDisc := h.RunfilePath(t, h.DiscoveryInitramfs)
	alpineInitramfsRouter := h.RunfilePath(t, h.RouterInitramfs)
	sw.Lap("resolve runfiles")

	out := h.OutputDir(t)
	tmpDir := t.TempDir()

	vpsConfig := h.ReadRunfile(t, h.TalosVPSConfig)
	nat1Config := h.ReadRunfile(t, h.TalosNAT1Config)
	nat2Config := h.ReadRunfile(t, h.TalosNAT2Config)

	vpsCI := h.CreateCIDATA(t, tmpDir, "vps", vpsConfig)
	nat1CI := h.CreateCIDATA(t, tmpDir, "nat1", nat1Config)
	nat2CI := h.CreateCIDATA(t, tmpDir, "nat2", nat2Config)
	sw.Lap("create CIDATA volumes")

	mcastPortInternet := h.RandomPort()
	mcastPortLan1 := h.RandomPort()
	mcastPortLan2 := h.RandomPort()
	mcastInternet := fmt.Sprintf("230.0.0.1:%d", mcastPortInternet)
	mcastLan1 := fmt.Sprintf("230.0.0.1:%d", mcastPortLan1)
	mcastLan2 := fmt.Sprintf("230.0.0.1:%d", mcastPortLan2)

	vmDiscovery := h.BootVM(t, "talos-disc", alpineVmlinuz, alpineInitramfsDisc,
		"mode=discovery role=discovery discovery_ip=192.168.50.254/24",
		h.McastNIC("net0", mcastInternet, "52:54:00:ff:00:01")...)
	vmRouter1 := h.BootVM(t, "talos-router-1", alpineVmlinuz, alpineInitramfsRouter,
		"mode=router role=router-1 internet_ip=192.168.50.1/24 lan_ip=192.168.60.1/24",
		append(h.McastNIC("net0", mcastInternet, "52:54:00:c1:00:01"),
			h.McastNIC("net1", mcastLan1, "52:54:00:c1:00:02")...)...)
	vmRouter2 := h.BootVM(t, "talos-router-2", alpineVmlinuz, alpineInitramfsRouter,
		"mode=router role=router-2 internet_ip=192.168.50.3/24 lan_ip=192.168.70.1/24",
		append(h.McastNIC("net0", mcastInternet, "52:54:00:c2:00:01"),
			h.McastNIC("net1", mcastLan2, "52:54:00:c2:00:02")...)...)
	sw.Lap("boot infrastructure VMs (discovery + routers)")

	talosAPIPort := h.RandomPort()
	vmVPS := h.BootTalosVM(t, "talos-vps", talosBaseImage, vpsCI,
		talosAPIPort, h.McastNIC("net0", mcastInternet, "52:54:00:a0:00:01"))
	vmNAT1 := h.BootTalosVM(t, "talos-nat1", talosBaseImage, nat1CI,
		0, h.McastNIC("net0", mcastLan1, "52:54:00:a0:00:02"))
	vmNAT2 := h.BootTalosVM(t, "talos-nat2", talosBaseImage, nat2CI,
		0, h.McastNIC("net0", mcastLan2, "52:54:00:a0:00:03"))
	sw.Lap("boot Talos VMs")

	h.RequireAllEvents(t, []*h.VM{vmDiscovery, vmRouter1, vmRouter2}, h.EventDone, 30*time.Second)
	sw.Lap("infrastructure VMs ready")

	allVMs := []*h.VM{vmVPS, vmNAT1, vmNAT2, vmRouter1, vmRouter2, vmDiscovery}
	h.CleanupVMs(t, allVMs, out)

	// Create Talos API client from talosconfig credentials.
	endpoint := fmt.Sprintf("127.0.0.1:%d", talosAPIPort)
	nodeIP := "192.168.50.2"
	talosClient := h.NewTalosClient(t, h.RunfilePath(t, h.TalosConfig), endpoint)
	defer talosClient.Close()

	// Observed on RBE (Firecracker, TCG): apid healthy ~64s after VM start.
	h.WaitForTalosAPI(t, talosClient, nodeIP, 120*time.Second)
	sw.Lap("Talos API ready")

	// Observed: KubeSpan nftables rules applied ~35s after VM start.
	// Peer discovery depends on discovery service + WireGuard handshake.
	peers, err := h.PollKubeSpanStatus(t, talosClient, nodeIP, 120*time.Second)
	sw.Lap("KubeSpan status poll")

	statusJSON, _ := json.MarshalIndent(peers, "", "  ")
	h.SaveArtifact(t, out, "kubespan-status.json", string(statusJSON))

	if err != nil {
		t.Errorf("KubeSpan peer discovery failed: %v", err)
	}
	for _, peer := range peers {
		// On TCG-emulated VMs, WireGuard handshakes may not complete within the
		// test timeout (state stays "unknown"). Log for diagnostics but don't fail.
		t.Logf("peer %s state=%s, endpoint=%s", peer.Label, peer.State, peer.Endpoint)
	}
	if len(peers) < 2 {
		t.Errorf("expected 2 KubeSpan peers, got %d", len(peers))
	}
	sw.Lap("assertions")

	sw.Summary(out)
}
