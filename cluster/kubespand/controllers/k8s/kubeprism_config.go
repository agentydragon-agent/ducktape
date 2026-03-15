// Ref: internal/app/machined/pkg/controllers/k8s/kubeprism_endpoints.go
//
//	internal/app/machined/pkg/controllers/k8s/kubeprism_config.go
//
// Merges Talos's KubePrismEndpointsController + KubePrismConfigController into one,
// adapted from cluster.Affiliate (kubespand) instead of config.MachineConfig + cluster.Member (Talos).
package k8sctrl

import (
	"context"
	"fmt"
	"net/url"

	"github.com/cosi-project/runtime/pkg/controller"
	"github.com/cosi-project/runtime/pkg/safe"
	"github.com/cosi-project/runtime/pkg/state"
	"github.com/siderolabs/talos/pkg/machinery/config/machine"
	"github.com/siderolabs/talos/pkg/machinery/constants"
	"github.com/siderolabs/talos/pkg/machinery/resources/cluster"
	"github.com/siderolabs/talos/pkg/machinery/resources/k8s"
	"go.uber.org/zap"

	"github.com/agentydragon/ducktape/cluster/kubespand/agentconfig"
)

// KubePrismConfigController watches cluster.Affiliate resources, filters for
// control plane nodes, and produces a k8s.KubePrismConfig resource containing
// the load balancer bind address and upstream API server endpoints.
type KubePrismConfigController struct{}

// Name implements controller.Controller.
func (ctrl *KubePrismConfigController) Name() string {
	return "kubespan.KubePrismConfigController"
}

// Inputs implements controller.Controller.
func (ctrl *KubePrismConfigController) Inputs() []controller.Input {
	return []controller.Input{
		safe.Input[*cluster.Affiliate](controller.InputWeak),
		safe.Input[*agentconfig.Resource](controller.InputWeak),
	}
}

// Outputs implements controller.Controller.
func (ctrl *KubePrismConfigController) Outputs() []controller.Output {
	return []controller.Output{
		{
			Type: k8s.KubePrismConfigType,
			Kind: controller.OutputExclusive,
		},
	}
}

// Run implements controller.Controller.
func (ctrl *KubePrismConfigController) Run(ctx context.Context, r controller.Runtime, logger *zap.Logger) error {
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-r.EventCh():
		}

		acfg, err := safe.ReaderGetByID[*agentconfig.Resource](ctx, r, agentconfig.ResourceID)
		if err != nil {
			if state.IsNotFoundError(err) {
				continue
			}
			return fmt.Errorf("getting agent config: %w", err)
		}
		agentSpec := acfg.TypedSpec()

		var endpoints []k8s.KubePrismEndpoint

		// Add configured fallback endpoint from cluster.endpoint URL.
		// Matches Talos's cluster.controlPlane.endpoint behavior.
		if agentSpec.ClusterEndpoint != "" {
			u, err := url.Parse(agentSpec.ClusterEndpoint)
			if err == nil {
				host := u.Hostname()
				port := u.Port()
				if port == "" {
					port = fmt.Sprintf("%d", constants.DefaultControlPlanePort)
				}
				var portNum uint32
				if _, err := fmt.Sscanf(port, "%d", &portNum); err == nil {
					endpoints = append(endpoints, k8s.KubePrismEndpoint{
						Host: host,
						Port: portNum,
					})
				}
			}
		}

		// List discovered affiliates and extract CP endpoints.
		affiliates, err := safe.ReaderListAll[*cluster.Affiliate](ctx, r)
		if err != nil {
			if state.IsNotFoundError(err) {
				continue
			}
			return fmt.Errorf("listing affiliates: %w", err)
		}

		for aff := range affiliates.All() {
			spec := aff.TypedSpec()
			if spec.MachineType != machine.TypeControlPlane || spec.ControlPlane == nil {
				continue
			}
			// Use routable addresses from the affiliate.
			for _, addr := range spec.Addresses {
				endpoints = append(endpoints, k8s.KubePrismEndpoint{
					Host: addr.String(),
					Port: uint32(spec.ControlPlane.APIServerPort),
				})
			}
		}

		if err := safe.WriterModify(ctx, r,
			k8s.NewKubePrismConfig(k8s.NamespaceName, k8s.KubePrismConfigID),
			func(res *k8s.KubePrismConfig) error {
				res.TypedSpec().Host = agentSpec.KubePrismHost
				res.TypedSpec().Port = agentSpec.KubePrismPort
				res.TypedSpec().Endpoints = endpoints
				return nil
			},
		); err != nil {
			return fmt.Errorf("writing kubeprism config: %w", err)
		}

		logger.Debug("kubeprism config reconciled",
			zap.Int("endpoints", len(endpoints)),
			zap.String("host", agentSpec.KubePrismHost),
			zap.Int("port", agentSpec.KubePrismPort),
		)
		r.ResetRestartBackoff()
	}
}
