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
