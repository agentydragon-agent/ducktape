package runner

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"testing/synctest"
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
	limits := ResourceLimits{CPUQuotaMicros: 100000, MemoryMaxBytes: 64 * 1024 * 1024, PidsMax: 32, ReadBPS: 1, WriteBPS: 1, ReadIOPS: 1, WriteIOPS: 1}
	harness := &AgentCgroups{Root: "/test-cgroups/workloads", AggregateLimits: limits, ProcessLimits: limits}
	executor := *harness
	executor.Root = "/test-cgroups/executors"
	if err := (CodexExecutorConfig{URL: endpoint, Isolation: &executor}).validate(harness); err != nil {
		t.Fatal(err)
	}
	invalid := executor
	invalid.ProcessLimits.MemoryMaxBytes++
	for _, config := range []CodexExecutorConfig{
		{URL: endpoint},
		{URL: endpoint, ContainerSocket: "relative"},
		{URL: endpoint, ContainerSocket: "/run/test.sock", Isolation: harness},
		{URL: endpoint, Isolation: harness},
		{URL: endpoint, Isolation: &AgentCgroups{Root: "/test-cgroups/workloads/executor"}},
		{URL: endpoint, Isolation: &invalid},
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

func TestExecutorMonitorToleratesTransientProbesAndResetsFailures(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		results := []error{context.DeadlineExceeded, context.DeadlineExceeded, nil, context.DeadlineExceeded, context.DeadlineExceeded, nil}
		calls := 0
		finished := make(chan error, 1)
		go func() {
			finished <- monitorExecutorHealth(ctx, make(chan error), func(context.Context) error {
				result := results[calls]
				calls++
				return result
			})
		}()
		synctest.Wait()
		for range results {
			time.Sleep(5 * time.Second)
			synctest.Wait()
			select {
			case err := <-finished:
				t.Fatalf("fenced a transient failure: %v", err)
			default:
			}
		}
		if calls != len(results) {
			t.Fatalf("probed %d times, want %d", calls, len(results))
		}
		cancel()
		if err := <-finished; !errors.Is(err, context.Canceled) {
			t.Fatalf("monitor cancellation: %v", err)
		}
	})
}

func TestExecutorMonitorFencesPersistentFailure(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
		defer cancel()
		calls := 0
		err := monitorExecutorHealth(ctx, make(chan error), func(ctx context.Context) error {
			calls++
			<-ctx.Done()
			return ctx.Err()
		})
		if !errors.Is(err, context.DeadlineExceeded) || calls != 3 {
			t.Fatalf("monitor: calls=%d error=%v, want three failed bounded probes", calls, err)
		}
	})
}

func TestExecutorMonitorDoesNotDelayProcessExitForProbeGrace(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		done := make(chan error, 1)
		finished := make(chan error, 1)
		calls := 0
		go func() {
			finished <- monitorExecutorHealth(ctx, done, func(context.Context) error {
				calls++
				return context.DeadlineExceeded
			})
		}()
		synctest.Wait()
		time.Sleep(5 * time.Second)
		synctest.Wait()
		exited := errors.New("test executor exited")
		done <- exited
		if err := <-finished; !errors.Is(err, exited) || calls != 1 {
			t.Fatalf("monitor: calls=%d error=%v, want immediate process exit", calls, err)
		}
	})
}

// A companion whose Codex binary cannot start serves a refusal instead of exiting: a generation that
// spawned nothing has no work to fence, and a container restarting into the same failure would leave
// no socket to fence and a Runner able neither to run Codex nor to quiesce.
func TestExecutorCompanionRefusesClaimAndKeepsServing(t *testing.T) {
	dir := t.TempDir()
	socket := filepath.Join(dir, "control.sock")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	served := make(chan error, 1)
	go func() {
		served <- serveExecutorContainer(ctx, socket, filepath.Join(dir, "absent-codex"), "ws://127.0.0.1:4501")
	}()
	waitForSocket(t, socket)

	for attempt := 1; attempt <= 2; attempt++ {
		_, err := claimExecutorContainer(ctx, socket, map[string]string{"PATH": "/usr/bin"})
		var refusal executorRefusal
		if !errors.As(err, &refusal) {
			t.Fatalf("claim %d: %v (%T), want an executorRefusal", attempt, err, err)
		}
		if !strings.Contains(err.Error(), "absent-codex") {
			t.Errorf("claim %d: %q, want the companion's reason", attempt, err)
		}
	}

	// The generation survived both refusals: an idle companion still answers, unowned and unchanged.
	_, status, err := executorControl(ctx, socket, executorControlRequest{Operation: "inspect"})
	if err != nil {
		t.Fatalf("inspect after refusals: %v", err)
	}
	if status.Owned || status.Error != "" {
		t.Errorf("inspect after refusals = %+v, want an unowned generation reporting no error", status)
	}
	cancel()
	if err := <-served; err != nil {
		t.Fatalf("companion after cancellation: %v", err)
	}
}

// A refusal must reach a waiting Session as itself, not as the expiry of its startup deadline: the
// companion will refuse every later claim the same way, so nothing is recovered by waiting.
func TestExecutorEnsureReportsRefusalInsteadOfItsDeadline(t *testing.T) {
	dir := t.TempDir()
	socket := filepath.Join(dir, "control.sock")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() {
		_ = serveExecutorContainer(ctx, socket, filepath.Join(dir, "absent-codex"), "ws://127.0.0.1:4599")
	}()
	waitForSocket(t, socket)

	e := newCodexExecutor(&Runner{ctx: ctx}, CodexExecutorConfig{URL: "ws://127.0.0.1:4599", ContainerSocket: socket})
	startup, cancelStartup := context.WithTimeout(ctx, time.Minute)
	defer cancelStartup()
	started := time.Now()
	err := e.ensure(startup)
	var refusal executorRefusal
	if !errors.As(err, &refusal) {
		t.Fatalf("ensure: %v (%T), want an executorRefusal", err, err)
	}
	if elapsed := time.Since(started); elapsed > 10*time.Second {
		t.Errorf("ensure took %v to report a refusal, want it reported without waiting for the deadline", elapsed)
	}
	if err := e.stop(context.Background()); err != nil {
		t.Fatalf("stop after refusal: %v", err)
	}
}

func waitForSocket(t *testing.T, path string) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for {
		if _, err := os.Stat(path); err == nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("no companion socket at %s", path)
		}
		time.Sleep(10 * time.Millisecond)
	}
}
