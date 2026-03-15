// Binary apid is the Talos API proxy daemon.
//
// Wraps the upstream Talos apid entry point for use with kubespand.
// Listens on port 50000 with mTLS and proxies gRPC calls to the
// machined Unix socket at /system/run/machined/machine.sock.
package main

import apid "github.com/siderolabs/talos/internal/app/apid"

func main() {
	apid.Main()
}
