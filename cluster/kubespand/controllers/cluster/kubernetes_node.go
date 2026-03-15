// KubernetesNodeController watches a K8s Node object via client-go informer
// and produces a k8s.NodeStatus COSI resource with PodCIDRs (+ ServiceCIDRs from config).
//
// The upstream LocalAffiliateController reads k8s.NodeStatus.PodCIDRs to populate
// AdditionalAddresses in the local affiliate announcement.
//
// Ref: talos/internal/app/machined/pkg/controllers/cluster/local_affiliate.go (consumer)
package clusterctrl

import (
	"context"
	"fmt"
	"net/netip"

	"github.com/cosi-project/runtime/pkg/controller"
	"github.com/cosi-project/runtime/pkg/safe"
	"github.com/cosi-project/runtime/pkg/state"
	"github.com/siderolabs/talos/pkg/machinery/resources/k8s"
	"github.com/siderolabs/talos/pkg/machinery/resources/kubespan"
	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/fields"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"

	"github.com/agentydragon/ducktape/cluster/kubespand/agentconfig"
)

// KubernetesNodeController watches a K8s Node object via client-go informer
// and produces a k8s.NodeStatus COSI resource with PodCIDRs + ServiceCIDRs.
type KubernetesNodeController struct {
	factory  informers.SharedInformerFactory
	informer cache.SharedIndexInformer
}

// Name implements controller.Controller.
func (ctrl *KubernetesNodeController) Name() string {
	return "kubespan.KubernetesNodeController"
}

// Inputs implements controller.Controller.
func (ctrl *KubernetesNodeController) Inputs() []controller.Input {
	return []controller.Input{
		safe.Input[*kubespan.Config](controller.InputWeak),
		safe.Input[*agentconfig.Resource](controller.InputWeak),
		safe.Input[*k8s.Nodename](controller.InputWeak),
	}
}

// Outputs implements controller.Controller.
func (ctrl *KubernetesNodeController) Outputs() []controller.Output {
	return []controller.Output{
		{
			Type: k8s.NodeStatusType,
			Kind: controller.OutputExclusive,
		},
	}
}

// Run implements controller.Controller.
func (ctrl *KubernetesNodeController) Run(ctx context.Context, r controller.Runtime, logger *zap.Logger) error {
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

		if !cfg.TypedSpec().AdvertiseKubernetesNetworks {
			continue
		}

		acfg, err := safe.ReaderGetByID[*agentconfig.Resource](ctx, r, agentconfig.ResourceID)
		if err != nil {
			if state.IsNotFoundError(err) {
				continue
			}
			return fmt.Errorf("getting agent config: %w", err)
		}
		agentSpec := acfg.TypedSpec()

		// Read k8s.Nodename to use as the NodeStatus resource ID (matches upstream pattern).
		nodename, err := safe.ReaderGetByID[*k8s.Nodename](ctx, r, k8s.NodenameID)
		if err != nil {
			if state.IsNotFoundError(err) {
				continue
			}
			return fmt.Errorf("getting nodename: %w", err)
		}
		nodeID := nodename.TypedSpec().Nodename

		// Lazy-init the K8s informer on first reconcile when config is available.
		if ctrl.informer == nil {
			if initErr := ctrl.initInformer(ctx, r, logger, agentSpec); initErr != nil {
				logger.Warn("failed to initialize K8s informer, will retry", zap.Error(initErr))
				continue
			}
		}

		// Read node from informer cache and extract PodCIDRs.
		prefixes := ctrl.getPodCIDRs(logger)

		// Merge static ServiceCIDRs from config into PodCIDRs. The upstream
		// LocalAffiliateController reads NodeStatus.PodCIDRs for AdditionalAddresses.
		prefixes = append(prefixes, agentSpec.ServiceCIDRs...)

		// Write k8s.NodeStatus resource keyed by nodename (matches upstream pattern
		// where LocalAffiliateController reads NodeStatus by nodename.TypedSpec().Nodename).
		if err := safe.WriterModify(ctx, r,
			k8s.NewNodeStatus(k8s.NamespaceName, nodeID),
			func(res *k8s.NodeStatus) error {
				res.TypedSpec().Nodename = nodeID
				res.TypedSpec().NodeReady = true
				res.TypedSpec().PodCIDRs = prefixes
				return nil
			},
		); err != nil {
			return fmt.Errorf("writing node status: %w", err)
		}

		logger.Debug("node status reconciled", zap.Int("prefixes", len(prefixes)))
		r.ResetRestartBackoff()
	}
}

// initInformer creates the K8s clientset and starts the node informer.
func (ctrl *KubernetesNodeController) initInformer(ctx context.Context, r controller.Runtime, logger *zap.Logger, agentSpec *agentconfig.Spec) error {
	var config *rest.Config
	var err error

	if agentSpec.KubeconfigPath != "" {
		config, err = clientcmd.BuildConfigFromFlags("", agentSpec.KubeconfigPath)
		if err != nil {
			return fmt.Errorf("building kubeconfig from %s: %w", agentSpec.KubeconfigPath, err)
		}
	} else {
		config, err = rest.InClusterConfig()
		if err != nil {
			return fmt.Errorf("building in-cluster config: %w", err)
		}
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return fmt.Errorf("creating kubernetes client: %w", err)
	}

	// Create informer factory filtered to the local node only.
	ctrl.factory = informers.NewSharedInformerFactoryWithOptions(
		clientset, 0,
		informers.WithTweakListOptions(func(opts *metav1.ListOptions) {
			opts.FieldSelector = fields.OneTermEqualSelector("metadata.name", agentSpec.NodeName).String()
		}),
	)

	ctrl.informer = ctrl.factory.Core().V1().Nodes().Informer()

	// Bridge K8s informer events to COSI reconcile loop.
	ctrl.informer.AddEventHandler(cache.ResourceEventHandlerFuncs{ //nolint:errcheck
		AddFunc:    func(_ interface{}) { r.QueueReconcile() },
		UpdateFunc: func(_, _ interface{}) { r.QueueReconcile() },
		DeleteFunc: func(_ interface{}) { r.QueueReconcile() },
	})

	ctrl.factory.Start(ctx.Done())

	// Wait for initial cache sync.
	if !cache.WaitForCacheSync(ctx.Done(), ctrl.informer.HasSynced) {
		return fmt.Errorf("timed out waiting for K8s node informer to sync")
	}

	logger.Info("K8s node informer started", zap.String("node", agentSpec.NodeName))
	return nil
}

// getPodCIDRs reads PodCIDRs from the informer cache for the local node.
func (ctrl *KubernetesNodeController) getPodCIDRs(logger *zap.Logger) []netip.Prefix {
	items := ctrl.informer.GetStore().List()
	if len(items) == 0 {
		return nil
	}

	node, ok := items[0].(*corev1.Node)
	if !ok {
		return nil
	}

	var prefixes []netip.Prefix
	for _, cidr := range node.Spec.PodCIDRs {
		p, err := netip.ParsePrefix(cidr)
		if err != nil {
			logger.Warn("failed to parse PodCIDR", zap.String("cidr", cidr), zap.Error(err))
			continue
		}
		prefixes = append(prefixes, p)
	}

	return prefixes
}
