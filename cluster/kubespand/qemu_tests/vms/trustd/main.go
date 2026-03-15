// Binary trustd is the PID-1 init for the trustd CSR flow test VM.
// Starts kubespand (with ca_crt + token for trustd) and apid, then idles.
// The test observes the result from outside via the Talos API on port 50000.
package main

import (
	"encoding/base64"
	"fmt"
	"os"
	"os/exec"

	qemu_tests "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vms/initlib"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vms/kubespanlib"
)

func main() {
	initlib.InitBasic()
	params := initlib.ParseCmdline()

	clusterID := params["cluster_id"]
	sharedSecret := params["shared_secret"]
	discoveryAddr := params["discovery"]
	caCrtB64 := params["ca_crt"]
	token := params["token"]
	clusterEndpoint := params["cluster_endpoint"]

	if clusterID == "" || sharedSecret == "" || discoveryAddr == "" || caCrtB64 == "" || token == "" || clusterEndpoint == "" {
		initlib.EmitEvent(qemu_tests.Event{
			Type:    qemu_tests.EventError,
			Message: "missing required kernel cmdline params",
			Error:   fmt.Sprintf("cluster_id=%s discovery=%s ca_crt_len=%d token=%s endpoint=%s", clusterID, discoveryAddr, len(caCrtB64), token, clusterEndpoint),
		})
		initlib.Poweroff()
	}

	caCrtPEM, err := base64.StdEncoding.DecodeString(caCrtB64)
	if err != nil {
		initlib.EmitEvent(qemu_tests.Event{Type: qemu_tests.EventError, Message: "ca_crt base64 decode failed", Error: err.Error()})
		initlib.Poweroff()
	}

	kubespanlib.LoadModules()

	// eth0: L2 segment (mcast NIC) for KubeSpan mesh.
	kubespanlib.ConfigureNetwork("192.168.50.1", "24")

	// eth1: mgmt NIC (QEMU user-mode) for port forwarding apid to the test host.
	initlib.WaitForInterface("eth1")
	initlib.MustRun("ip", "link", "set", "eth1", "up")
	initlib.MustRun("ip", "addr", "add", "10.0.2.15/24", "dev", "eth1")

	cfg := kubespanlib.KubespandConfig{
		ClusterID:       clusterID,
		SharedSecret:    sharedSecret,
		DiscoveryAddr:   discoveryAddr,
		ListenPort:      51820,
		EndpointFilters: []string{"192.168.50.0/24"},
		ClusterEndpoint: clusterEndpoint,
		CACrt:           string(caCrtPEM),
		Token:           token,
	}
	kubespanlib.StartKubespand(cfg)

	// Start apid — serves mTLS on :50000 once secrets.API appears in COSI state.
	logFile, _ := os.Create("/tmp/apid.log")
	apidCmd := exec.Command("/apid")
	apidCmd.Stdout = logFile
	apidCmd.Stderr = logFile
	if err := apidCmd.Start(); err != nil {
		initlib.EmitEvent(qemu_tests.Event{Type: qemu_tests.EventError, Message: "apid failed to start", Error: err.Error()})
		initlib.Poweroff()
	}
	initlib.EmitEvent(qemu_tests.Event{Type: qemu_tests.EventKubespand, Message: fmt.Sprintf("apid started pid=%d", apidCmd.Process.Pid)})

	// Idle forever — test observes via Talos API from outside.
	select {}
}
