package main

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/cosi-project/runtime/pkg/controller"
	controllerruntime "github.com/cosi-project/runtime/pkg/controller/runtime"
	"github.com/cosi-project/runtime/pkg/safe"
	"github.com/cosi-project/runtime/pkg/state"
	"github.com/cosi-project/runtime/pkg/state/impl/inmem"
	"github.com/cosi-project/runtime/pkg/state/impl/namespaced"
	"github.com/siderolabs/talos/pkg/machinery/resources/kubespan"
	"go.uber.org/zap"
	"go.uber.org/zap/zaptest"
)

// configReaderController is a minimal controller that watches Config (InputWeak)
// and signals when it successfully reads the Config resource.
type configReaderController struct {
	configSeen chan struct{}
}

func (ctrl *configReaderController) Name() string {
	return "test.ConfigReaderController"
}

func (ctrl *configReaderController) Inputs() []controller.Input {
	return []controller.Input{
		safe.Input[*kubespan.Config](controller.InputWeak),
	}
}

func (ctrl *configReaderController) Outputs() []controller.Output {
	return nil
}

func (ctrl *configReaderController) Run(ctx context.Context, r controller.Runtime, logger *zap.Logger) error {
	logger.Info("reader controller started, waiting for events")

	eventCount := 0
	for {
		select {
		case <-ctx.Done():
			logger.Info("reader controller context cancelled", zap.Int("total_events", eventCount))
			return nil
		case <-r.EventCh():
		}

		eventCount++
		logger.Info("reader controller received event", zap.Int("event_number", eventCount))

		cfg, err := safe.ReaderGetByID[*kubespan.Config](ctx, r, kubespan.ConfigID)
		if err != nil {
			if state.IsNotFoundError(err) {
				logger.Info("config not found via reader, trying direct state read")
				// Try reading directly from state to see if the resource exists
				// in the underlying state but isn't visible through the controller runtime
				continue
			}
			return fmt.Errorf("getting config: %w", err)
		}

		logger.Info("CONFIG FOUND!", zap.String("cluster_id", cfg.TypedSpec().ClusterID))
		close(ctrl.configSeen)
		r.ResetRestartBackoff()

		// Keep running to avoid restart.
		<-ctx.Done()
		return nil
	}
}

// TestCOSIConfigPropagation verifies that when ConfigController writes a
// kubespan.Config resource, a downstream controller with InputWeak on Config
// actually receives an event and can read the Config.
func TestCOSIConfigPropagation(t *testing.T) {
	logger := zaptest.NewLogger(t)

	st := state.WrapCore(namespaced.NewState(inmem.Build))

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	rt, err := controllerruntime.NewRuntime(st, logger)
	if err != nil {
		t.Fatalf("creating runtime: %v", err)
	}

	cfgSpec := kubespan.ConfigSpec{
		ClusterID:    "test-cluster-id",
		SharedSecret: "test-secret",
		Enabled:      true,
		ForceRouting: true,
	}

	reader := &configReaderController{
		configSeen: make(chan struct{}),
	}

	if err := rt.RegisterController(&ConfigController{spec: cfgSpec}); err != nil {
		t.Fatalf("registering config controller: %v", err)
	}
	if err := rt.RegisterController(reader); err != nil {
		t.Fatalf("registering reader controller: %v", err)
	}

	runtimeErrCh := make(chan error, 1)
	go func() {
		runtimeErrCh <- rt.Run(ctx)
	}()

	// Also poll the underlying state directly to check if Config exists
	go func() {
		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				cfg, err := safe.StateGetByID[*kubespan.Config](ctx, st, kubespan.ConfigID)
				if err != nil {
					if state.IsNotFoundError(err) {
						t.Log("direct state poll: Config not found")
					} else {
						t.Logf("direct state poll error: %v", err)
					}
				} else {
					t.Logf("direct state poll: Config EXISTS in state, cluster_id=%s", cfg.TypedSpec().ClusterID)
				}
			}
		}
	}()

	select {
	case <-reader.configSeen:
		t.Log("SUCCESS: reader controller saw the Config resource")
	case err := <-runtimeErrCh:
		t.Fatalf("runtime exited unexpectedly: %v", err)
	case <-ctx.Done():
		// Check final state
		cfg, err := safe.StateGetByID[*kubespan.Config](context.Background(), st, kubespan.ConfigID)
		if err != nil {
			t.Logf("final check: Config NOT in state: %v", err)
		} else {
			t.Logf("final check: Config IS in state (cluster_id=%s) but reader never saw it", cfg.TypedSpec().ClusterID)
		}
		t.Fatal("TIMEOUT: reader controller never saw the Config resource")
	}
}
