// Shared helpers for booting Talos VMs and interacting with the Talos API
// in QEMU integration tests.
package qemu_tests

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/cosi-project/runtime/pkg/safe"
	"github.com/siderolabs/talos/pkg/machinery/client"
	clientconfig "github.com/siderolabs/talos/pkg/machinery/client/config"
	"github.com/siderolabs/talos/pkg/machinery/resources/kubespan"
)

// KubespanPeerResult holds the result of a KubeSpan peer status query.
type KubespanPeerResult struct {
	Label    string             `json:"label"`
	State    kubespan.PeerState `json:"state"`
	Endpoint string             `json:"endpoint"`
}

// MgmtNIC returns QEMU args for a user-mode management NIC with TCP port forwarding to port 50000.
func MgmtNIC(hostPort int) []string {
	return []string{
		"-netdev", fmt.Sprintf("user,id=mgmt,hostfwd=tcp::%d-:50000", hostPort),
		"-device", "virtio-net-pci,netdev=mgmt,mac=52:54:00:ab:00:01",
	}
}

// pollUntil calls fn every second until it returns true or the deadline passes.
// Returns true if fn returned true, false on timeout.
func pollUntil(deadline time.Time, fn func() bool) bool {
	for time.Now().Before(deadline) {
		if fn() {
			return true
		}
		time.Sleep(1 * time.Second)
	}
	return false
}

// BootTalosVM starts a Talos QEMU VM from a qcow2 disk image with CIDATA config.
// Uses snapshot=on so QEMU creates a temporary overlay per VM, keeping the
// base image read-only and allowing multiple VMs to share it.
func BootTalosVM(t *testing.T, name, baseImage, cidataPath string, mgmtPort int, netArgs []string) *VM {
	t.Helper()

	args := []string{
		"-drive", fmt.Sprintf("file=%s,if=virtio,format=qcow2,snapshot=on", baseImage),
		"-drive", fmt.Sprintf("file=%s,if=virtio,format=raw,readonly=on", cidataPath),
		"-nographic",
		"-m", "1536",
		"-machine", "accel=tcg",
		"-cpu", "max",
		"-display", "none",
		"-smp", "2",
	}

	args = append(args, netArgs...)

	if mgmtPort > 0 {
		args = append(args, MgmtNIC(mgmtPort)...)
	}

	return StartVM(t, name, exec.Command("qemu-system-x86_64", args...), false)
}

// CreateCIDATA creates a FAT32 disk image with cloud-init metadata for Talos.
func CreateCIDATA(t *testing.T, tmpDir, name string, machineConfig []byte) string {
	t.Helper()

	ciDir := filepath.Join(tmpDir, "cidata-"+name)
	os.MkdirAll(ciDir, 0o755)

	metaData := fmt.Sprintf("instance-id: %s\nlocal-hostname: %s\n", name, name)
	os.WriteFile(filepath.Join(ciDir, "meta-data"), []byte(metaData), 0o644)
	os.WriteFile(filepath.Join(ciDir, "user-data"), machineConfig, 0o644)

	imgPath := filepath.Join(tmpDir, fmt.Sprintf("cidata-%s.img", name))

	RunCmd(t, "dd", "if=/dev/zero", "of="+imgPath, "bs=1M", "count=4")
	RunCmd(t, "/usr/sbin/mkfs.vfat", "-n", "cidata", imgPath)
	RunCmd(t, "/usr/bin/mcopy", "-i", imgPath, filepath.Join(ciDir, "meta-data"), "::")
	RunCmd(t, "/usr/bin/mcopy", "-i", imgPath, filepath.Join(ciDir, "user-data"), "::")

	t.Logf("created CIDATA for %s: %s", name, imgPath)
	return imgPath
}

// NewTalosClient creates a Talos API client from a talosconfig file.
func NewTalosClient(t *testing.T, configPath, endpoint string) *client.Client {
	t.Helper()

	cfg, err := clientconfig.Open(configPath)
	if err != nil {
		t.Fatalf("open talosconfig: %v", err)
	}

	c, err := client.New(context.Background(),
		client.WithConfig(cfg),
		client.WithEndpoints(endpoint),
	)
	if err != nil {
		t.Fatalf("create talos client: %v", err)
	}

	return c
}

// WaitForTalosAPI polls client.Version() until the Talos API responds.
func WaitForTalosAPI(t *testing.T, c *client.Client, nodeIP string, timeout time.Duration) {
	t.Helper()
	if !pollUntil(time.Now().Add(timeout), func() bool {
		ctx, cancel := context.WithTimeout(client.WithNode(context.Background(), nodeIP), 5*time.Second)
		resp, err := c.Version(ctx)
		cancel()
		if err != nil {
			t.Logf("waiting for talos API: %v", err)
			return false
		}
		tag := ""
		for _, msg := range resp.Messages {
			if msg.Version != nil {
				tag = msg.Version.Tag
			}
		}
		t.Logf("talos API ready: %s", tag)
		return true
	}) {
		t.Fatalf("talos API not reachable after %v", timeout)
	}
}

// PollKubeSpanStatus polls the Talos COSI API for KubeSpan peer status.
// Returns when at least minPeers peers are found and all are in "up" state.
func PollKubeSpanStatus(t *testing.T, c *client.Client, nodeIP string, timeout time.Duration) ([]KubespanPeerResult, error) {
	t.Helper()

	var lastErr string
	var finalPeers []KubespanPeerResult

	pollUntil(time.Now().Add(timeout), func() bool {
		ctx, cancel := context.WithTimeout(client.WithNode(context.Background(), nodeIP), 10*time.Second)
		list, err := safe.StateListAll[*kubespan.PeerStatus](ctx, c.COSI)
		cancel()
		if err != nil {
			lastErr = err.Error()
			t.Logf("COSI poll (waiting): %s", lastErr)
			return false
		}

		var peers []KubespanPeerResult
		for it := list.Iterator(); it.Next(); {
			ps := it.Value()
			peers = append(peers, KubespanPeerResult{
				Label:    ps.TypedSpec().Label,
				State:    ps.TypedSpec().State,
				Endpoint: ps.TypedSpec().Endpoint.String(),
			})
		}

		allUp := len(peers) >= 2
		for _, p := range peers {
			if p.State != kubespan.PeerStateUp {
				allUp = false
			}
		}
		finalPeers = peers
		return allUp
	})

	allUp := len(finalPeers) >= 2
	for _, p := range finalPeers {
		if p.State != kubespan.PeerStateUp {
			allUp = false
		}
	}
	if allUp {
		return finalPeers, nil
	}
	return nil, fmt.Errorf("timeout after %v, last error: %s", timeout, lastErr)
}
