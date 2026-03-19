// Binary worker is the PID-1 init process for the Alpine-based k8s worker VM.
// Starts Nebula (overlay mesh), containerd, and kubelet to join a Talos cluster
// and prove pod-to-pod connectivity across a double NAT topology.
package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"time"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vms/initlib"
)

func main() {
	params := initlib.Init()

	linkIP := params["link_ip"]
	defaultGW := params["default_gw"]
	nebulaIP := params["nebula_ip"]
	if linkIP == "" || defaultGW == "" || nebulaIP == "" {
		log.Fatalf("missing params: link_ip=%s default_gw=%s nebula_ip=%s", linkIP, defaultGW, nebulaIP)
	}

	log.Printf("worker mode, link_ip=%s, default_gw=%s, nebula_ip=%s", linkIP, defaultGW, nebulaIP)

	// Load kernel modules needed by containerd and kubelet.
	initlib.Modprobe("virtio_blk", "overlay", "br_netfilter", "tun", "virtio_net", "veth")

	// Enable IP forwarding (required for pod networking).
	for _, path := range []string{
		"/proc/sys/net/ipv4/ip_forward",
		"/proc/sys/net/bridge/bridge-nf-call-iptables",
	} {
		os.WriteFile(path, []byte("1"), 0o644)
	}

	// Wait for virtio devices to settle after modprobe.
	time.Sleep(500 * time.Millisecond)

	// Configure mesh NIC (eth0).
	initlib.WaitForInterface("eth0")
	initlib.MustRun("ip", "link", "set", "lo", "up")
	initlib.MustRun("ip", "link", "set", "eth0", "up")
	initlib.MustRun("ip", "addr", "add", linkIP+"/24", "dev", "eth0")
	initlib.MustRun("ip", "route", "add", "default", "via", defaultGW)
	log.Printf("eth0 configured: %s, gw=%s", linkIP, defaultGW)

	// Configure management NIC.
	initlib.ConfigureMgmtNIC(false)

	// Mount CIDATA and extract config files.
	mountCIDATA()

	// Start Nebula.
	startNebula()
	waitForInterface("nebula1", 60*time.Second)
	log.Printf("nebula1 interface is up")

	// Add static routes for pod CIDRs of other workers through Nebula.
	// These would normally be handled by a CNI (Cilium), but for the demo
	// we use static routes + bridge CNI.
	// Routes are set up after kubelet starts and assigns pod CIDRs.

	// Set up CNI directories.
	os.MkdirAll("/opt/cni/bin", 0o755)
	os.MkdirAll("/etc/cni/net.d", 0o755)
	setupCNI(nebulaIP)

	// Start containerd.
	startContainerd()
	time.Sleep(2 * time.Second) // Give containerd time to initialize.
	log.Printf("containerd started")

	// Create glibc compat symlinks for dynamically-linked binaries (kubelet, containerd).
	// Alpine uses musl, but k8s binaries are built with CGO against glibc.
	setupGlibcCompat()

	// Start kubelet.
	startKubelet(nebulaIP)

	// Start probe server for test host connectivity verification.
	initlib.StartProbeServer(fmt.Sprintf(":%d", initlib.ProbeServerPort))

	log.Printf("worker running: nebula=%s, kubelet starting", nebulaIP)
	select {}
}

// setupGlibcCompat creates symlinks so dynamically-linked glibc binaries
// (kubelet, containerd) can run on Alpine's musl libc.
func setupGlibcCompat() {
	os.MkdirAll("/lib64", 0o755)
	// The dynamic linker path that glibc binaries expect.
	musl := "/lib/ld-musl-x86_64.so.1"
	if _, err := os.Stat(musl); err != nil {
		log.Printf("WARNING: musl not found at %s, glibc compat unavailable", musl)
		return
	}
	os.Symlink(musl, "/lib64/ld-linux-x86-64.so.2")
	os.Symlink(musl, "/lib/ld-linux-x86-64.so.2")
	log.Printf("glibc compat symlinks created")
}

// mountCIDATA mounts the CIDATA virtio drive and extracts Nebula + k8s configs.
func mountCIDATA() {
	os.MkdirAll("/mnt/cidata", 0o755)
	os.MkdirAll("/etc/nebula", 0o755)
	os.MkdirAll("/etc/kubernetes/pki", 0o755)

	initlib.MustRun("mount", "-t", "vfat", "-o", "ro", "/dev/vda", "/mnt/cidata")

	// Nebula configs.
	copyFile("/mnt/cidata/nebula-ca.crt", "/etc/nebula/ca.crt")
	copyFile("/mnt/cidata/nebula-host.crt", "/etc/nebula/host.crt")
	copyFile("/mnt/cidata/nebula-host.key", "/etc/nebula/host.key")
	copyFile("/mnt/cidata/nebula-config.yaml", "/etc/nebula/config.yaml")

	// Kubernetes configs.
	copyFile("/mnt/cidata/ca.crt", "/etc/kubernetes/pki/ca.crt")
	copyFile("/mnt/cidata/bootstrap-kubelet.conf", "/etc/kubernetes/bootstrap-kubelet.conf")

	log.Printf("CIDATA mounted and configs extracted")
}

func copyFile(src, dst string) {
	data, err := os.ReadFile(src)
	if err != nil {
		log.Fatalf("read %s: %v", src, err)
	}
	if err := os.WriteFile(dst, data, 0o600); err != nil {
		log.Fatalf("write %s: %v", dst, err)
	}
}

// startNebula starts the Nebula daemon in the background.
func startNebula() {
	cmd := exec.Command("/usr/bin/nebula", "-config", "/etc/nebula/config.yaml")
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		log.Fatalf("start nebula: %v", err)
	}
	log.Printf("nebula started (pid=%d)", cmd.Process.Pid)
}

func waitForInterface(name string, timeout time.Duration) {
	if !initlib.HasInterface(name, timeout) {
		log.Fatalf("%s not found after %v", name, timeout)
	}
}

// setupCNI writes the bridge CNI config and symlinks CNI binaries.
func setupCNI(nebulaIP string) {
	// Bridge CNI config — assigns pod IPs from a /24 subnet.
	cniConf := fmt.Sprintf(`{
  "cniVersion": "1.0.0",
  "name": "bridge",
  "plugins": [
    {
      "type": "bridge",
      "bridge": "cni0",
      "isGateway": true,
      "ipMasq": true,
      "ipam": {
        "type": "host-local",
        "subnet": "10.244.2.0/24",
        "routes": [{"dst": "0.0.0.0/0"}]
      }
    },
    {
      "type": "loopback"
    }
  ]
}`)
	if err := os.WriteFile("/etc/cni/net.d/10-bridge.conflist", []byte(cniConf), 0o644); err != nil {
		log.Fatalf("write CNI config: %v", err)
	}
	log.Printf("CNI bridge config written (subnet=10.244.2.0/24)")
}

// startContainerd starts containerd in the background.
func startContainerd() {
	os.MkdirAll("/var/lib/containerd", 0o755)
	os.MkdirAll("/run/containerd", 0o755)

	// Write a minimal containerd config.
	config := `version = 3
[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc]
  runtime_type = "io.containerd.runc.v2"
[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc.options]
  SystemdCgroup = false
[plugins."io.containerd.cri.v1.runtime".cni]
  bin_dir = "/opt/cni/bin"
  conf_dir = "/etc/cni/net.d"
`
	os.MkdirAll("/etc/containerd", 0o755)
	os.WriteFile("/etc/containerd/config.toml", []byte(config), 0o644)

	cmd := exec.Command("/usr/bin/containerd", "--config", "/etc/containerd/config.toml")
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		log.Fatalf("start containerd: %v", err)
	}
	log.Printf("containerd started (pid=%d)", cmd.Process.Pid)
}

// startKubelet starts kubelet in the background.
func startKubelet(nodeIP string) {
	os.MkdirAll("/var/lib/kubelet", 0o755)
	os.MkdirAll("/var/log", 0o755)

	// Write kubelet config.
	kubeletConfig := fmt.Sprintf(`apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
authentication:
  anonymous:
    enabled: false
  webhook:
    enabled: true
authorization:
  mode: Webhook
clusterDNS:
  - "10.96.0.10"
clusterDomain: "cluster.local"
failSwapOn: false
containerRuntimeEndpoint: "unix:///run/containerd/containerd.sock"
`)
	os.WriteFile("/var/lib/kubelet/kubelet-config.yaml", []byte(kubeletConfig), 0o644)

	cmd := exec.Command("/usr/bin/kubelet",
		"--bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf",
		"--kubeconfig=/var/lib/kubelet/kubeconfig",
		"--config=/var/lib/kubelet/kubelet-config.yaml",
		"--node-ip="+nodeIP,
		"--register-node=true",
		"--v=2",
	)
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		log.Fatalf("start kubelet: %v", err)
	}
	log.Printf("kubelet started (pid=%d, node-ip=%s)", cmd.Process.Pid, nodeIP)
}
