package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	controllerruntime "github.com/cosi-project/runtime/pkg/controller/runtime"
	"github.com/cosi-project/runtime/pkg/state"
	"github.com/cosi-project/runtime/pkg/state/impl/inmem"
	"github.com/cosi-project/runtime/pkg/state/impl/namespaced"
	"go.uber.org/zap"

	"github.com/agentydragon/ducktape/cluster/kubespand/agentconfig"
	taloscontrollersk8s "github.com/siderolabs/talos/internal/app/machined/pkg/controllers/k8s"
	taloscontrollerskubespan "github.com/siderolabs/talos/internal/app/machined/pkg/controllers/kubespan"
	taloscontrollersnetwork "github.com/siderolabs/talos/internal/app/machined/pkg/controllers/network"
)

// agentCfg is the parsed agent configuration, accessible to controllers
// for agent-specific fields not in upstream kubespan.ConfigSpec.
var agentCfg *agentconfig.AgentConfig

func main() {
	configPath := flag.String("config", "/etc/kubespan/agent.yaml", "path to config file")
	debug := flag.Bool("debug", false, "enable debug logging")
	flag.Parse()

	var logger *zap.Logger
	var err error
	if *debug {
		logger, err = zap.NewDevelopment()
	} else {
		logger, err = zap.NewProduction()
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "logger: %v\n", err)
		os.Exit(1)
	}
	defer logger.Sync() //nolint:errcheck

	if err := run(*configPath, logger); err != nil {
		logger.Fatal("kubespand exited with error", zap.Error(err))
	}
}

func run(configPath string, logger *zap.Logger) error {
	// Load agent config from YAML.
	var err error
	agentCfg, err = agentconfig.Load(configPath)
	if err != nil {
		return fmt.Errorf("config: %w", err)
	}
	logger.Info("loaded config",
		zap.String("cluster_id", agentCfg.Cluster.ID),
		zap.String("discovery_endpoint", agentCfg.Discovery.Endpoint),
		zap.Int("listen_port", agentCfg.Kubespan.ListenPort),
		zap.Uint32("mtu", agentCfg.Kubespan.MTU),
	)

	// Convert to upstream ConfigSpec for COSI injection.
	cfgSpec := agentCfg.ToConfigSpec()

	// Create COSI in-memory state.
	st := state.WrapCore(namespaced.NewState(inmem.Build))

	// Set up context with signal handling.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		select {
		case sig := <-sigCh:
			logger.Info("received signal, shutting down", zap.String("signal", sig.String()))
			cancel()
		case <-ctx.Done():
		}
	}()

	// Create COSI controller runtime.
	rt, err := controllerruntime.NewRuntime(st, logger)
	if err != nil {
		return fmt.Errorf("creating controller runtime: %w", err)
	}

	// Register controllers.
	// ConfigController injects the parsed YAML config as a COSI resource.
	// It must go through a controller (not direct state manipulation) so that
	// the COSI runtime's internal watches detect the creation and trigger
	// downstream controllers via EventCh.
	if err := rt.RegisterController(&ConfigController{spec: cfgSpec}); err != nil {
		return fmt.Errorf("registering config controller: %w", err)
	}
	if err := rt.RegisterController(&IdentityController{}); err != nil {
		return fmt.Errorf("registering identity controller: %w", err)
	}
	if err := rt.RegisterController(&DiscoveryController{}); err != nil {
		return fmt.Errorf("registering discovery controller: %w", err)
	}
	if err := rt.RegisterController(&taloscontrollerskubespan.PeerSpecController{}); err != nil {
		return fmt.Errorf("registering peerspec controller: %w", err)
	}
	if agentCfg.Kubernetes.AdvertiseNetworks {
		if err := rt.RegisterController(&KubernetesNodeController{}); err != nil {
			return fmt.Errorf("registering k8s node controller: %w", err)
		}
	}
	if agentCfg.KubePrism.Enabled {
		if err := rt.RegisterController(&KubePrismConfigController{}); err != nil {
			return fmt.Errorf("registering kubeprism config controller: %w", err)
		}
		if err := rt.RegisterController(&taloscontrollersk8s.KubePrismController{}); err != nil {
			return fmt.Errorf("registering kubeprism controller: %w", err)
		}
	}
	if err := rt.RegisterController(&ManagerController{}); err != nil {
		return fmt.Errorf("registering manager controller: %w", err)
	}
	if err := rt.RegisterController(&taloscontrollersnetwork.NfTablesChainController{}); err != nil {
		return fmt.Errorf("registering nftables chain controller: %w", err)
	}
	if err := rt.RegisterController(&taloscontrollersnetwork.AddressSpecController{}); err != nil {
		return fmt.Errorf("registering address spec controller: %w", err)
	}
	if err := rt.RegisterController(&taloscontrollersnetwork.RouteSpecController{}); err != nil {
		return fmt.Errorf("registering route spec controller: %w", err)
	}
	if err := rt.RegisterController(&taloscontrollerskubespan.EndpointController{}); err != nil {
		return fmt.Errorf("registering endpoint controller: %w", err)
	}

	logger.Info("starting COSI runtime")

	// Start the COSI runtime in a goroutine.
	runtimeErrCh := make(chan error, 1)
	go func() {
		err := rt.Run(ctx)
		if err != nil {
			logger.Error("COSI runtime exited with error", zap.Error(err))
		} else {
			logger.Info("COSI runtime exited cleanly")
		}
		runtimeErrCh <- err
	}()

	// Run until context cancelled.
	select {
	case err := <-runtimeErrCh:
		if err != nil {
			return fmt.Errorf("controller runtime: %w", err)
		}
		return nil
	case <-ctx.Done():
		return nil
	}
}
