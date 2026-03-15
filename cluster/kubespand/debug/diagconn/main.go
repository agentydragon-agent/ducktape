// diagconn tests gRPC connectivity to discovery.talos.dev.
// Run with: bazel run //cluster/kubespand/debug/diagconn
package main

import (
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"os"
	"time"

	"github.com/siderolabs/talos/pkg/machinery/client/dialer"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/keepalive"
)

func testGRPC(name, target string, opts []grpc.DialOption) {
	fmt.Printf("\n=== %s (target=%q) ===\n", name, target)
	start := time.Now()
	grpcConn, err := grpc.NewClient(target, opts...)
	if err != nil {
		fmt.Printf("NewClient FAIL: %v\n", err)
		return
	}
	defer grpcConn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	grpcConn.Connect()
	for {
		state := grpcConn.GetState()
		fmt.Printf("  state=%v (elapsed %v)\n", state, time.Since(start))
		if state == 2 { // READY
			fmt.Println("OK: gRPC connection READY")
			break
		}
		if ctx.Err() != nil {
			fmt.Printf("FAIL: timeout (state=%v, took %v)\n", state, time.Since(start))
			break
		}
		if !grpcConn.WaitForStateChange(ctx, state) {
			fmt.Printf("FAIL: context cancelled (state=%v, took %v)\n", state, time.Since(start))
			break
		}
	}
}

func main() {
	endpoint := "discovery.talos.dev:443"

	// Test 1: Go stdlib DNS resolution
	fmt.Println("=== Test 1: net.LookupHost ===")
	start := time.Now()
	addrs, err := net.LookupHost("discovery.talos.dev")
	if err != nil {
		fmt.Printf("FAIL: %v (took %v)\n", err, time.Since(start))
	} else {
		fmt.Printf("OK: resolved to %v (took %v)\n", addrs, time.Since(start))
	}

	// Test 2: net.DefaultResolver.LookupHost (what gRPC uses)
	fmt.Println("\n=== Test 2: net.DefaultResolver.LookupHost ===")
	start = time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	addrs, err = net.DefaultResolver.LookupHost(ctx, "discovery.talos.dev")
	cancel()
	if err != nil {
		fmt.Printf("FAIL: %v (took %v)\n", err, time.Since(start))
	} else {
		fmt.Printf("OK: resolved to %v (took %v)\n", addrs, time.Since(start))
	}

	// Test 3: TCP connectivity
	fmt.Println("\n=== Test 3: net.DialTimeout TCP ===")
	start = time.Now()
	conn, err := net.DialTimeout("tcp", endpoint, 5*time.Second)
	if err != nil {
		fmt.Printf("FAIL: %v (took %v)\n", err, time.Since(start))
	} else {
		fmt.Printf("OK: connected to %v (took %v)\n", conn.RemoteAddr(), time.Since(start))
		conn.Close()
	}

	// Test 4: DynamicProxyDialer
	fmt.Println("\n=== Test 4: DynamicProxyDialerWithTLSConfig ===")
	tlsConfigFunc := func() *tls.Config {
		return &tls.Config{MinVersion: tls.VersionTLS12}
	}
	dialerFn := dialer.DynamicProxyDialerWithTLSConfig(tlsConfigFunc)
	ctx, cancel = context.WithTimeout(context.Background(), 5*time.Second)
	start = time.Now()
	conn, err = dialerFn(ctx, endpoint)
	cancel()
	if err != nil {
		fmt.Printf("FAIL: %v (took %v)\n", err, time.Since(start))
	} else {
		fmt.Printf("OK: connected to %v (took %v)\n", conn.RemoteAddr(), time.Since(start))
		conn.Close()
	}

	// Test 5: Check /etc/resolv.conf
	fmt.Println("\n=== Test 5: /etc/resolv.conf ===")
	data, err := os.ReadFile("/etc/resolv.conf")
	if err != nil {
		fmt.Printf("FAIL: %v\n", err)
	} else {
		fmt.Printf("%s", data)
	}

	// Test 6: SRV lookup (gRPC dns resolver may do this)
	fmt.Println("\n=== Test 6: net.LookupSRV for grpcs ===")
	start = time.Now()
	_, srvs, err := net.LookupSRV("grpcs", "tcp", "discovery.talos.dev")
	if err != nil {
		fmt.Printf("No SRV: %v (took %v)\n", err, time.Since(start))
	} else {
		for _, srv := range srvs {
			fmt.Printf("SRV: %v:%v (took %v)\n", srv.Target, srv.Port, time.Since(start))
		}
	}

	// gRPC tests with different target formats
	tlsConfig := &tls.Config{MinVersion: tls.VersionTLS12}
	baseOpts := []grpc.DialOption{
		grpc.WithKeepaliveParams(keepalive.ClientParameters{Time: 10 * time.Second}),
		grpc.WithTransportCredentials(credentials.NewTLS(tlsConfig)),
		grpc.WithContextDialer(dialer.DynamicProxyDialerWithTLSConfig(tlsConfigFunc)),
	}

	// Test 7: gRPC with hostname (default dns resolver)
	testGRPC("Test 7: gRPC hostname", endpoint, baseOpts)

	// Test 8: gRPC with explicit dns:/// scheme
	testGRPC("Test 8: gRPC dns:///", "dns:///"+endpoint, baseOpts)

	// Test 9: gRPC with passthrough:/// scheme (bypass gRPC DNS)
	testGRPC("Test 9: gRPC passthrough:///", "passthrough:///"+endpoint, baseOpts)

	// Test 10: gRPC with direct IPv4 address
	if len(addrs) > 0 {
		for _, a := range addrs {
			ip := net.ParseIP(a)
			if ip != nil && ip.To4() != nil {
				testGRPC("Test 10: gRPC direct IPv4", a+":443", baseOpts)
				break
			}
		}
	}

	// Test 11: gRPC without custom dialer (use gRPC default)
	optsNoDialer := []grpc.DialOption{
		grpc.WithKeepaliveParams(keepalive.ClientParameters{Time: 10 * time.Second}),
		grpc.WithTransportCredentials(credentials.NewTLS(tlsConfig)),
	}
	testGRPC("Test 11: gRPC no custom dialer", endpoint, optsNoDialer)
}
