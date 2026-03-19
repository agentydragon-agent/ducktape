// Nebula configuration generation for the double NAT demo.
// Produces YAML configs matching the patterns from
// cluster/terraform/bootstrap/infrastructure/nebula.tf.
package nebula_demo

import "gopkg.in/yaml.v3"

// NebulaNodeConfig holds everything needed to configure Nebula on one node.
type NebulaNodeConfig struct {
	CACert  string // PEM CA certificate
	HostCrt string // PEM host certificate
	HostKey string // PEM host private key
	Config  string // YAML config content
}

// NebulaConfig is the top-level Nebula YAML config structure.
type NebulaConfig struct {
	PKI           NebulaConfigPKI        `yaml:"pki"`
	StaticHostMap map[string][]string    `yaml:"static_host_map"`
	Lighthouse    NebulaConfigLighthouse `yaml:"lighthouse"`
	Relay         NebulaConfigRelay      `yaml:"relay,omitempty"`
	Listen        NebulaConfigListen     `yaml:"listen"`
	Punchy        NebulaConfigPunchy     `yaml:"punchy"`
	TUN           NebulaConfigTUN        `yaml:"tun"`
	Firewall      NebulaConfigFirewall   `yaml:"firewall"`
	Logging       NebulaConfigLogging    `yaml:"logging,omitempty"`
}

type NebulaConfigPKI struct {
	CA   string `yaml:"ca"`
	Cert string `yaml:"cert"`
	Key  string `yaml:"key"`
}

type NebulaConfigLighthouse struct {
	AmLighthouse bool     `yaml:"am_lighthouse"`
	Interval     int      `yaml:"interval"`
	Hosts        []string `yaml:"hosts,omitempty"`
}

type NebulaConfigRelay struct {
	AmRelay   bool     `yaml:"am_relay,omitempty"`
	Relays    []string `yaml:"relays,omitempty"`
	UseRelays bool     `yaml:"use_relays,omitempty"`
}

type NebulaConfigListen struct {
	Host string `yaml:"host"`
	Port int    `yaml:"port"`
}

type NebulaConfigPunchy struct {
	Punch   bool `yaml:"punch"`
	Respond bool `yaml:"respond"`
}

type NebulaConfigTUN struct {
	Dev string `yaml:"dev"`
}

type NebulaConfigFirewall struct {
	Outbound []NebulaFirewallRule `yaml:"outbound"`
	Inbound  []NebulaFirewallRule `yaml:"inbound"`
}

type NebulaFirewallRule struct {
	Port  string `yaml:"port"`
	Proto string `yaml:"proto"`
	Host  string `yaml:"host"`
}

type NebulaConfigLogging struct {
	Level string `yaml:"level,omitempty"`
}

// allowAllFirewall returns a firewall config that allows all traffic.
func allowAllFirewall() NebulaConfigFirewall {
	rule := NebulaFirewallRule{Port: "any", Proto: "any", Host: "any"}
	return NebulaConfigFirewall{
		Outbound: []NebulaFirewallRule{rule},
		Inbound:  []NebulaFirewallRule{rule},
	}
}

// Nebula PKI paths inside the Talos extension service filesystem.
const (
	nebulaCACrtPath   = "/usr/local/etc/nebula/ca.crt"
	nebulaHostCrtPath = "/usr/local/etc/nebula/host.crt"
	nebulaHostKeyPath = "/usr/local/etc/nebula/host.key"
	nebulaConfigPath  = "/usr/local/etc/nebula/config.yml"
)

// LighthouseConfig builds a Nebula config for a lighthouse+relay node.
func LighthouseConfig(publicIP string) NebulaConfig {
	return NebulaConfig{
		PKI: NebulaConfigPKI{
			CA:   nebulaCACrtPath,
			Cert: nebulaHostCrtPath,
			Key:  nebulaHostKeyPath,
		},
		StaticHostMap: map[string][]string{
			NebulaVPSIP: {publicIP + ":4242"},
		},
		Lighthouse: NebulaConfigLighthouse{
			AmLighthouse: true,
			Interval:     10,
		},
		Relay: NebulaConfigRelay{AmRelay: true},
		Listen: NebulaConfigListen{
			Host: "0.0.0.0",
			Port: 4242,
		},
		Punchy:   NebulaConfigPunchy{Punch: true, Respond: true},
		TUN:      NebulaConfigTUN{Dev: "nebula1"},
		Firewall: allowAllFirewall(),
		Logging:  NebulaConfigLogging{Level: "info"},
	}
}

// PeerConfig builds a Nebula config for a regular peer behind NAT.
func PeerConfig(lighthousePublicIP string) NebulaConfig {
	return NebulaConfig{
		PKI: NebulaConfigPKI{
			CA:   nebulaCACrtPath,
			Cert: nebulaHostCrtPath,
			Key:  nebulaHostKeyPath,
		},
		StaticHostMap: map[string][]string{
			NebulaVPSIP: {lighthousePublicIP + ":4242"},
		},
		Lighthouse: NebulaConfigLighthouse{
			AmLighthouse: false,
			Interval:     10,
			Hosts:        []string{NebulaVPSIP},
		},
		Relay: NebulaConfigRelay{
			Relays:    []string{NebulaVPSIP},
			UseRelays: true,
		},
		Listen: NebulaConfigListen{
			Host: "0.0.0.0",
			Port: 4242,
		},
		Punchy:   NebulaConfigPunchy{Punch: true, Respond: true},
		TUN:      NebulaConfigTUN{Dev: "nebula1"},
		Firewall: allowAllFirewall(),
		Logging:  NebulaConfigLogging{Level: "info"},
	}
}

// MarshalNebulaConfig serializes a Nebula config to YAML.
func MarshalNebulaConfig(cfg NebulaConfig) string {
	data, err := yaml.Marshal(cfg)
	if err != nil {
		panic("marshal nebula config: " + err.Error())
	}
	return string(data)
}
