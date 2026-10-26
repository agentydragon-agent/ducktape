package runner

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
)

func TestExecutorProbeRequiresValidRPCAndBoundsUnresponsiveServer(t *testing.T) {
	for _, test := range []struct {
		name, response string
		success        bool
	}{
		{"healthy", `{"id":1,"result":{"sessionId":"test-session"}}`, true},
		{"RPC error", `{"id":1,"error":{"code":-32603,"message":"unavailable"}}`, false},
		{"wrong request", `{"id":2,"result":{"sessionId":"test-session"}}`, false},
		{"stalled dispatcher", "", false},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				c, err := websocket.Accept(w, r, nil)
				if err != nil {
					return
				}
				defer c.CloseNow()
				ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
				defer cancel()
				if _, _, err := c.Read(ctx); err != nil {
					return
				}
				if test.response != "" {
					_ = c.Write(ctx, websocket.MessageText, []byte(test.response))
				}
				if test.success {
					if _, _, err := c.Read(ctx); err != nil {
						return
					}
					if _, _, err := c.Read(ctx); err != nil {
						return
					}
					_ = c.Write(ctx, websocket.MessageText, []byte(`{"id":2,"result":{"status":"ready"}}`))
				}
				_, _, _ = c.Read(ctx)
			}))
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			err := probeExecutor(ctx, "ws"+strings.TrimPrefix(server.URL, "http"))
			if (err == nil) != test.success {
				t.Fatalf("probe = %v, success=%t", err, test.success)
			}
		})
	}
}

func TestExecutorConfigurationRejectsPartialOrOverlappingIsolation(t *testing.T) {
	for _, endpoint := range []string{"", "ws://0.0.0.0:4501", "ws://127.0.0.1:0", "wss://127.0.0.1:4501", "ws://127.0.0.1:4501/path", "ws://user@127.0.0.1:4501"} {
		if err := validateExecutorURL(endpoint); err == nil {
			t.Fatalf("accepted %q", endpoint)
		}
	}
	const endpoint = "ws://127.0.0.1:4501"
	if err := (CodexExecutorConfig{URL: endpoint, ContainerSocket: "/run/test-executor.sock"}).validate(nil); err != nil {
		t.Fatal(err)
	}
	harness := &AgentCgroups{Root: "/test-cgroups/workloads"}
	if err := (CodexExecutorConfig{URL: endpoint, Isolation: &AgentCgroups{Root: "/test-cgroups/executors"}}).validate(harness); err != nil {
		t.Fatal(err)
	}
	for _, config := range []CodexExecutorConfig{
		{URL: endpoint},
		{URL: endpoint, ContainerSocket: "relative"},
		{URL: endpoint, ContainerSocket: "/run/test.sock", Isolation: harness},
		{URL: endpoint, Isolation: harness},
		{URL: endpoint, Isolation: &AgentCgroups{Root: "/test-cgroups/workloads/executor"}},
	} {
		if err := config.validate(harness); err == nil {
			t.Fatalf("accepted %+v", config)
		}
	}
}

func TestStoppedExecutorCannotStart(t *testing.T) {
	e := newCodexExecutor(nil, CodexExecutorConfig{})
	if err := e.stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := e.ensure(context.Background()); err == nil {
		t.Fatal("stopped executor restarted")
	}
	if err := e.stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := monitorExecutor(ctx, "", make(chan error)); !errors.Is(err, context.Canceled) {
		t.Fatalf("monitor: %v", err)
	}
}
