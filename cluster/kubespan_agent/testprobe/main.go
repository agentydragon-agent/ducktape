// Binary testprobe sends ICMPv6 echo requests to verify KubeSpan tunnel connectivity.
// It retries until a response is received or the timeout expires.
package main

import (
	"flag"
	"fmt"
	"net"
	"os"
	"time"

	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv6"
)

func main() {
	timeout := flag.Duration("timeout", 30*time.Second, "overall timeout for probe")
	flag.Parse()

	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: testprobe [-timeout duration] <ipv6-address>")
		os.Exit(2)
	}

	target := flag.Arg(0)
	deadline := time.Now().Add(*timeout)
	seq := 0

	for time.Now().Before(deadline) {
		seq++
		if ping6(target, seq) {
			fmt.Printf("ping %s succeeded (seq %d)\n", target, seq)
			os.Exit(0)
		}
		time.Sleep(time.Second)
	}

	fmt.Fprintf(os.Stderr, "timeout after %s: no ICMPv6 echo reply from %s\n", *timeout, target)
	os.Exit(1)
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
