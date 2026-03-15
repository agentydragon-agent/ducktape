// ConfigController injects the agent's parsed configuration into the COSI state
// as three resources:
//   - kubespan.Config — WireGuard/routing settings (upstream type)
//   - cluster.Config  — discovery service settings (upstream type)
//   - agentconfig.Resource — kubespand-specific fields (custom type)
//
// This mirrors Talos's pattern where MachineConfig is decomposed into
// domain-specific config resources by dedicated controllers.
package kubespandctrl

import (
	"context"
	"fmt"

	"github.com/cosi-project/runtime/pkg/controller"
	"github.com/cosi-project/runtime/pkg/safe"
	"github.com/siderolabs/talos/pkg/machinery/resources/cluster"
	talosconfig "github.com/siderolabs/talos/pkg/machinery/resources/config"
	"github.com/siderolabs/talos/pkg/machinery/resources/kubespan"
	"go.uber.org/zap"

	"github.com/agentydragon/ducktape/cluster/kubespand/agentconfig"
)

// ConfigController injects parsed YAML config into COSI state as three resources.
type ConfigController struct {
	KubespanSpec kubespan.ConfigSpec
	ClusterSpec  cluster.ConfigSpec
	AgentSpec    agentconfig.Spec
}

// Name implements controller.Controller.
func (ctrl *ConfigController) Name() string {
	return "kubespand.ConfigController"
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
		{
			Type: cluster.ConfigType,
			Kind: controller.OutputExclusive,
		},
		{
			Type: agentconfig.ResourceType,
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
			kubespan.NewConfig(talosconfig.NamespaceName, kubespan.ConfigID),
			func(res *kubespan.Config) error {
				*res.TypedSpec() = ctrl.KubespanSpec
				return nil
			},
		); err != nil {
			return fmt.Errorf("writing kubespan config: %w", err)
		}

		if err := safe.WriterModify(ctx, r,
			cluster.NewConfig(talosconfig.NamespaceName, cluster.ConfigID),
			func(res *cluster.Config) error {
				*res.TypedSpec() = ctrl.ClusterSpec
				return nil
			},
		); err != nil {
			return fmt.Errorf("writing cluster config: %w", err)
		}

		if err := safe.WriterModify(ctx, r,
			agentconfig.NewResource(),
			func(res *agentconfig.Resource) error {
				*res.TypedSpec() = ctrl.AgentSpec
				return nil
			},
		); err != nil {
			return fmt.Errorf("writing agent config: %w", err)
		}

		logger.Info("config resources injected via COSI controller")
		r.ResetRestartBackoff()
	}
}
