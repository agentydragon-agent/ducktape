package kubespanlib

import (
	"fmt"
	"net"
	"os"
	"sync"
	"time"

	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv4"
	"golang.org/x/net/ipv6"

	qemu_tests "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vms/initlib"
)

// probeResult holds the outcome of a single probe for deferred event emission.
type probeResult struct {
	name   string
	target string
	ok     bool
}

// icmpProbe sends ICMP echo requests to the target with retry until timeout.
func icmpProbe(name, target string, timeout time.Duration) probeResult {
	deadline := time.Now().Add(timeout)
	seq := 0

	ip := net.ParseIP(target)
	isV4 := ip != nil && ip.To4() != nil

	for time.Now().Before(deadline) {
		seq++
		var ok bool
		if isV4 {
			ok = ping4(target, seq)
		} else {
			ok = ping6(target, seq)
		}
		if ok {
			fmt.Printf("ping %s succeeded (seq %d)\n", target, seq)
			return probeResult{name, target, true}
		}
		time.Sleep(200 * time.Millisecond)
	}

	fmt.Fprintf(os.Stderr, "timeout after %s: no ICMP echo reply from %s\n", timeout, target)
	return probeResult{name, target, false}
}

// tcpProbe attempts a TCP connection to target:port with retry until timeout.
func tcpProbe(name, target string, port int, timeout time.Duration) probeResult {
	addr := net.JoinHostPort(target, fmt.Sprintf("%d", port))
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		conn, err := net.DialTimeout("tcp", addr, 3*time.Second)
		if err == nil {
			conn.Close()
			fmt.Printf("tcp connect %s succeeded\n", addr)
			return probeResult{name, addr, true}
		}
		time.Sleep(200 * time.Millisecond)
	}

	fmt.Fprintf(os.Stderr, "timeout after %s: no TCP connection to %s\n", timeout, addr)
	return probeResult{name, addr, false}
}

// ServeTCP starts TCP listeners on the given port on both IPv4 and IPv6.
func ServeTCP(port int) (cancel func()) {
	addr := fmt.Sprintf(":%d", port)
	var listeners []net.Listener
	for _, network := range []string{"tcp4", "tcp6"} {
		ln, err := net.Listen(network, addr)
		if err != nil {
			fmt.Fprintf(os.Stderr, "serveTCP %s: %v\n", network, err)
			continue
		}
		listeners = append(listeners, ln)
		go func(l net.Listener) {
			for {
				conn, err := l.Accept()
				if err != nil {
					return
				}
				conn.Close()
			}
		}(ln)
	}
	return func() {
		for _, ln := range listeners {
			ln.Close()
		}
	}
}

func ping4(target string, seq int) bool {
	conn, err := icmp.ListenPacket("ip4:icmp", "0.0.0.0")
	if err != nil {
		fmt.Fprintf(os.Stderr, "listen: %v\n", err)
		return false
	}
	defer conn.Close()

	if err := conn.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		return false
	}

	msg := icmp.Message{
		Type: ipv4.ICMPTypeEcho, Code: 0,
		Body: &icmp.Echo{ID: os.Getpid() & 0xffff, Seq: seq, Data: []byte("kubespan-probe")},
	}
	wb, err := msg.Marshal(nil)
	if err != nil {
		return false
	}

	dst, err := net.ResolveIPAddr("ip4", target)
	if err != nil {
		return false
	}
	if _, err := conn.WriteTo(wb, dst); err != nil {
		return false
	}

	rb := make([]byte, 1500)
	n, _, err := conn.ReadFrom(rb)
	if err != nil {
		return false
	}
	rm, err := icmp.ParseMessage(1, rb[:n])
	if err != nil {
		return false
	}
	return rm.Type == ipv4.ICMPTypeEchoReply
}

func ping6(target string, seq int) bool {
	conn, err := icmp.ListenPacket("ip6:ipv6-icmp", "::")
	if err != nil {
		fmt.Fprintf(os.Stderr, "listen: %v\n", err)
		return false
	}
	defer conn.Close()

	if err := conn.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		return false
	}

	msg := icmp.Message{
		Type: ipv6.ICMPTypeEchoRequest, Code: 0,
		Body: &icmp.Echo{ID: os.Getpid() & 0xffff, Seq: seq, Data: []byte("kubespan-probe")},
	}
	wb, err := msg.Marshal(nil)
	if err != nil {
		return false
	}

	dst, err := net.ResolveIPAddr("ip6", target)
	if err != nil {
		return false
	}
	if _, err := conn.WriteTo(wb, dst); err != nil {
		return false
	}

	rb := make([]byte, 1500)
	n, _, err := conn.ReadFrom(rb)
	if err != nil {
		return false
	}
	rm, err := icmp.ParseMessage(58, rb[:n])
	if err != nil {
		return false
	}
	return rm.Type == ipv6.ICMPTypeEchoReply
}

// emitProbeResult emits a probe event and dumps kubespand log on failure.
func emitProbeResult(r probeResult) {
	evt := qemu_tests.Event{Type: qemu_tests.EventProbe, Message: r.name, Target: r.target, Success: &r.ok}
	if !r.ok {
		evt.Error = "probe failed"
		initlib.DumpLog("/tmp/kubespand.log")
	}
	initlib.EmitEvent(evt)
}

// runProbesParallel runs all probes concurrently and emits events after all complete.
func runProbesParallel(probes []func() probeResult) {
	results := make([]probeResult, len(probes))
	var wg sync.WaitGroup
	wg.Add(len(probes))
	for i, fn := range probes {
		go func(idx int, f func() probeResult) {
			defer wg.Done()
			results[idx] = f()
		}(i, fn)
	}
	wg.Wait()
	for _, r := range results {
		emitProbeResult(r)
	}
}

// RunProbes runs the standard 2-node probe suite (IPv6 ULA + IPv4 bridge, ICMP + TCP).
func RunProbes(peerAddr, peerBridgeIP string, tcpPort int) {
	runProbesParallel([]func() probeResult{
		func() probeResult { return icmpProbe(qemu_tests.ProbeIPv6ULAICMP, peerAddr, 60*time.Second) },
		func() probeResult { return icmpProbe(qemu_tests.ProbeIPv4Eth0ICMP, peerBridgeIP, 60*time.Second) },
		func() probeResult { return tcpProbe(qemu_tests.ProbeIPv6ULATCP, peerAddr, tcpPort, 30*time.Second) },
		func() probeResult {
			return tcpProbe(qemu_tests.ProbeIPv4Eth0TCP, peerBridgeIP, tcpPort, 30*time.Second)
		},
	})
}

// RunDoubleNATProbes probes each peer's ULA via ICMP and TCP.
func RunDoubleNATProbes(peerAddrs []string, tcpPort int) {
	var probes []func() probeResult
	for i, addr := range peerAddrs {
		addr := addr
		icmpName := fmt.Sprintf(qemu_tests.ProbePeerULAICMPFmt, i+1)
		tcpName := fmt.Sprintf(qemu_tests.ProbePeerULATCPFmt, i+1)
		probes = append(probes, func() probeResult { return icmpProbe(icmpName, addr, 60*time.Second) })
		probes = append(probes, func() probeResult { return tcpProbe(tcpName, addr, tcpPort, 30*time.Second) })
	}
	runProbesParallel(probes)
}
