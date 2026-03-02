package main

import (
	"context"
	"fmt"

	"github.com/cosi-project/runtime/pkg/controller"
	"github.com/cosi-project/runtime/pkg/safe"
	"github.com/siderolabs/talos/pkg/machinery/resources/kubespan"
	"go.uber.org/zap"
)

// ConfigController injects the agent's parsed configuration into the COSI state
// as a kubespan.Config resource. This is the COSI-native equivalent of Talos's
// KubeSpanConfigController, which derives Config from MachineConfig.
//
// Creating Config through a controller (rather than writing to the state directly)
// ensures the COSI runtime's internal watches detect the resource and trigger
// downstream controllers (IdentityController, etc.) via EventCh.
type ConfigController struct {
	spec kubespan.ConfigSpec
}

// Name implements controller.Controller.
func (ctrl *ConfigController) Name() string {
	return "kubespan.ConfigController"
}

// Inputs implements controller.Controller.
func (ctrl *ConfigController) Inputs() []controller.Input {
	return nil
}

// Outputs implements controller.Controller.
func (ctrl *ConfigController) Outputs() []controller.Output {
	return []controller.Output{
		{
			Type: kubespan.ConfigType,
			Kind: controller.OutputExclusive,
		},
	}
}

// Run implements controller.Controller.
func (ctrl *ConfigController) Run(ctx context.Context, r controller.Runtime, logger *zap.Logger) error {
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-r.EventCh():
		}

		if err := safe.WriterModify(ctx, r,
			kubespan.NewConfig(kubespan.NamespaceName, kubespan.ConfigID),
			func(res *kubespan.Config) error {
				*res.TypedSpec() = ctrl.spec
				return nil
			},
		); err != nil {
			return fmt.Errorf("writing config: %w", err)
		}

		logger.Info("config resource injected via COSI controller")
		r.ResetRestartBackoff()
	}
}
