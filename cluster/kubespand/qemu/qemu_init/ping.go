package main

import (
	"fmt"
	"net"
	"os"
	"time"

	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv4"
	"golang.org/x/net/ipv6"
)

// tcpProbe attempts a TCP connection to target:port with retry until timeout.
// Returns true on first successful connection.
func tcpProbe(target string, port int, timeout time.Duration) bool {
	addr := net.JoinHostPort(target, fmt.Sprintf("%d", port))
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		conn, err := net.DialTimeout("tcp", addr, 3*time.Second)
		if err == nil {
			conn.Close()
			fmt.Printf("tcp connect %s succeeded\n", addr)
			return true
		}
		time.Sleep(time.Second)
	}

	fmt.Fprintf(os.Stderr, "timeout after %s: no TCP connection to %s\n", timeout, addr)
	return false
}

// serveTCP starts a TCP listener on the given port that accepts connections
// and immediately closes them (for probe testing). Runs until the returned
// cancel function is called.
// serveTCP starts TCP listeners on the given port on both IPv4 and IPv6.
// Accepts connections and immediately closes them (for probe testing).
// Runs until the returned cancel function is called.
func serveTCP(port int) (cancel func()) {
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

// probe sends ICMP echo requests to the target address with retry until
// timeout. Auto-detects IPv4 vs IPv6 from the target. Returns true on
// first successful echo reply.
func probe(target string, timeout time.Duration) bool {
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
			return true
		}
		time.Sleep(time.Second)
	}

	fmt.Fprintf(os.Stderr, "timeout after %s: no ICMP echo reply from %s\n", timeout, target)
	return false
}

// ping4 sends a single ICMPv4 echo request and waits up to 3s for a reply.
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
		Type: ipv4.ICMPTypeEcho,
		Code: 0,
		Body: &icmp.Echo{
			ID:   os.Getpid() & 0xffff,
			Seq:  seq,
			Data: []byte("kubespan-probe"),
		},
	}
	wb, err := msg.Marshal(nil)
	if err != nil {
		return false
	}

	dst, err := net.ResolveIPAddr("ip4", target)
	if err != nil {
		fmt.Fprintf(os.Stderr, "resolve %s: %v\n", target, err)
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

	rm, err := icmp.ParseMessage(1, rb[:n]) // 1 = ICMPv4 protocol number
	if err != nil {
		return false
	}

	return rm.Type == ipv4.ICMPTypeEchoReply
}

// ping6 sends a single ICMPv6 echo request and waits up to 3s for a reply.
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
		Type: ipv6.ICMPTypeEchoRequest,
		Code: 0,
		Body: &icmp.Echo{
			ID:   os.Getpid() & 0xffff,
			Seq:  seq,
			Data: []byte("kubespan-probe"),
		},
	}
	wb, err := msg.Marshal(nil)
	if err != nil {
		return false
	}

	dst, err := net.ResolveIPAddr("ip6", target)
	if err != nil {
		fmt.Fprintf(os.Stderr, "resolve %s: %v\n", target, err)
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

	rm, err := icmp.ParseMessage(58, rb[:n]) // 58 = ICMPv6 protocol number
	if err != nil {
		return false
	}

	return rm.Type == ipv6.ICMPTypeEchoReply
}
