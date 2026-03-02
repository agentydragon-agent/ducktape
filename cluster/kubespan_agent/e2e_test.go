// Integration tests for kubespand: verifies peer discovery and network
// connectivity against a real Talos container and local discovery service.
// Requires Docker, ~2–3 minutes.
package main

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	docker "github.com/fsouza/go-dockerclient"
	"gopkg.in/yaml.v3"

	"github.com/agentydragon/ducktape/cluster/kubespan_agent/agentconfig"
)

const (
	discoveryRepoTag     = "ghcr.io/siderolabs/discovery-service:latest"
	talosRepoTag         = "ghcr.io/siderolabs/talos:v1.9.5"
	kubespandRepoTag     = "kubespand:latest"
	kubespandTestRepoTag = "kubespand-test:latest"
	networkPrefix        = "kubespan-e2e"
)

func TestKubeSpanDiscovery(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	// 90s for test logic (images are pre-cached by Bazel). Leaves buffer
	// before the 300s Bazel test timeout so t.Cleanup runs on failure.
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	client, err := docker.NewClientFromEnv()
	if err != nil {
		t.Fatalf("creating Docker client: %v", err)
	}

	// Load all container images from Bazel tarballs.
	loadImage(t, client, "third_party/siderolabs/discovery_service_load/tarball.tar", discoveryRepoTag)
	loadImage(t, client, "third_party/siderolabs/talos_v1_9_5_load/tarball.tar", talosRepoTag)
	loadImage(t, client, "cluster/kubespan_agent/kubespand_load/tarball.tar", kubespandRepoTag)

	// Generate unique test ID for resource names.
	testID := randomHex(8)
	networkName := fmt.Sprintf("%s-%s", networkPrefix, testID)
	t.Logf("test ID: %s, network: %s", testID, networkName)

	// Generate shared cluster credentials.
	clusterID := base64.StdEncoding.EncodeToString(randomBytes(32))
	sharedSecret := base64.StdEncoding.EncodeToString(randomBytes(32))
	t.Logf("cluster_id: %s", clusterID)

	// Create temp directory for test artifacts.
	tmpDir := t.TempDir()

	// Compute discovery container name up front.
	discoveryName := fmt.Sprintf("discovery-%s", testID)

	// Create Docker network.
	network, err := client.CreateNetwork(docker.CreateNetworkOptions{
		Name:    networkName,
		Context: ctx,
	})
	if err != nil {
		t.Fatalf("creating Docker network: %v", err)
	}
	t.Cleanup(func() {
		_ = client.RemoveNetwork(network.ID)
	})

	// Start discovery service (plain gRPC, no TLS).
	discoveryContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: discoveryName,
		Config: &docker.Config{
			Image: discoveryRepoTag,
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
		},
		Context: ctx,
	})
	t.Log("discovery service started")

	// Wait for discovery service to be ready.
	waitForContainer(t, ctx, client, discoveryContainer.ID, 30*time.Second)

	// Write kubespand config.
	configFile := filepath.Join(tmpDir, "agent.yaml")
	writeKubespandConfig(t, configFile, clusterID, sharedSecret, discoveryName+":3000")

	// Generate Talos machine config and start Talos container.
	talosName := fmt.Sprintf("talos-%s", testID)
	talosContainer := startTalosContainer(t, ctx, client, talosName, networkName, clusterID, sharedSecret, discoveryName)

	// Give Talos a moment to start KubeSpan and register with discovery.
	t.Log("waiting for Talos to register with discovery service...")
	time.Sleep(15 * time.Second)

	// Verify containers are healthy before starting kubespand.
	logContainerStatus(t, ctx, client, "discovery", discoveryContainer.ID)
	logContainerStatus(t, ctx, client, "talos", talosContainer.ID)

	// Run kubespand in discovery-only mode.
	kubespandName := fmt.Sprintf("kubespand-%s", testID)
	t.Log("starting kubespand in discovery-only mode...")
	kubespandContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: kubespandName,
		Config: &docker.Config{
			Image: kubespandRepoTag,
			Cmd:   []string{"-config", "/etc/kubespan/agent.yaml", "-discovery-only", "-timeout", "30s"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Binds: []string{
				configFile + ":/etc/kubespan/agent.yaml:ro",
			},
		},
		Context: ctx,
	})

	// Wait for kubespand to exit. 45s deadline (kubespand has -timeout 30s
	// internally, so 45s gives it 15s buffer to exit after its own timeout).
	diagContainers := map[string]string{
		discoveryName: discoveryContainer.ID,
		talosName:     talosContainer.ID,
		kubespandName: kubespandContainer.ID,
	}
	exitCode, err := waitContainerOrFail(t, ctx, client, kubespandContainer.ID, 45*time.Second, diagContainers)
	if err != nil {
		t.Fatalf("waiting for kubespand container: %v", err)
	}

	out := containerLogs(t, ctx, client, kubespandContainer.ID)
	t.Logf("kubespand output:\n%s", out)

	if exitCode != 0 {
		t.Fatalf("kubespand exited with code %d; output:\n%s", exitCode, out)
	}

	// The test passes if kubespand exited 0 (peers found).
	if !strings.Contains(out, "peers found") {
		t.Errorf("kubespand did not find peers; output:\n%s", out)
	}
}

func createAndStartContainer(t *testing.T, ctx context.Context, client *docker.Client, opts docker.CreateContainerOptions) *docker.Container {
	t.Helper()

	container, err := client.CreateContainer(opts)
	if err != nil {
		t.Fatalf("creating container %s: %v", opts.Name, err)
	}

	if err := client.StartContainerWithContext(container.ID, nil, ctx); err != nil {
		t.Fatalf("starting container %s: %v", opts.Name, err)
	}

	// LIFO: removal registered first (runs last), log dump registered second
	// (runs first, while container still exists).
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: container.ID, Force: true})
	})
	t.Cleanup(func() {
		dumpContainerLogs(t, client, container.ID, opts.Name)
	})

	return container
}

// dumpContainerLogs writes a container's logs to TEST_UNDECLARED_OUTPUTS_DIR
// so they appear as test artifacts in CI (BuildBuddy/Bazel).
// Only dumps on test failure to avoid noisy artifacts on success.
func dumpContainerLogs(t *testing.T, client *docker.Client, containerID, name string) {
	t.Helper()

	if !t.Failed() {
		return
	}

	outputDir := os.Getenv("TEST_UNDECLARED_OUTPUTS_DIR")
	if outputDir == "" {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var buf bytes.Buffer
	if err := client.Logs(docker.LogsOptions{
		Context:      ctx,
		Container:    containerID,
		OutputStream: &buf,
		ErrorStream:  &buf,
		Stdout:       true,
		Stderr:       true,
	}); err != nil {
		t.Logf("failed to collect container logs for %s (%s): %v", name, containerID, err)
	}

	logFile := filepath.Join(outputDir, name+".log")
	if err := os.WriteFile(logFile, buf.Bytes(), 0644); err != nil {
		t.Logf("failed to write container logs for %s: %v", name, err)
	}
}

func containerLogs(t *testing.T, ctx context.Context, client *docker.Client, containerID string) string {
	t.Helper()

	var buf bytes.Buffer
	err := client.Logs(docker.LogsOptions{
		Context:      ctx,
		Container:    containerID,
		OutputStream: &buf,
		ErrorStream:  &buf,
		Stdout:       true,
		Stderr:       true,
	})
	if err != nil {
		t.Fatalf("getting container logs: %v", err)
	}
	return buf.String()
}

func loadImage(t *testing.T, client *docker.Client, rlocation, repoTag string) {
	t.Helper()

	tarball := resolveRunfile(t, rlocation)
	t.Logf("loading image %s from %s", repoTag, tarball)

	f, err := os.Open(tarball)
	if err != nil {
		t.Fatalf("opening tarball %s: %v", tarball, err)
	}
	defer f.Close()

	if err := client.LoadImage(docker.LoadImageOptions{InputStream: f}); err != nil {
		t.Fatalf("docker load %s failed: %v", tarball, err)
	}
}

func resolveRunfile(t *testing.T, rlocation string) string {
	t.Helper()

	if dir := os.Getenv("RUNFILES_DIR"); dir != "" {
		p := filepath.Join(dir, "_main", rlocation)
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	if dir := os.Getenv("TEST_SRCDIR"); dir != "" {
		p := filepath.Join(dir, "_main", rlocation)
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}

	exe, err := os.Executable()
	if err == nil {
		runfilesDir := exe + ".runfiles"
		p := filepath.Join(runfilesDir, "_main", rlocation)
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}

	t.Fatalf("could not resolve runfile %q (RUNFILES_DIR=%q, TEST_SRCDIR=%q)", rlocation, os.Getenv("RUNFILES_DIR"), os.Getenv("TEST_SRCDIR"))
	return ""
}

func randomBytes(n int) []byte {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return b
}

func randomHex(n int) string {
	return fmt.Sprintf("%x", randomBytes(n))
}

// writeKubespandConfig writes a kubespand YAML config file using AgentConfig struct.
func writeKubespandConfig(t *testing.T, path, clusterID, sharedSecret, discoveryEndpoint string) {
	t.Helper()

	cfg := agentconfig.AgentConfig{
		ClusterID:         clusterID,
		SharedSecret:      sharedSecret,
		DiscoveryEndpoint: discoveryEndpoint,
		InsecureDiscovery: true,
		ListenPort:        51820,
		MTU:               1420,
		IdentityFile:      "/tmp/kubespan-identity.yaml",
		MachineType:       "worker",
	}

	data, err := yaml.Marshal(cfg)
	if err != nil {
		t.Fatalf("marshaling kubespand config: %v", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		t.Fatalf("writing kubespand config: %v", err)
	}
}

// generateMachineCA creates a self-signed CA certificate and key for the Talos
// machine config. Returns base64-encoded PEM cert and key strings.
func generateMachineCA(t *testing.T) (crtB64, keyB64 string) {
	t.Helper()

	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generating CA key: %v", err)
	}

	template := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "talos-test-ca"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
		BasicConstraintsValid: true,
		IsCA:                  true,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatalf("creating CA cert: %v", err)
	}

	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	keyDER, err := x509.MarshalECPrivateKey(caKey)
	if err != nil {
		t.Fatalf("marshaling CA key: %v", err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})

	return base64.StdEncoding.EncodeToString(certPEM), base64.StdEncoding.EncodeToString(keyPEM)
}

func startTalosContainer(t *testing.T, ctx context.Context, client *docker.Client, name, network, clusterID, sharedSecret, discoveryHost string) *docker.Container {
	t.Helper()
	t.Log("generating Talos machine config...")

	caCrt, _ := generateMachineCA(t)

	talosConfig := map[string]interface{}{
		"version": "v1alpha1",
		"persist": true,
		"machine": map[string]interface{}{
			"type": "worker",
			"ca": map[string]interface{}{
				"crt": caCrt,
			},
			"network": map[string]interface{}{
				"kubespan": map[string]interface{}{
					"enabled": true,
				},
			},
			"features": map[string]interface{}{
				"hostDNS": map[string]interface{}{
					"enabled":              true,
					"forwardKubeDNSToHost": true,
				},
			},
		},
		"cluster": map[string]interface{}{
			"id":     clusterID,
			"secret": sharedSecret,
			"discovery": map[string]interface{}{
				"enabled": true,
				"registries": map[string]interface{}{
					"service": map[string]interface{}{
						"endpoint": fmt.Sprintf("http://%s:3000/", discoveryHost),
					},
				},
			},
			"controlPlane": map[string]interface{}{
				"endpoint": "https://localhost:6443",
			},
		},
	}

	configJSON, err := json.Marshal(talosConfig)
	if err != nil {
		t.Fatalf("marshaling Talos config: %v", err)
	}
	configB64 := base64.StdEncoding.EncodeToString(configJSON)

	t.Log("starting Talos container...")
	container := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: name,
		Config: &docker.Config{
			Image: talosRepoTag,
			Env: []string{
				"PLATFORM=container",
				"USERDATA=" + configB64,
			},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode:    network,
			Privileged:     true,
			SecurityOpt:    []string{"seccomp=unconfined"},
			ReadonlyRootfs: true,
			Tmpfs: map[string]string{
				"/run":    "",
				"/system": "",
				"/tmp":    "",
			},
			Mounts: []docker.HostMount{
				{Target: "/system/state", Type: "volume"},
				{Target: "/var", Type: "volume"},
				{Target: "/etc/cni", Type: "volume"},
				{Target: "/etc/kubernetes", Type: "volume"},
				{Target: "/usr/libexec/kubernetes", Type: "volume"},
				{Target: "/opt", Type: "volume"},
			},
		},
		Context: ctx,
	})
	t.Log("Talos container started")
	return container
}

func waitForContainer(t *testing.T, ctx context.Context, client *docker.Client, containerID string, timeout time.Duration) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		container, err := client.InspectContainerWithContext(containerID, ctx)
		if err == nil && container.State.Running {
			return
		}
		time.Sleep(time.Second)
	}
	t.Fatalf("container %s did not start within %v", containerID, timeout)
}

func TestKubeSpanNetworking(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	// 120s for test logic (images are pre-cached by Bazel, but full mode
	// needs WireGuard setup + connectivity probe). Leaves buffer before
	// the 300s Bazel test timeout so t.Cleanup runs on failure.
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	client, err := docker.NewClientFromEnv()
	if err != nil {
		t.Fatalf("creating Docker client: %v", err)
	}

	// Load all container images from Bazel tarballs.
	loadImage(t, client, "third_party/siderolabs/discovery_service_load/tarball.tar", discoveryRepoTag)
	loadImage(t, client, "third_party/siderolabs/talos_v1_9_5_load/tarball.tar", talosRepoTag)
	loadImage(t, client, "cluster/kubespan_agent/kubespand_test_load/tarball.tar", kubespandTestRepoTag)

	// Generate unique test ID for resource names.
	testID := randomHex(8)
	networkName := fmt.Sprintf("%s-%s", networkPrefix, testID)
	t.Logf("test ID: %s, network: %s", testID, networkName)

	// Generate shared cluster credentials.
	clusterID := base64.StdEncoding.EncodeToString(randomBytes(32))
	sharedSecret := base64.StdEncoding.EncodeToString(randomBytes(32))
	t.Logf("cluster_id: %s", clusterID)

	// Create temp directory for test artifacts.
	tmpDir := t.TempDir()

	// Compute discovery container name up front.
	discoveryName := fmt.Sprintf("discovery-%s", testID)

	// Create Docker network.
	network, err := client.CreateNetwork(docker.CreateNetworkOptions{
		Name:    networkName,
		Context: ctx,
	})
	if err != nil {
		t.Fatalf("creating Docker network: %v", err)
	}
	t.Cleanup(func() {
		_ = client.RemoveNetwork(network.ID)
	})

	// Start discovery service (plain gRPC, no TLS).
	discoveryContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: discoveryName,
		Config: &docker.Config{
			Image: discoveryRepoTag,
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
		},
		Context: ctx,
	})
	t.Log("discovery service started")

	// Wait for discovery service to be ready.
	waitForContainer(t, ctx, client, discoveryContainer.ID, 30*time.Second)

	// Write kubespand config.
	configFile := filepath.Join(tmpDir, "agent.yaml")
	writeKubespandConfig(t, configFile, clusterID, sharedSecret, discoveryName+":3000")

	// Generate Talos machine config and start Talos container.
	talosName := fmt.Sprintf("talos-%s", testID)
	talosContainer := startTalosContainer(t, ctx, client, talosName, networkName, clusterID, sharedSecret, discoveryName)

	// Give Talos a moment to start KubeSpan and register with discovery.
	t.Log("waiting for Talos to register with discovery service...")
	time.Sleep(15 * time.Second)

	// Verify containers are healthy before starting kubespand.
	logContainerStatus(t, ctx, client, "discovery", discoveryContainer.ID)
	logContainerStatus(t, ctx, client, "talos", talosContainer.ID)

	// Run kubespand in FULL mode (with WireGuard and routing).
	kubespandName := fmt.Sprintf("kubespand-%s", testID)
	t.Log("starting kubespand in full mode...")
	kubespandContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: kubespandName,
		Config: &docker.Config{
			Image: kubespandTestRepoTag,
			Cmd:   []string{"-config", "/etc/kubespan/agent.yaml"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Privileged:  true,
			Binds: []string{
				configFile + ":/etc/kubespan/agent.yaml:ro",
			},
		},
		Context: ctx,
	})

	// Wait for kubespand to discover a peer and extract its KubeSpan address.
	t.Log("waiting for kubespand to discover and configure peer...")
	peerAddr := pollLogsForField(t, ctx, client, kubespandContainer.ID, "configuring peer", "address", 60*time.Second)

	// Validate and parse the discovered address (logged as netip.Prefix like "fd63:.../128").
	prefix, err := netip.ParsePrefix(peerAddr)
	if err != nil {
		t.Fatalf("invalid peer address %q from container logs: %v", peerAddr, err)
	}
	peerAddr = prefix.Addr().String()
	t.Logf("peer KubeSpan address: %s", peerAddr)

	// Verify connectivity by pinging the peer through the WireGuard tunnel.
	t.Log("probing peer KubeSpan address via ICMPv6...")
	exitCode, probeOut := dockerExec(t, ctx, client, kubespandContainer.ID, []string{"/testprobe", "-timeout", "60s", peerAddr})

	logs := containerLogs(t, ctx, client, kubespandContainer.ID)
	t.Logf("kubespand logs:\n%s", logs)
	t.Logf("probe output: %s", probeOut)

	if exitCode != 0 {
		t.Fatalf("connectivity probe failed (exit %d): %s", exitCode, probeOut)
	}
}

// pollLogsForField polls a container's logs for a JSON log line with the given
// msg field, then returns the value of the specified field from that line.
func pollLogsForField(t *testing.T, ctx context.Context, client *docker.Client, containerID, logMsg, fieldName string, timeout time.Duration) string {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		logs := containerLogs(t, ctx, client, containerID)
		for _, line := range strings.Split(logs, "\n") {
			line = strings.TrimSpace(line)
			if line == "" || line[0] != '{' {
				continue
			}
			var entry map[string]interface{}
			if err := json.Unmarshal([]byte(line), &entry); err != nil {
				continue
			}
			msg, _ := entry["msg"].(string)
			if msg != logMsg {
				continue
			}
			val, _ := entry[fieldName].(string)
			if val != "" {
				return val
			}
		}
		time.Sleep(2 * time.Second)
	}

	// Dump logs on failure for debugging.
	logs := containerLogs(t, ctx, client, containerID)
	t.Fatalf("timed out waiting for log line %q with field %q; logs:\n%s", logMsg, fieldName, logs)
	return ""
}

// logContainerStatus logs the current state of a container.
func logContainerStatus(t *testing.T, ctx context.Context, client *docker.Client, name, containerID string) {
	t.Helper()

	info, err := client.InspectContainerWithContext(containerID, ctx)
	if err != nil {
		t.Logf("[status] %s: inspect failed: %v", name, err)
		return
	}
	t.Logf("[status] %s: status=%s running=%v exitCode=%d pid=%d",
		name, info.State.Status, info.State.Running, info.State.ExitCode, info.State.Pid)
}

// waitContainerOrFail waits for a container to exit, logging periodic status
// updates. If the container doesn't exit within the deadline, it dumps logs
// from all diagnostic containers before failing the test.
func waitContainerOrFail(t *testing.T, ctx context.Context, client *docker.Client, containerID string, timeout time.Duration, diagContainers map[string]string) (int, error) {
	t.Helper()

	waitCtx, waitCancel := context.WithTimeout(ctx, timeout)
	defer waitCancel()

	type waitResult struct {
		exitCode int
		err      error
	}
	resultCh := make(chan waitResult, 1)
	go func() {
		code, err := client.WaitContainerWithContext(containerID, waitCtx)
		resultCh <- waitResult{code, err}
	}()

	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case r := <-resultCh:
			if r.err != nil {
				t.Logf("container wait failed: %v — collecting diagnostics", r.err)
				dumpAllContainerLogs(t, client, diagContainers)
			}
			return r.exitCode, r.err

		case <-ticker.C:
			for name, id := range diagContainers {
				logContainerStatus(t, ctx, client, name, id)
			}
		}
	}
}

// dumpAllContainerLogs dumps logs from all containers to the test log
// for postmortem debugging. Uses a fresh context to avoid inheriting
// a cancelled parent.
func dumpAllContainerLogs(t *testing.T, client *docker.Client, containers map[string]string) {
	t.Helper()

	diagCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	for name, id := range containers {
		logContainerStatus(t, diagCtx, client, name, id)

		var buf bytes.Buffer
		_ = client.Logs(docker.LogsOptions{
			Context:      diagCtx,
			Container:    id,
			OutputStream: &buf,
			ErrorStream:  &buf,
			Stdout:       true,
			Stderr:       true,
			Tail:         "200",
		})
		t.Logf("[diag] %s logs (last 200 lines):\n%s", name, buf.String())
	}
}

// dockerExec runs a command inside a container and returns the exit code and combined output.
func dockerExec(t *testing.T, ctx context.Context, client *docker.Client, containerID string, cmd []string) (int, string) {
	t.Helper()

	exec, err := client.CreateExec(docker.CreateExecOptions{
		AttachStdout: true,
		AttachStderr: true,
		Cmd:          cmd,
		Container:    containerID,
		Context:      ctx,
	})
	if err != nil {
		t.Fatalf("creating exec: %v", err)
	}

	var buf bytes.Buffer
	if err := client.StartExec(exec.ID, docker.StartExecOptions{
		OutputStream: &buf,
		ErrorStream:  &buf,
		Context:      ctx,
	}); err != nil {
		t.Fatalf("starting exec: %v", err)
	}

	info, err := client.InspectExec(exec.ID)
	if err != nil {
		t.Fatalf("inspecting exec: %v", err)
	}

	return info.ExitCode, buf.String()
}
