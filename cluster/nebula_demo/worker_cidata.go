// CIDATA helpers for the Alpine worker VM.
// Creates a FAT32 disk image containing Nebula certs/config and Kubernetes
// bootstrap credentials, mounted by the worker init at /dev/vda.
package nebula_demo

import (
	"os"
	"path/filepath"
	"testing"

	h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
)

// WorkerCIDATAFiles holds all files to include in the worker CIDATA image.
type WorkerCIDATAFiles struct {
	NebulaCACrt         string
	NebulaHostCrt       string
	NebulaHostKey       string
	NebulaConfigYAML    string
	K8sCACrt            string
	BootstrapKubeconfig string
}

// CreateWorkerCIDATA creates a FAT32 CIDATA disk image for the Alpine worker VM.
func CreateWorkerCIDATA(t *testing.T, tmpDir, name string, files WorkerCIDATAFiles) string {
	t.Helper()

	ciDir := filepath.Join(tmpDir, "worker-cidata-"+name)
	os.MkdirAll(ciDir, 0o755)

	writeFile(t, ciDir, "nebula-ca.crt", files.NebulaCACrt)
	writeFile(t, ciDir, "nebula-host.crt", files.NebulaHostCrt)
	writeFile(t, ciDir, "nebula-host.key", files.NebulaHostKey)
	writeFile(t, ciDir, "nebula-config.yaml", files.NebulaConfigYAML)
	writeFile(t, ciDir, "ca.crt", files.K8sCACrt)
	writeFile(t, ciDir, "bootstrap-kubelet.conf", files.BootstrapKubeconfig)

	imgPath := filepath.Join(tmpDir, "worker-cidata-"+name+".img")
	h.RunCmd(t, "dd", "if=/dev/zero", "of="+imgPath, "bs=1M", "count=4")
	h.RunCmd(t, "/usr/sbin/mkfs.vfat", "-n", "CIDATA", imgPath)

	for _, fname := range []string{
		"nebula-ca.crt", "nebula-host.crt", "nebula-host.key",
		"nebula-config.yaml", "ca.crt", "bootstrap-kubelet.conf",
	} {
		h.RunCmd(t, "/usr/bin/mcopy", "-i", imgPath, filepath.Join(ciDir, fname), "::")
	}

	t.Logf("created worker CIDATA for %s: %s", name, imgPath)
	return imgPath
}

func writeFile(t *testing.T, dir, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
}

// WorkerInitramfsPath is the runfile path for the Alpine worker initramfs.
const WorkerInitramfsPath = "cluster/nebula_demo/vms/worker/initramfs.cpio.gz"
