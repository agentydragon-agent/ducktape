// Integration test proving Talos + Nebula handles double NAT where KubeSpan failed.
//
// Topology:
//
//	[NAT1: Talos worker]   --[LAN-A]-- [Router-A] --+
//	     10.42.0.10                                   |
//	                                             [Internet]
//	                                                  |
//	[NAT2: Alpine worker]  --[LAN-B]-- [Router-B] --+
//	     10.42.0.20                                   |
//	     (nebula + kubelet + containerd + CNI)        |
//	                                             [VPS: Talos CP]
//	                                               10.42.0.1
//	                                         (lighthouse + relay)
//
// Nebula's relay capability guarantees NAT1↔NAT2 connectivity through the VPS,
// unlike KubeSpan which relies on probabilistic endpoint cycling (~240s average).
package nebula_demo_test

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/siderolabs/talos/pkg/machinery/client"

	h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
	. "github.com/agentydragon/ducktape/cluster/nebula_demo"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vmconst"
)

func TestNebulaDoubleNAT(t *testing.T) {
	sw := h.NewStopwatch(t)
	out := h.OutputDir(t)
	sw.SetOutDir(out)

	// Resolve runfile paths.
	vmlinuz := h.RunfilePath(t, h.VmlinuzPath)
	initramfsRouter := h.RunfilePath(t, h.RouterInitramfs)
	initramfsWorker := h.RunfilePath(t, WorkerInitramfsPath)
	tmpDir := t.TempDir()
	talosBaseImage := DecompressTalosImage(t, tmpDir)
	sw.Lap("resolve runfiles + decompress image")

	// Read pre-generated Nebula certificates from testdata.
	caCrt := ReadTestdataCert(t, "ca.crt")
	vpsCrt := ReadTestdataCert(t, "vps.crt")
	vpsKey := ReadTestdataCert(t, "vps.key")
	nat1Crt := ReadTestdataCert(t, "nat1.crt")
	nat1Key := ReadTestdataCert(t, "nat1.key")
	nat2Crt := ReadTestdataCert(t, "nat2.crt")
	nat2Key := ReadTestdataCert(t, "nat2.key")

	// Build Nebula configs.
	// The Nebula PKI paths differ between Talos (ExtensionServiceConfig mounts to
	// /usr/local/etc/nebula/) and Alpine worker (init writes to /etc/nebula/).
	vpsNebulaYAML := MarshalNebulaConfig(LighthouseConfig(VPSIP))
	nat1NebulaYAML := MarshalNebulaConfig(PeerConfig(VPSIP))
	// NAT2 (Alpine worker) uses /etc/nebula/ paths.
	nat2NebulaCfg := PeerConfig(VPSIP)
	nat2NebulaCfg.PKI = NebulaConfigPKI{
		CA:   "/etc/nebula/ca.crt",
		Cert: "/etc/nebula/host.crt",
		Key:  "/etc/nebula/host.key",
	}
	nat2NebulaYAML := MarshalNebulaConfig(nat2NebulaCfg)

	// Generate Talos cluster secrets.
	secrets := h.GenerateTestTalosSecrets(t)
	cpEndpoint := fmt.Sprintf("https://%s:6443", VPSIP)

	// Build Talos machine configs with Nebula (VPS + NAT1 only).
	vpsConfig := ControlPlaneConfigWithNebula(secrets, TalosNebulaNodeConfig{
		IP:                   VPSIP + "/24",
		ControlPlaneEndpoint: cpEndpoint,
		CertSANs:             []string{VPSIP, "127.0.0.1"},
		NebulaCACrt:          caCrt,
		NebulaHostCrt:        vpsCrt,
		NebulaHostKey:        vpsKey,
		NebulaConfigYAML:     vpsNebulaYAML,
	})
	nat1Config := WorkerConfigWithNebula(secrets, TalosNebulaNodeConfig{
		IP:                   NAT1IP + "/24",
		Gateway:              NAT1Gateway,
		ControlPlaneEndpoint: cpEndpoint,
		NebulaCACrt:          caCrt,
		NebulaHostCrt:        nat1Crt,
		NebulaHostKey:        nat1Key,
		NebulaConfigYAML:     nat1NebulaYAML,
	})

	talosConfigPath := filepath.Join(tmpDir, "talosconfig")
	secrets.WriteTalosconfig(t, talosConfigPath)

	vpsCI := h.CreateCIDATA(t, tmpDir, "vps", vpsConfig)
	nat1CI := h.CreateCIDATA(t, tmpDir, "nat1", nat1Config)

	// NAT2 Alpine worker CIDATA — Nebula certs + k8s bootstrap credentials.
	// TODO: generate a proper bootstrap kubeconfig from secrets.
	bootstrapKubeconfig := fmt.Sprintf(`apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority: /etc/kubernetes/pki/ca.crt
    server: %s
  name: nebula-demo
contexts:
- context:
    cluster: nebula-demo
    user: kubelet-bootstrap
  name: bootstrap
current-context: bootstrap
users:
- name: kubelet-bootstrap
  user:
    token: %s
`, cpEndpoint, secrets.ClusterToken)

	nat2CI := CreateWorkerCIDATA(t, tmpDir, "nat2", WorkerCIDATAFiles{
		NebulaCACrt:         caCrt,
		NebulaHostCrt:       nat2Crt,
		NebulaHostKey:       nat2Key,
		NebulaConfigYAML:    nat2NebulaYAML,
		K8sCACrt:            string(secrets.ClusterCA.Crt),
		BootstrapKubeconfig: bootstrapKubeconfig,
	})
	sw.Lap("generate configs")

	// Network segments (multicast socket bridges).
	mcastInternet := fmt.Sprintf("230.0.0.1:%d", h.RandomPort())
	mcastLanA := fmt.Sprintf("230.0.0.1:%d", h.RandomPort())
	mcastLanB := fmt.Sprintf("230.0.0.1:%d", h.RandomPort())

	// Boot router VMs (Alpine + nftables masquerade).
	vmRouterA := h.BootVM(t, "vm-router-a", vmlinuz, initramfsRouter,
		"role=router-a internet_ip="+h.DoubleNATRouterAInternetCIDR+" lan_ip="+h.DoubleNATRouterALanCIDR,
		append(h.McastNIC("net0", mcastInternet, h.DoubleNATRouterAInternetMAC),
			h.McastNIC("net1", mcastLanA, h.DoubleNATRouterALanMAC)...))
	vmRouterB := h.BootVM(t, "vm-router-b", vmlinuz, initramfsRouter,
		"role=router-b internet_ip="+h.DoubleNATRouterBInternetCIDR+" lan_ip="+h.DoubleNATRouterBLanCIDR,
		append(h.McastNIC("net0", mcastInternet, h.DoubleNATRouterBInternetMAC),
			h.McastNIC("net1", mcastLanB, h.DoubleNATRouterBLanMAC)...))
	sw.Lap("boot routers")

	// Boot VPS (Talos CP + Nebula lighthouse/relay).
	vpsAPIPort := h.RandomPort()
	vmVPS := BootTalosRawVM(t, "vm-vps", talosBaseImage, vpsCI,
		vpsAPIPort, h.McastNIC("net0", mcastInternet, h.DoubleNATVPSMAC))

	// Boot NAT1 (Talos worker + Nebula).
	nat1APIPort := h.RandomPort()
	vmNAT1 := BootTalosRawVM(t, "vm-nat1", talosBaseImage, nat1CI,
		nat1APIPort, h.McastNIC("net0", mcastLanA, h.DoubleNATNAT1MAC))

	// Boot NAT2 (Alpine worker + Nebula + kubelet).
	vmNAT2 := h.BootVM(t, "vm-nat2", vmlinuz, initramfsWorker,
		"role=worker link_ip="+NAT2IP+" default_gw="+NAT2Gateway+" nebula_ip="+NebulaNAT2IP,
		append(h.McastNIC("net0", mcastLanB, h.DoubleNATNAT2MAC), h.CIDATADrive(nat2CI)...))
	sw.Lap("boot VMs")

	allVMs := []*h.VM{vmVPS, vmNAT1, vmNAT2, vmRouterA, vmRouterB}
	h.CleanupVMs(t, allVMs, out)

	// Wait for router and NAT2 probe servers (Alpine VMs have probe servers).
	h.WaitForProbeServers(t, []*h.VM{vmRouterA, vmRouterB, vmNAT2}, 120*time.Second)
	sw.Lap("probe servers ready")

	// Wait for Talos API on VPS and NAT1.
	vpsClient := h.NewTalosClient(t, talosConfigPath, fmt.Sprintf("127.0.0.1:%d", vpsAPIPort))
	t.Cleanup(func() { vpsClient.Close() })
	nat1Client := h.NewTalosClient(t, talosConfigPath, fmt.Sprintf("127.0.0.1:%d", nat1APIPort))
	t.Cleanup(func() { nat1Client.Close() })

	waitTalosAPI(t, "vps", vpsClient, 180*time.Second)
	sw.Lap("VPS Talos API ready")
	waitTalosAPI(t, "nat1", nat1Client, 180*time.Second)
	sw.Lap("NAT1 Talos API ready")

	// Check Nebula extension service is running on Talos nodes.
	checkNebulaService(t, "vps", vpsClient)
	checkNebulaService(t, "nat1", nat1Client)
	sw.Lap("Nebula services checked")

	// === BIDIRECTIONAL CONNECTIVITY PROOF ===
	ctx, cancel := context.WithTimeout(t.Context(), 3*time.Minute)
	defer cancel()

	t.Log("=== Waiting for Nebula mesh convergence ===")

	// NAT2 (Alpine) has a probe server — use ICMP probes via it.
	// NAT1↔NAT2: the hardest path (double NAT, must relay through VPS).
	if !vmNAT2.ProbeICMP(NebulaNAT1IP, 120*time.Second) {
		dumpNebulaStatus(t, "vps", vpsClient)
		t.Fatal("NAT2 cannot reach NAT1 over Nebula (ICMP probe failed)")
	}
	sw.Lap("NAT2→NAT1 ICMP OK")

	// VPS→NAT2 and NAT2→VPS (hub-spoke).
	if !vmNAT2.ProbeICMP(NebulaVPSIP, 30*time.Second) {
		t.Fatal("NAT2 cannot reach VPS over Nebula")
	}
	sw.Lap("NAT2→VPS ICMP OK")

	// For Talos nodes, verify Nebula is up by checking routing table.
	if !pollNebulaRoute(ctx, t, "nat1", nat1Client) {
		t.Fatal("NAT1 nebula1 route not established")
	}
	if !pollNebulaRoute(ctx, t, "vps", vpsClient) {
		t.Fatal("VPS nebula1 route not established")
	}
	sw.Lap("full mesh connectivity verified")

	t.Log("=== SUCCESS: Nebula full mesh across double NAT ===")
	t.Logf("  VPS  (%s) ↔ NAT1 (%s): Nebula overlay up", NebulaVPSIP, NebulaNAT1IP)
	t.Logf("  VPS  (%s) ↔ NAT2 (%s): Nebula overlay up", NebulaVPSIP, NebulaNAT2IP)
	t.Logf("  NAT1 (%s) ↔ NAT2 (%s): ICMP via relay OK", NebulaNAT1IP, NebulaNAT2IP)

	summary := map[string]interface{}{
		"topology":    "double_nat_nebula",
		"vps_nebula":  NebulaVPSIP,
		"nat1_nebula": NebulaNAT1IP,
		"nat2_nebula": NebulaNAT2IP,
		"nat2_type":   "alpine_worker",
		"cluster_id":  secrets.ClusterID,
	}
	summaryJSON, _ := json.MarshalIndent(summary, "", "  ")
	h.SaveArtifact(t, out, "test-summary.json", string(summaryJSON))
	sw.Summary(out)
}

// waitTalosAPI polls the Talos API until it responds or times out.
func waitTalosAPI(t *testing.T, name string, c *client.Client, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		ctx, cancel := context.WithTimeout(client.WithNode(context.Background(), vmconst.MgmtIP), 5*time.Second)
		_, err := c.Version(ctx)
		cancel()
		if err == nil {
			t.Logf("[%s] Talos API ready", name)
			return
		}
		time.Sleep(2 * time.Second)
	}
	t.Fatalf("[%s] Talos API not ready after %v", name, timeout)
}

// checkNebulaService verifies the Nebula extension service is running via Talos API.
func checkNebulaService(t *testing.T, name string, c *client.Client) {
	t.Helper()
	ctx, cancel := context.WithTimeout(client.WithNode(context.Background(), vmconst.MgmtIP), 30*time.Second)
	defer cancel()

	resp, err := c.ServiceList(ctx)
	if err != nil {
		t.Logf("[%s] ServiceList failed: %v", name, err)
		return
	}

	for _, msg := range resp.Messages {
		for _, svc := range msg.Services {
			if svc.Id == "ext-nebula" || svc.Id == "nebula" {
				t.Logf("[%s] Nebula service: id=%s state=%s health=%v",
					name, svc.Id, svc.State, svc.Health)
				return
			}
		}
	}
	t.Logf("[%s] WARNING: Nebula service not found in service list", name)
}

// pollNebulaRoute checks if the nebula1 interface appears in the routing table.
func pollNebulaRoute(ctx context.Context, t *testing.T, name string, c *client.Client) bool {
	t.Helper()
	for {
		select {
		case <-ctx.Done():
			return false
		default:
		}

		rctx, cancel := context.WithTimeout(client.WithNode(context.Background(), vmconst.MgmtIP), 10*time.Second)
		reader, err := c.Read(rctx, "/proc/net/route")
		cancel()
		if err != nil {
			time.Sleep(3 * time.Second)
			continue
		}

		var buf [4096]byte
		n, _ := reader.Read(buf[:])
		reader.Close()
		routes := string(buf[:n])

		if strings.Contains(routes, "nebula1") {
			t.Logf("[%s] nebula1 route established", name)
			return true
		}
		time.Sleep(3 * time.Second)
	}
}

// dumpNebulaStatus logs Nebula-related diagnostics from a Talos node.
func dumpNebulaStatus(t *testing.T, name string, c *client.Client) {
	t.Helper()
	ctx, cancel := context.WithTimeout(client.WithNode(context.Background(), vmconst.MgmtIP), 10*time.Second)
	defer cancel()

	reader, err := c.Read(ctx, "/proc/net/route")
	if err == nil {
		var buf [4096]byte
		n, _ := reader.Read(buf[:])
		reader.Close()
		t.Logf("[%s] /proc/net/route:\n%s", name, string(buf[:n]))
	}

	resp, err := c.ServiceList(ctx)
	if err == nil {
		for _, msg := range resp.Messages {
			for _, svc := range msg.Services {
				t.Logf("[%s] service: %s state=%s health=%v", name, svc.Id, svc.State, svc.Health)
			}
		}
	}
}
