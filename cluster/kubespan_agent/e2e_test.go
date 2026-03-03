// Integration tests for kubespand: verifies peer discovery and network
// connectivity between two kubespand instances via a local discovery service.
// Requires Docker, ~1 minute.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
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
	kubespandRepoTag     = "kubespand:latest"
	kubespandTestRepoTag = "kubespand-test:latest"
	networkPrefix        = "kubespan-e2e"
)

// TestKubeSpanDiscovery runs two kubespand instances in discovery-only mode and
// verifies they discover each other via the discovery service.
func TestKubeSpanDiscovery(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	client, err := docker.NewClientFromEnv()
	if err != nil {
		t.Fatalf("creating Docker client: %v", err)
	}

	loadImage(t, client, "third_party/siderolabs/discovery_service_load/tarball.tar", discoveryRepoTag)
	loadImage(t, client, "cluster/kubespan_agent/kubespand_load/tarball.tar", kubespandRepoTag)

	testID := randomHex(8)
	networkName := fmt.Sprintf("%s-%s", networkPrefix, testID)
	t.Logf("test ID: %s, network: %s", testID, networkName)

	clusterID := base64.StdEncoding.EncodeToString(randomBytes(32))
	sharedSecret := base64.StdEncoding.EncodeToString(randomBytes(32))
	t.Logf("cluster_id: %s", clusterID)

	tmpDir := t.TempDir()
	discoveryName := fmt.Sprintf("discovery-%s", testID)

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

	discoveryContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: discoveryName,
		Config: &docker.Config{
			Image: discoveryRepoTag,
			Cmd:   []string{"-debug"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
		},
		Context: ctx,
	})
	t.Log("discovery service started")
	waitForContainer(t, ctx, client, discoveryContainer.ID, 30*time.Second)

	// Write configs for two kubespand instances (same cluster, different identity files).
	configA := filepath.Join(tmpDir, "agent-a.yaml")
	configB := filepath.Join(tmpDir, "agent-b.yaml")
	writeKubespandConfig(t, configA, clusterID, sharedSecret, discoveryName+":3000", 51820, "/tmp/kubespan-identity-a.yaml")
	writeKubespandConfig(t, configB, clusterID, sharedSecret, discoveryName+":3000", 51821, "/tmp/kubespan-identity-b.yaml")

	// Start both kubespand instances in discovery-only mode.
	nameA := fmt.Sprintf("kubespand-a-%s", testID)
	nameB := fmt.Sprintf("kubespand-b-%s", testID)

	t.Log("starting kubespand-a in discovery-only mode...")
	containerA := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: nameA,
		Config: &docker.Config{
			Image: kubespandRepoTag,
			Cmd:   []string{"-config", "/etc/kubespan/agent.yaml", "-discovery-only", "-timeout", "30s", "-debug"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Binds:       []string{configA + ":/etc/kubespan/agent.yaml:ro"},
		},
		Context: ctx,
	})

	t.Log("starting kubespand-b in discovery-only mode...")
	containerB := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: nameB,
		Config: &docker.Config{
			Image: kubespandRepoTag,
			Cmd:   []string{"-config", "/etc/kubespan/agent.yaml", "-discovery-only", "-timeout", "30s", "-debug"},
		},
		HostConfig: &docker.HostConfig{
			NetworkMode: networkName,
			Binds:       []string{configB + ":/etc/kubespan/agent.yaml:ro"},
		},
		Context: ctx,
	})

	// Wait for kubespand-a to exit (it should find kubespand-b as a peer).
	diagContainers := map[string]string{
		discoveryName: discoveryContainer.ID,
		nameA:         containerA.ID,
		nameB:         containerB.ID,
	}
	exitCode, err := waitContainerOrFail(t, ctx, client, containerA.ID, 45*time.Second, diagContainers)
	if err != nil {
		t.Fatalf("waiting for kubespand-a: %v", err)
	}

	out := containerLogs(t, ctx, client, containerA.ID)
	t.Logf("kubespand-a output:\n%s", out)

	if exitCode != 0 {
		t.Fatalf("kubespand-a exited with code %d; output:\n%s", exitCode, out)
	}

	if !strings.Contains(out, "peers found") {
		t.Errorf("kubespand-a did not find peers; output:\n%s", out)
	}
}

// TestNftablesSmoke tests whether nftables operations work in Docker containers.
// Runs the nft-smoke probe in two configurations:
//   - --network=none (clean netns, no Docker-managed iptables/nftables rules)
//   - default bridge (Docker adds veth+bridge iptables-nft rules to netns)
//
// This diagnostic test isolates the nftables EBUSY root cause:
// if --network=none passes but default bridge fails, Docker's bridge setup
// is the culprit (structural EBUSY from iptable_nat or bridge nftables rules).
func TestNftablesSmoke(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	client, err := docker.NewClientFromEnv()
	if err != nil {
		t.Fatalf("creating Docker client: %v", err)
	}

	loadImage(t, client, "cluster/kubespan_agent/kubespand_test_load/tarball.tar", kubespandTestRepoTag)

	testID := randomHex(8)

	// Test 1: --network=none (clean netns).
	t.Run("network-none", func(t *testing.T) {
		name := fmt.Sprintf("nft-smoke-none-%s", testID)
		container := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
			Name: name,
			Config: &docker.Config{
				Image:      kubespandTestRepoTag,
				Entrypoint: []string{"/testprobe"},
				Cmd:        []string{"-nft-smoke"},
			},
			HostConfig: &docker.HostConfig{
				Privileged:  true,
				NetworkMode: "none",
			},
			Context: ctx,
		})
		exitCode, err := client.WaitContainerWithContext(container.ID, ctx)
		out := containerLogs(t, ctx, client, container.ID)
		t.Logf("nft-smoke (network=none) exit=%d output:\n%s", exitCode, out)
		if err != nil {
			t.Fatalf("waiting for container: %v", err)
		}
		if exitCode != 0 {
			t.Fatalf("nftables smoke test failed with --network=none (exit %d)", exitCode)
		}
	})

	// Test 2: default bridge (Docker-managed networking).
	t.Run("default-bridge", func(t *testing.T) {
		name := fmt.Sprintf("nft-smoke-bridge-%s", testID)
		container := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
			Name: name,
			Config: &docker.Config{
				Image:      kubespandTestRepoTag,
				Entrypoint: []string{"/testprobe"},
				Cmd:        []string{"-nft-smoke"},
			},
			HostConfig: &docker.HostConfig{
				Privileged: true,
			},
			Context: ctx,
		})
		exitCode, err := client.WaitContainerWithContext(container.ID, ctx)
		out := containerLogs(t, ctx, client, container.ID)
		t.Logf("nft-smoke (default bridge) exit=%d output:\n%s", exitCode, out)
		if err != nil {
			t.Fatalf("waiting for container: %v", err)
		}
		if exitCode != 0 {
			t.Logf("nftables EBUSY on default bridge — Docker's bridge setup causes structural EBUSY")
		}
	})
}

// TestKubeSpanNetworking runs two kubespand instances in full mode and verifies
// ICMPv6 connectivity through the WireGuard tunnel.
//
// Containers start with --network=none so kubespand installs nftables rules
// in a clean netns (no Docker-managed iptables-nft rules). After nftables
// setup, containers are connected to the default bridge via Docker API for
// discovery service access.
func TestKubeSpanNetworking(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()

	client, err := docker.NewClientFromEnv()
	if err != nil {
		t.Fatalf("creating Docker client: %v", err)
	}

	loadImage(t, client, "third_party/siderolabs/discovery_service_load/tarball.tar", discoveryRepoTag)
	loadImage(t, client, "cluster/kubespan_agent/kubespand_test_load/tarball.tar", kubespandTestRepoTag)

	testID := randomHex(8)
	t.Logf("test ID: %s", testID)

	clusterID := base64.StdEncoding.EncodeToString(randomBytes(32))
	sharedSecret := base64.StdEncoding.EncodeToString(randomBytes(32))
	t.Logf("cluster_id: %s", clusterID)

	tmpDir := t.TempDir()
	discoveryName := fmt.Sprintf("discovery-%s", testID)

	// Discovery service runs on default bridge (doesn't need nftables).
	discoveryContainer := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: discoveryName,
		Config: &docker.Config{
			Image: discoveryRepoTag,
			Cmd:   []string{"-debug"},
		},
		HostConfig: &docker.HostConfig{},
		Context:    ctx,
	})
	t.Log("discovery service started")
	waitForContainer(t, ctx, client, discoveryContainer.ID, 30*time.Second)

	discInfo, err := client.InspectContainerWithContext(discoveryContainer.ID, ctx)
	if err != nil {
		t.Fatalf("inspecting discovery container: %v", err)
	}
	discoveryIP := discInfo.NetworkSettings.IPAddress
	if discoveryIP == "" {
		t.Fatal("discovery container has no IP address")
	}
	discoveryEndpoint := fmt.Sprintf("%s:3000", discoveryIP)
	t.Logf("discovery endpoint: %s", discoveryEndpoint)

	// Write kubespand configs before starting containers (bind-mounted in).
	configA := filepath.Join(tmpDir, "agent-a.yaml")
	configB := filepath.Join(tmpDir, "agent-b.yaml")
	writeKubespandConfig(t, configA, clusterID, sharedSecret, discoveryEndpoint, 51820, "/tmp/kubespan-identity-a.yaml")
	writeKubespandConfig(t, configB, clusterID, sharedSecret, discoveryEndpoint, 51821, "/tmp/kubespan-identity-b.yaml")

	nameA := fmt.Sprintf("kubespand-a-%s", testID)
	nameB := fmt.Sprintf("kubespand-b-%s", testID)

	// kubespand containers start with --network=none for a clean netns
	// free of Docker-managed iptables/nftables rules. kubespand installs
	// its nftables rules in this clean namespace. We then connect the
	// containers to a Docker bridge for discovery service connectivity.
	// COSI controllers retry failed operations, so kubespand will
	// recover once networking becomes available.
	t.Log("starting kubespand containers with --network=none...")
	containerA := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: nameA,
		Config: &docker.Config{
			Image: kubespandTestRepoTag,
			Cmd:   []string{"-config", "/etc/kubespan/agent.yaml", "-debug"},
		},
		HostConfig: &docker.HostConfig{
			Privileged:  true,
			NetworkMode: "none",
			Binds:       []string{configA + ":/etc/kubespan/agent.yaml:ro"},
		},
		Context: ctx,
	})

	containerB := createAndStartContainer(t, ctx, client, docker.CreateContainerOptions{
		Name: nameB,
		Config: &docker.Config{
			Image: kubespandTestRepoTag,
			Cmd:   []string{"-config", "/etc/kubespan/agent.yaml", "-debug"},
		},
		HostConfig: &docker.HostConfig{
			Privileged:  true,
			NetworkMode: "none",
			Binds:       []string{configB + ":/etc/kubespan/agent.yaml:ro"},
		},
		Context: ctx,
	})

	// Verify nftables works in the clean netns.
	t.Log("verifying nftables in clean netns...")
	nftExitCode, nftOut := dockerExec(t, ctx, client, containerA.ID, []string{"/testprobe", "-nft-smoke"})
	t.Logf("nft-smoke in container-a: exit=%d output:\n%s", nftExitCode, nftOut)
	if nftExitCode != 0 {
		t.Skipf("nftables unavailable in --network=none container (exit %d); skipping networking test", nftExitCode)
	}

	// Give kubespand a moment to install nftables rules in the clean netns
	// before we add Docker bridge networking (which adds its own iptables-nft rules).
	t.Log("waiting for kubespand to install nftables rules...")
	time.Sleep(5 * time.Second)

	// Connect containers to the default bridge for discovery service access.
	// Docker's bridge setup adds iptables-nft rules to the container's netns,
	// but kubespand's nftables are already installed by this point.
	t.Log("connecting containers to default bridge for discovery...")
	if err := client.ConnectNetwork("bridge", docker.NetworkConnectionOptions{
		Container: containerA.ID,
		Context:   ctx,
	}); err != nil {
		t.Fatalf("connecting container A to bridge: %v", err)
	}
	if err := client.ConnectNetwork("bridge", docker.NetworkConnectionOptions{
		Container: containerB.ID,
		Context:   ctx,
	}); err != nil {
		t.Fatalf("connecting container B to bridge: %v", err)
	}
	t.Log("containers connected to bridge network")

	// Wait for kubespand-a to discover and configure its peer.
	t.Log("waiting for kubespand-a to discover and configure peer...")
	peerAddrRaw := pollLogsForField(t, ctx, client, containerA.ID, "configuring peer", "address", 90*time.Second)

	peerAddr, err := netip.ParseAddr(peerAddrRaw)
	if err != nil {
		t.Fatalf("invalid peer address %q from container logs: %v", peerAddrRaw, err)
	}
	t.Logf("peer KubeSpan address: %s", peerAddr)

	// Verify connectivity through WireGuard tunnel.
	t.Log("probing peer KubeSpan address via ICMPv6...")
	probeExitCode, probeOut := dockerExec(t, ctx, client, containerA.ID, []string{"/testprobe", "-timeout", "60s", peerAddr.String()})
	t.Logf("probe output: %s", probeOut)

	if probeExitCode != 0 {
		logsA := containerLogs(t, ctx, client, containerA.ID)
		t.Logf("kubespand-a logs:\n%s", logsA)
		logsB := containerLogs(t, ctx, client, containerB.ID)
		t.Logf("kubespand-b logs:\n%s", logsB)
		t.Fatalf("connectivity probe failed (exit %d): %s", probeExitCode, probeOut)
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
// Always dumps for postmortem analysis.
func dumpContainerLogs(t *testing.T, client *docker.Client, containerID, name string) {
	t.Helper()

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
func writeKubespandConfig(t *testing.T, path, clusterID, sharedSecret, discoveryEndpoint string, listenPort int, identityFile string) {
	t.Helper()

	cfg := agentconfig.AgentConfig{
		ClusterID:         clusterID,
		SharedSecret:      sharedSecret,
		DiscoveryEndpoint: discoveryEndpoint,
		InsecureDiscovery: true,
		ForceRouting:      true,
		ListenPort:        listenPort,
		MTU:               1420,
		IdentityFile:      identityFile,
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

// pollLogsForField polls a container's logs for a log line containing logMsg,
// then returns the value of the specified field from the JSON-structured part
// of that line. Handles both JSON (production) and tab-delimited (development)
// zap output formats.
func pollLogsForField(t *testing.T, ctx context.Context, client *docker.Client, containerID, logMsg, fieldName string, timeout time.Duration) string {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		logs := containerLogs(t, ctx, client, containerID)
		for _, line := range strings.Split(logs, "\n") {
			line = strings.TrimSpace(line)
			if !strings.Contains(line, logMsg) {
				continue
			}
			// Find JSON part of the line (works for both formats).
			jsonIdx := strings.Index(line, "{")
			if jsonIdx < 0 {
				continue
			}
			var entry map[string]interface{}
			if err := json.Unmarshal([]byte(line[jsonIdx:]), &entry); err != nil {
				continue
			}
			val, _ := entry[fieldName].(string)
			if val != "" {
				return val
			}
		}
		time.Sleep(2 * time.Second)
	}

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

// dumpContainerDiagnostics captures networking state inside a container.
func dumpContainerDiagnostics(t *testing.T, ctx context.Context, client *docker.Client, name, containerID string) {
	t.Helper()

	cmds := [][]string{
		{"ls", "-la", "/proc/sys/net/netfilter/"},
	}
	for _, cmd := range cmds {
		_, out := dockerExec(t, ctx, client, containerID, cmd)
		if out != "" {
			t.Logf("[diag] %s exec %v:\n%s", name, cmd, out)
		}
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
