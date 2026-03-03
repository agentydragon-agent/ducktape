package main

import (
	"context"
	"fmt"
	"testing"
	"time"

	docker "github.com/fsouza/go-dockerclient"
)

// TestNftablesSmoke runs graduated nftables smoke tests (levels 1-6) inside
// Docker containers to isolate which nftables operation triggers EBUSY.
// See NFTABLES_EBUSY.md for results and analysis.
func TestNftablesSmoke(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	client, err := docker.NewClientFromEnv()
	if err != nil {
		t.Fatalf("creating Docker client: %v", err)
	}

	loadImage(t, client, "cluster/kubespan_agent/kubespand_test_load/tarball.tar", kubespandTestRepoTag)

	testID := randomHex(8)

	levels := []struct {
		level int
		desc  string
	}{
		{1, "table+chains"},
		{2, "anonymous-interval-set"},
		{3, "mark-expressions"},
		{4, "single-batch"},
		{5, "flushchain-reinstall"},
		{6, "full-kubespand-pattern"},
	}

	modes := []struct {
		name    string
		network string
	}{
		{"network-none", "none"},
		{"default-bridge", ""},
	}

	for _, lvl := range levels {
		for _, mode := range modes {
			name := fmt.Sprintf("level%d-%s/%s", lvl.level, lvl.desc, mode.name)
			lvl, mode := lvl, mode
			t.Run(name, func(t *testing.T) {
				containerName := fmt.Sprintf("nft-l%d-%s-%s", lvl.level, mode.name, testID)
				opts := docker.CreateContainerOptions{
					Name: containerName,
					Config: &docker.Config{
						Image:      kubespandTestRepoTag,
						Entrypoint: []string{"/testprobe"},
						Cmd:        []string{fmt.Sprintf("-nft-smoke=%d", lvl.level)},
					},
					HostConfig: &docker.HostConfig{
						Privileged: true,
					},
					Context: ctx,
				}
				if mode.network != "" {
					opts.HostConfig.NetworkMode = mode.network
				}

				container := createAndStartContainer(t, ctx, client, opts)
				exitCode, err := client.WaitContainerWithContext(container.ID, ctx)
				out := containerLogs(t, ctx, client, container.ID)
				t.Logf("exit=%d output:\n%s", exitCode, out)
				if err != nil {
					t.Fatalf("waiting for container: %v", err)
				}
				if exitCode != 0 {
					t.Fatalf("nft-smoke level %d failed on %s (exit %d)", lvl.level, mode.name, exitCode)
				}
			})
		}
	}
}
