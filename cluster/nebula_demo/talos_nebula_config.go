// Talos machine config generation with Nebula extension service.
// Produces multi-document YAML: the standard v1alpha1 config + an
// ExtensionServiceConfig document that injects Nebula certs and config.
package nebula_demo

import (
	"fmt"
	"net/url"
	"testing"

	sx509 "github.com/siderolabs/crypto/x509"
	v1alpha1 "github.com/siderolabs/talos/pkg/machinery/config/types/v1alpha1"
	"gopkg.in/yaml.v3"

	h "github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests"
	"github.com/agentydragon/ducktape/cluster/kubespand/qemu_tests/vmconst"
)

// ExtensionServiceConfig is a Talos document that mounts config files
// into a system extension service's filesystem.
type ExtensionServiceConfig struct {
	APIVersion  string       `yaml:"apiVersion"`
	Kind        string       `yaml:"kind"`
	Name        string       `yaml:"name"`
	ConfigFiles []ConfigFile `yaml:"configFiles"`
}

// ConfigFile is a single file to mount into an extension service.
type ConfigFile struct {
	MountPath string `yaml:"mountPath"`
	Content   string `yaml:"content"`
}

// NebulaExtensionConfig builds the ExtensionServiceConfig document for Nebula.
func NebulaExtensionConfig(caCrt, hostCrt, hostKey, configYAML string) ExtensionServiceConfig {
	return ExtensionServiceConfig{
		APIVersion: "v1alpha1",
		Kind:       "ExtensionServiceConfig",
		Name:       "nebula",
		ConfigFiles: []ConfigFile{
			{MountPath: nebulaCACrtPath, Content: caCrt},
			{MountPath: nebulaHostCrtPath, Content: hostCrt},
			{MountPath: nebulaHostKeyPath, Content: hostKey},
			{MountPath: nebulaConfigPath, Content: configYAML},
		},
	}
}

// TalosNebulaNodeConfig holds per-node parameters for Talos + Nebula config generation.
type TalosNebulaNodeConfig struct {
	IP                   string // e.g. "192.168.50.2/24"
	Gateway              string // optional
	ControlPlaneEndpoint string // e.g. "https://192.168.50.2:6443"
	CertSANs             []string
	// Nebula extension config (injected as second YAML document)
	NebulaCACrt      string
	NebulaHostCrt    string
	NebulaHostKey    string
	NebulaConfigYAML string
}

// ControlPlaneConfigWithNebula generates a multi-document YAML for a Talos
// control plane node with KubeSpan disabled and Nebula enabled.
func ControlPlaneConfigWithNebula(secrets *h.TestTalosSecrets, opts TalosNebulaNodeConfig) []byte {
	cfg := baseTalosConfig(secrets, "controlplane", opts)
	cfg.ClusterConfig.ClusterCA = secrets.ClusterCA
	cfg.ClusterConfig.ClusterAggregatorCA = secrets.AggregatorCA
	cfg.ClusterConfig.ClusterServiceAccount = &sx509.PEMEncodedKey{Key: secrets.ServiceAccountKey}
	cfg.ClusterConfig.EtcdConfig = &v1alpha1.EtcdConfig{
		RootCA: secrets.EtcdCA,
	}
	if len(opts.CertSANs) > 0 {
		cfg.ClusterConfig.APIServerConfig = &v1alpha1.APIServerConfig{
			CertSANs: opts.CertSANs,
		}
	}

	return marshalMultiDoc(cfg, opts)
}

// WorkerConfigWithNebula generates a multi-document YAML for a Talos
// worker node with KubeSpan disabled and Nebula enabled.
func WorkerConfigWithNebula(secrets *h.TestTalosSecrets, opts TalosNebulaNodeConfig) []byte {
	cfg := baseTalosConfig(secrets, "worker", opts)
	cfg.MachineConfig.MachineCA = &sx509.PEMEncodedCertificateAndKey{
		Crt: secrets.MachineCA.Crt,
		Key: []byte{},
	}
	cfg.ClusterConfig.ClusterCA = &sx509.PEMEncodedCertificateAndKey{
		Crt: secrets.ClusterCA.Crt,
		Key: []byte{},
	}

	return marshalMultiDoc(cfg, opts)
}

func baseTalosConfig(secrets *h.TestTalosSecrets, machineType string, opts TalosNebulaNodeConfig) *v1alpha1.Config {
	eth0 := &v1alpha1.Device{
		DeviceInterface: "eth0",
		DeviceAddresses: []string{opts.IP},
	}
	if opts.Gateway != "" {
		eth0.DeviceRoutes = append(eth0.DeviceRoutes, &v1alpha1.Route{
			RouteNetwork: "0.0.0.0/0",
			RouteGateway: opts.Gateway,
		})
	}
	eth1 := &v1alpha1.Device{
		DeviceInterface: "eth1",
		DeviceAddresses: []string{vmconst.MgmtIP + "/24"},
	}

	trueVal := true
	cfg := &v1alpha1.Config{
		ConfigVersion: "v1alpha1",
		ConfigPersist: &trueVal,
		MachineConfig: &v1alpha1.MachineConfig{
			MachineType:     machineType,
			MachineToken:    secrets.MachineToken,
			MachineCA:       secrets.MachineCA,
			MachineCertSANs: []string{"127.0.0.1"},
			MachineKubelet:  &v1alpha1.KubeletConfig{},
			MachineNetwork: &v1alpha1.NetworkConfig{
				NetworkInterfaces: []*v1alpha1.Device{eth0, eth1},
				// KubeSpan explicitly disabled — we use Nebula instead.
				NetworkKubeSpan: &v1alpha1.NetworkKubeSpan{
					KubeSpanEnabled: boolPtr(false),
				},
			},
			MachineInstall: &v1alpha1.InstallConfig{
				InstallDisk: "/dev/sda",
			},
			MachineTime: &v1alpha1.TimeConfig{
				TimeDisabled: boolPtr(true),
			},
			MachineFeatures: &v1alpha1.FeaturesConfig{
				RBAC:                 &trueVal,
				StableHostname:       &trueVal,
				ApidCheckExtKeyUsage: &trueVal,
				DiskQuotaSupport:     &trueVal,
				KubePrismSupport: &v1alpha1.KubePrism{
					ServerEnabled: boolPtr(true),
					ServerPort:    7445,
				},
				HostDNSSupport: &v1alpha1.HostDNSConfig{
					HostDNSEnabled:              boolPtr(false),
					HostDNSForwardKubeDNSToHost: boolPtr(false),
				},
			},
		},
		ClusterConfig: &v1alpha1.ClusterConfig{
			ClusterID:     secrets.ClusterID,
			ClusterSecret: secrets.ClusterSecret,
			ControlPlane: &v1alpha1.ControlPlaneConfig{
				Endpoint: &v1alpha1.Endpoint{URL: mustParseURL(opts.ControlPlaneEndpoint)},
			},
			ClusterName:                      "nebula-demo",
			BootstrapToken:                   secrets.ClusterToken,
			ClusterSecretboxEncryptionSecret: secrets.SecretboxSecret,
			CoreDNSConfig: &v1alpha1.CoreDNS{
				CoreDNSDisabled: boolPtr(true),
			},
			ClusterNetwork: &v1alpha1.ClusterNetworkConfig{
				CNI: &v1alpha1.CNIConfig{
					CNIName: "none",
				},
				DNSDomain:     "cluster.local",
				PodSubnet:     []string{"10.244.0.0/16"},
				ServiceSubnet: []string{"10.96.0.0/12"},
			},
			// Discovery disabled — Nebula handles peer discovery via lighthouses.
			ClusterDiscoveryConfig: &v1alpha1.ClusterDiscoveryConfig{
				DiscoveryEnabled: boolPtr(false),
			},
		},
	}

	return cfg
}

func marshalMultiDoc(cfg *v1alpha1.Config, opts TalosNebulaNodeConfig) []byte {
	machineConfig, err := yaml.Marshal(cfg)
	if err != nil {
		panic(fmt.Sprintf("marshal talos config: %v", err))
	}

	extCfg := NebulaExtensionConfig(opts.NebulaCACrt, opts.NebulaHostCrt, opts.NebulaHostKey, opts.NebulaConfigYAML)
	extDoc, err := yaml.Marshal(extCfg)
	if err != nil {
		panic(fmt.Sprintf("marshal extension config: %v", err))
	}

	// Multi-document YAML: machine config + ExtensionServiceConfig
	return append(machineConfig, append([]byte("---\n"), extDoc...)...)
}

func mustParseURL(rawURL string) *url.URL {
	u, err := url.Parse(rawURL)
	if err != nil {
		panic(fmt.Sprintf("parse URL %q: %v", rawURL, err))
	}
	return u
}

func boolPtr(v bool) *bool { return &v }

// ReadTestdataCert reads a pre-generated Nebula certificate or key from testdata.
func ReadTestdataCert(t *testing.T, filename string) string {
	t.Helper()
	data := h.ReadRunfile(t, "cluster/nebula_demo/testdata/"+filename)
	return string(data)
}
