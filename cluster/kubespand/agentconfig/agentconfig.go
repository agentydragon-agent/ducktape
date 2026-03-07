// Package agentconfig holds the kubespand agent YAML configuration and loader.
//
// This wraps the upstream kubespan.ConfigSpec with agent-specific fields
// (discovery endpoint, identity file, etc.) that Talos derives from
// MachineConfig but kubespand loads from a YAML file.
//
// The config is structured into logical groups aligned with Talos conventions:
//   - cluster: identity (matches Talos .spec.cluster.{id,secret})
//   - kubespan: WireGuard interface settings
//   - discovery: discovery service settings
//   - kubernetes: K8s integration (kubespand extension)
package agentconfig

import (
	"fmt"
	"net/netip"
	"os"

	"github.com/siderolabs/talos/pkg/machinery/constants"
	"github.com/siderolabs/talos/pkg/machinery/resources/kubespan"
	"gopkg.in/yaml.v3"
)

// AgentConfig holds the kubespand YAML configuration.
type AgentConfig struct {
	Cluster    ClusterConfig    `yaml:"cluster"`
	Kubespan   KubespanConfig   `yaml:"kubespan"`
	Discovery  DiscoveryConfig  `yaml:"discovery"`
	Kubernetes KubernetesConfig `yaml:"kubernetes"`
}

// ClusterConfig holds cluster identity fields (matches Talos .spec.cluster).
type ClusterConfig struct {
	// ID is the Talos cluster identity (base64). Required.
	ID string `yaml:"id"`
	// Secret is the 32-byte AES key for discovery encryption and WireGuard PSK (base64). Required.
	Secret string `yaml:"secret"`
}

// KubespanConfig holds WireGuard interface and routing settings.
type KubespanConfig struct {
	// ListenPort is the UDP port for the WireGuard interface. Default: 51820.
	ListenPort int `yaml:"listen_port"`
	// MTU for the kubespan WireGuard interface. Default: 1420.
	MTU uint32 `yaml:"mtu"`
	// ForceRouting routes all traffic through KubeSpan even when peers are down.
	ForceRouting bool `yaml:"force_routing"`
	// IdentityFile is the path to persist the WireGuard keypair.
	IdentityFile string `yaml:"identity_file"`
	// EndpointFilters control which discovered peer endpoints are accepted.
	EndpointFilters []string `yaml:"endpoint_filters"`
	// ExtraEndpoints are additional endpoints to announce via the discovery service.
	ExtraEndpoints []netip.AddrPort `yaml:"extra_endpoints"`
	// HarvestExtraEndpoints enables endpoint harvesting for re-announcement.
	HarvestExtraEndpoints bool `yaml:"harvest_extra_endpoints"`
	// ExcludeAdvertisedNetworks are prefixes to exclude from advertised networks.
	ExcludeAdvertisedNetworks []netip.Prefix `yaml:"exclude_advertised_networks"`
}

// DiscoveryConfig holds discovery service settings.
type DiscoveryConfig struct {
	// Endpoint is the gRPC endpoint for the Talos discovery service.
	// Default: constants.DefaultDiscoveryServiceEndpoint
	Endpoint string `yaml:"endpoint"`
	// Insecure uses plaintext gRPC (no TLS) for the discovery service.
	Insecure bool `yaml:"insecure"`
	// MachineType is advertised to the discovery service ("worker" or "controlplane").
	MachineType string `yaml:"machine_type"`
}

// KubernetesConfig holds K8s integration settings (kubespand extension).
type KubernetesConfig struct {
	// AdvertiseNetworks enables advertising Kubernetes pod/service CIDRs via discovery.
	AdvertiseNetworks bool `yaml:"advertise_networks"`
	// KubeconfigPath is the path to a kubeconfig file for K8s API access.
	KubeconfigPath string `yaml:"kubeconfig_path"`
	// NodeName is the Kubernetes node name for this machine.
	NodeName string `yaml:"node_name"`
	// ServiceCIDRs are Kubernetes service network ranges to advertise.
	ServiceCIDRs []netip.Prefix `yaml:"service_cidrs"`
}

// Load reads and validates a YAML config file.
func Load(path string) (*AgentConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading config %s: %w", path, err)
	}

	cfg := &AgentConfig{
		Discovery: DiscoveryConfig{
			Endpoint:    constants.DefaultDiscoveryServiceEndpoint,
			MachineType: "worker",
		},
		Kubespan: KubespanConfig{
			ListenPort:   constants.KubeSpanDefaultPort,
			MTU:          constants.KubeSpanLinkMTU,
			IdentityFile: "/var/lib/kubespan/identity.yaml",
		},
	}

	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, fmt.Errorf("parsing config %s: %w", path, err)
	}

	if cfg.Cluster.ID == "" {
		return nil, fmt.Errorf("cluster.id is required")
	}
	if cfg.Cluster.Secret == "" {
		return nil, fmt.Errorf("cluster.secret is required")
	}
	if cfg.Kubespan.MTU < constants.KubeSpanLinkMinimumMTU {
		return nil, fmt.Errorf("kubespan.mtu must be at least %d", constants.KubeSpanLinkMinimumMTU)
	}
	if cfg.Kubernetes.AdvertiseNetworks && cfg.Kubernetes.NodeName == "" {
		return nil, fmt.Errorf("kubernetes.node_name is required when kubernetes.advertise_networks is true")
	}

	return cfg, nil
}

// ToConfigSpec converts agent config to upstream kubespan.ConfigSpec for COSI injection.
func (ac *AgentConfig) ToConfigSpec() kubespan.ConfigSpec {
	return kubespan.ConfigSpec{
		Enabled:                     true,
		ClusterID:                   ac.Cluster.ID,
		SharedSecret:                ac.Cluster.Secret,
		ForceRouting:                ac.Kubespan.ForceRouting,
		MTU:                         ac.Kubespan.MTU,
		EndpointFilters:             ac.Kubespan.EndpointFilters,
		HarvestExtraEndpoints:       ac.Kubespan.HarvestExtraEndpoints,
		ExtraEndpoints:              ac.Kubespan.ExtraEndpoints,
		AdvertiseKubernetesNetworks: ac.Kubernetes.AdvertiseNetworks,
		ExcludeAdvertisedNetworks:   ac.Kubespan.ExcludeAdvertisedNetworks,
	}
}
