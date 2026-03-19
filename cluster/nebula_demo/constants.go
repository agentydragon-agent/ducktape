// Network topology constants for the Nebula double NAT demo.
// Reuses the same physical topology as the KubeSpan doublenat test
// (cluster/kubespand/qemu_tests/doublenat_topology.go) but adds
// Nebula overlay IP assignments.
package nebula_demo

import h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"

// Physical topology constants — delegated to the existing qemu_tests package.
const (
	VPSIP = h.DoubleNATVPSIP // 192.168.50.2

	NAT1IP      = h.DoubleNATNAT1IP      // 192.168.60.2
	NAT1Gateway = h.DoubleNATNAT1Gateway // 192.168.60.1

	NAT2IP      = h.DoubleNATNAT2IP      // 192.168.70.2
	NAT2Gateway = h.DoubleNATNAT2Gateway // 192.168.70.1
)

// Nebula overlay IP assignments.
const (
	NebulaVPSIP  = "10.42.0.1"
	NebulaNAT1IP = "10.42.0.10"
	NebulaNAT2IP = "10.42.0.20"
)

// Runfile paths.
const (
	TalosNebulaImagePath = "cluster/nebula_demo/talos/nocloud-amd64.qcow2"
)
