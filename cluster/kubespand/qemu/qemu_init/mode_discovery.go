package main

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"time"

	"github.com/agentydragon/ducktape/cluster/kubespand/qemu"
)

func modeDiscovery(params map[string]string) {
	discoveryIP := params["discovery_ip"]
	if discoveryIP == "" {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "missing discovery_ip", Error: "discovery_ip parameter required"})
		poweroff()
	}

	emitEvent(qemu.Event{Type: qemu.EventBoot, Message: fmt.Sprintf("discovery mode, ip=%s", discoveryIP)})

	runSilent("modprobe", "virtio_net")

	// Configure eth0.
	waitForInterface("eth0")
	mustRun("ip", "link", "set", "lo", "up")
	mustRun("ip", "link", "set", "eth0", "up")
	mustRun("ip", "addr", "add", discoveryIP, "dev", "eth0")

	emitEvent(qemu.Event{Type: qemu.EventNetwork, Message: fmt.Sprintf("network ready, ip=%s", discoveryIP)})

	// Start discovery service.
	logFile, _ := os.Create("/tmp/discovery-service.log")
	discCmd := exec.Command("/discovery-service", "-debug")
	discCmd.Stdout = logFile
	discCmd.Stderr = logFile
	if err := discCmd.Start(); err != nil {
		emitEvent(qemu.Event{Type: qemu.EventError, Message: "discovery-service failed to start", Error: err.Error()})
		poweroff()
	}
	emitEvent(qemu.Event{Type: qemu.EventKubespand, Message: fmt.Sprintf("discovery-service started pid=%d", discCmd.Process.Pid)})

	// Poll until ready.
	for i := 0; i < 60; i++ {
		resp, err := http.Get("http://127.0.0.1:3000/")
		if err == nil {
			resp.Body.Close()
			break
		}
		time.Sleep(500 * time.Millisecond)
	}

	emitEvent(qemu.Event{Type: qemu.EventDone, Message: "discovery-service running"})

	// Sleep forever (discovery service stays up until killed).
	select {}
}
