// Binary kubespan is the PID-1 init for KubeSpan test VMs.
// Handles flat and cross_subnet topologies.
// Kubespand agent config is provided via a CIDATA virtio drive.
package main

import (
	"log"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vms/initlib"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vms/kubespanlib"
)

func main() {
	params := initlib.Init()

	linkIP := params["link_ip"]
	if linkIP == "" {
		log.Fatalf("missing link_ip kernel parameter")
	}

	log.Printf("kubespan mode, role=%s, link_ip=%s", initlib.Role, linkIP)

	kubespanlib.LoadModules()
	kubespanlib.ConfigureNetwork(linkIP, "24")

	// mgmt NIC (QEMU user-mode) for port forwarding to the test host.
	initlib.ConfigureMgmtNIC(false)

	log.Printf("network ready: link=%s/24", linkIP)

	kubespanlib.RunKubespandAndIdle(9999)
}
