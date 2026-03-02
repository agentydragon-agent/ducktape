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
	"net"
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

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
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

	// Generate self-signed TLS cert for the discovery service.
	certFile, keyFile := generateTLSCert(t, tmpDir)

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

	// Start discovery service.
	discoveryName := fmt.Sprintf("discovery-%s", testID)
	discoveryContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: discoveryName,
		Config: &docker.Config{
			Image: discoveryRepoTag,
			Cmd:   []string{"-certificate-path", "/tls/cert.pem", "-key-path", "/tls/key.pem"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Binds: []string{
				certFile + ":/tls/cert.pem:ro",
				keyFile + ":/tls/key.pem:ro",
			},
		},
		Context: ctx,
	})
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: discoveryContainer.ID, Force: true})
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
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: talosContainer.ID, Force: true})
	})

	// Give Talos a moment to start KubeSpan and register with discovery.
	t.Log("waiting for Talos to register with discovery service...")
	time.Sleep(15 * time.Second)

	// Run kubespand in discovery-only mode.
	kubespandName := fmt.Sprintf("kubespand-%s", testID)
	t.Log("starting kubespand in discovery-only mode...")
	kubespandContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: kubespandName,
		Config: &docker.Config{
			Image: kubespandRepoTag,
			Cmd:   []string{"/kubespand", "-config", "/etc/kubespan/agent.yaml", "-discovery-only", "-timeout", "120s"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Binds: []string{
				configFile + ":/etc/kubespan/agent.yaml:ro",
			},
		},
		Context: ctx,
	})
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: kubespandContainer.ID, Force: true})
	})

	// Wait for kubespand to exit and collect logs.
	exitCode, err := client.WaitContainerWithContext(kubespandContainer.ID, ctx)
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

	// Dump logs to undeclared test outputs on cleanup for postmortem analysis.
	t.Cleanup(func() {
		dumpContainerLogs(t, client, container.ID, opts.Name)
	})

	return container
}

// dumpContainerLogs writes a container's logs to TEST_UNDECLARED_OUTPUTS_DIR
// so they appear as test artifacts in CI (BuildBuddy/Bazel).
func dumpContainerLogs(t *testing.T, client *docker.Client, containerID, name string) {
	t.Helper()

	outputDir := os.Getenv("TEST_UNDECLARED_OUTPUTS_DIR")
	if outputDir == "" {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var buf bytes.Buffer
	_ = client.Logs(docker.LogsOptions{
		Context:      ctx,
		Container:    containerID,
		OutputStream: &buf,
		ErrorStream:  &buf,
		Stdout:       true,
		Stderr:       true,
	})

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

func generateTLSCert(t *testing.T, dir string) (certFile, keyFile string) {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generating TLS key: %v", err)
	}

	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "discovery-test"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:     []string{"discovery-test", "localhost"},
		IPAddresses:  []net.IP{net.ParseIP("127.0.0.1")},
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("creating self-signed cert: %v", err)
	}

	certFile = filepath.Join(dir, "cert.pem")
	keyFile = filepath.Join(dir, "key.pem")

	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	if err := os.WriteFile(certFile, certPEM, 0644); err != nil {
		t.Fatalf("writing cert: %v", err)
	}

	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatalf("marshaling key: %v", err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(keyFile, keyPEM, 0600); err != nil {
		t.Fatalf("writing key: %v", err)
	}

	return certFile, keyFile
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

func startTalosContainer(t *testing.T, ctx context.Context, client *docker.Client, name, network, clusterID, sharedSecret, discoveryHost string) *docker.Container {
	t.Helper()
	t.Log("generating Talos machine config...")

	talosConfig := map[string]interface{}{
		"version": "v1alpha1",
		"persist": false,
		"machine": map[string]interface{}{
			"type": "worker",
			"network": map[string]interface{}{
				"kubespan": map[string]interface{}{
					"enabled": true,
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
						"endpoint": fmt.Sprintf("https://%s:3000/", discoveryHost),
					},
				},
			},
			"controlPlane": map[string]interface{}{
				"endpoint": "https://localhost:6443",
			},
			"clusterNetwork": map[string]interface{}{
				"dnsDomain":      "cluster.local",
				"podSubnets":     []string{"10.244.0.0/16"},
				"serviceSubnets": []string{"10.96.0.0/12"},
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
			NetworkMode: network,
			Privileged:  true,
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

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
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

	// Generate self-signed TLS cert for the discovery service.
	certFile, keyFile := generateTLSCert(t, tmpDir)

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

	// Start discovery service.
	discoveryName := fmt.Sprintf("discovery-%s", testID)
	discoveryContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: discoveryName,
		Config: &docker.Config{
			Image: discoveryRepoTag,
			Cmd:   []string{"-certificate-path", "/tls/cert.pem", "-key-path", "/tls/key.pem"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Binds: []string{
				certFile + ":/tls/cert.pem:ro",
				keyFile + ":/tls/key.pem:ro",
			},
		},
		Context: ctx,
	})
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: discoveryContainer.ID, Force: true})
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
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: talosContainer.ID, Force: true})
	})

	// Give Talos a moment to start KubeSpan and register with discovery.
	t.Log("waiting for Talos to register with discovery service...")
	time.Sleep(15 * time.Second)

	// Run kubespand in FULL mode (with WireGuard and routing).
	kubespandName := fmt.Sprintf("kubespand-%s", testID)
	t.Log("starting kubespand in full mode...")
	kubespandContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: kubespandName,
		Config: &docker.Config{
			Image: kubespandTestRepoTag,
			Cmd:   []string{"/kubespand", "-config", "/etc/kubespan/agent.yaml"},
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
	t.Cleanup(func() {
		_ = client.RemoveContainer(docker.RemoveContainerOptions{ID: kubespandContainer.ID, Force: true})
	})

	// Wait for kubespand to discover a peer and extract its KubeSpan address.
	t.Log("waiting for kubespand to discover and configure peer...")
	peerAddr := pollLogsForField(t, ctx, client, kubespandContainer.ID, "configuring peer", "address", 120*time.Second)

	// Strip the /128 prefix length if present to get the bare IPv6 address.
	if idx := strings.Index(peerAddr, "/"); idx != -1 {
		peerAddr = peerAddr[:idx]
	}
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
