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
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-r.EventCh():
		}

		cfg, err := safe.ReaderGetByID[*kubespan.Config](ctx, r, kubespan.ConfigID)
		if err != nil {
			if state.IsNotFoundError(err) {
				continue
			}
			return fmt.Errorf("getting config: %w", err)
		}

		logger.Info("config propagated", zap.String("cluster_id", cfg.TypedSpec().ClusterID))
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

	select {
	case <-reader.configSeen:
		t.Log("reader controller saw the Config resource")
	case err := <-runtimeErrCh:
		t.Fatalf("runtime exited unexpectedly: %v", err)
	case <-ctx.Done():
		t.Fatal("timeout: reader controller never saw the Config resource")
	}
}
