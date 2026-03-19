// Helper to boot Talos VMs from raw disk images (Image Factory format).
package nebula_demo

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"testing"

	h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
)

// DecompressTalosImage decompresses a .raw.zst Talos image to a raw file in tmpDir.
// Tries zstd CLI first, falls back to python3 with the zstandard module.
func DecompressTalosImage(t *testing.T, tmpDir string) string {
	t.Helper()
	zstPath := h.RunfilePath(t, TalosNebulaImageZstPath)
	rawPath := filepath.Join(tmpDir, "talos-nebula.raw")

	// Decompress using zstd CLI. Install it first if missing (apt-get on RBE workers).
	if _, err := exec.LookPath("zstd"); err != nil {
		t.Log("installing zstd...")
		cmd := exec.Command("bash", "-c", "apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq zstd >/dev/null 2>&1")
		if err := cmd.Run(); err != nil {
			t.Fatalf("install zstd: %v", err)
		}
	}
	h.RunCmd(t, "zstd", "-d", "-f", "-o", rawPath, zstPath)

	t.Logf("decompressed Talos image to %s", rawPath)
	return rawPath
}

// BootTalosRawVM starts a Talos QEMU VM from a raw disk image with CIDATA.
// Similar to h.BootTalosVM but uses format=raw instead of qcow2.
func BootTalosRawVM(t *testing.T, name, baseImage, cidataPath string, mgmtPort int, netArgs []string) *h.VM {
	t.Helper()

	args := []string{
		"-drive", fmt.Sprintf("file=%s,if=virtio,format=raw,snapshot=on", baseImage),
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
		args = append(args, h.MgmtNIC(mgmtPort, 50000, "52:54:00:ab:00:01")...)
	}

	return h.StartVM(t, name, exec.Command("qemu-system-x86_64", args...))
}
