package runner

import (
	"bufio"
	"errors"
	"fmt"
	"maps"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"github.com/agentydragon/ducktape/agentplane/runner/harness"
)

const (
	guestSeedVersion  = 2
	guestConfigPath   = "/run/agentplane/config.json"
	guestLaunchPath   = "/run/agentplane/launch.json"
	guestStateDir     = "/state"
	guestWorkspaceDir = "/state/workspaces"
	guestCABundle     = "/run/agentplane/ca-certificates.crt"
	guestKubeconfig   = "/run/agentplane/kubeconfig"
	guestWorkspaceDev = "/dev/disk/by-id/virtio-workspace"
	guestAgentUID     = uint32(107)
	guestAgentGID     = uint32(107)
	workloadToken     = "agentplane-credential-agentplane-workload"
	// The runner disk carries this executable and the `agentplane` command; runner/vm.nix mounts it
	// at /run/agentplane/runner.
	guestRunnerDiskBin = "/run/agentplane/runner/bin"
)

// guestSeed is the read-only per-environment configuration written to the guest.
// Keep console_autologin here even though the runner does not consume it: vm.nix
// and the provisioning schema share this versioned JSON contract.
type guestSeed struct {
	Version              int            `json:"version"`
	Control              Endpoint       `json:"control"`
	Ingress              Endpoint       `json:"ingress"`
	Resources            guestResources `json:"resources"`
	LLMBaseURL           string         `json:"llm_base_url"`
	ProxyURL             string         `json:"proxy_url"`
	PlatformInstructions string         `json:"platform_instructions"`
	ConsoleAutologin     bool           `json:"console_autologin"`
	// HarnessEnv is added to the harness environment; it may not set a name the guest owns.
	HarnessEnv map[string]string `json:"harness_env"`
}

type guestResources struct {
	GuestMemoryBytes       int64          `json:"guest_memory_bytes"`
	GuestVCPUCount         int64          `json:"guest_vcpu_count"`
	OSReserveBytes         int64          `json:"os_reserve_bytes"`
	ServiceMemoryHighBytes int64          `json:"service_memory_high_bytes"`
	ServiceMemoryMaxBytes  int64          `json:"service_memory_max_bytes"`
	ServiceCPUQuotaMicros  int64          `json:"service_cpu_quota_micros"`
	ServicePidsMax         int64          `json:"service_pids_max"`
	Aggregate              ResourceLimits `json:"aggregate"`
	Process                ResourceLimits `json:"process"`
}

func (r guestResources) Validate() error {
	if r.GuestMemoryBytes <= 0 || r.GuestVCPUCount <= 0 || r.OSReserveBytes < 0 || r.OSReserveBytes >= r.GuestMemoryBytes {
		return errors.New("guest memory, vCPU count and OS reserve are inconsistent")
	}
	if r.GuestVCPUCount > int64(^uint64(0)>>1)/int64(cgroupCPUPeriodMicros) {
		return errors.New("guest vCPU count is too large")
	}
	if r.ServiceMemoryHighBytes <= 0 || r.ServiceMemoryMaxBytes < r.ServiceMemoryHighBytes || r.ServiceMemoryMaxBytes > r.GuestMemoryBytes-r.OSReserveBytes {
		return errors.New("service memory caps must leave the configured OS reserve")
	}
	if r.ServiceCPUQuotaMicros <= 0 || r.ServiceCPUQuotaMicros > r.GuestVCPUCount*int64(cgroupCPUPeriodMicros) || r.ServiceCPUQuotaMicros%1000 != 0 {
		return errors.New("service CPU quota must fit guest vCPU capacity and map to an integral systemd CPUQuota percent")
	}
	if r.ServicePidsMax <= 0 {
		return errors.New("service PID max must be positive")
	}
	groups := AgentCgroups{AggregateLimits: r.Aggregate, ProcessLimits: r.Process}
	if err := groups.AggregateLimits.Validate(); err != nil {
		return fmt.Errorf("invalid aggregate limits: %w", err)
	}
	if err := groups.validateProcessLimits(groups.ProcessLimits); err != nil {
		return fmt.Errorf("invalid process limits: %w", err)
	}
	if r.Aggregate.MemoryMaxBytes > r.ServiceMemoryHighBytes || r.Aggregate.PidsMax > r.ServicePidsMax || r.Aggregate.CPUQuotaMicros > r.ServiceCPUQuotaMicros {
		return errors.New("aggregate limits must fit within Runner service limits")
	}
	return nil
}

// guestResourceSystemdProperties reads and validates the seed before returning
// systemd properties. The VM applies these before starting the runner, so this
// path must reject malformed limits before systemctl is invoked.
func guestResourceSystemdProperties(configPath string) ([]string, error) {
	return guestResourceSystemdPropertiesWithMeminfo(configPath, "/proc/meminfo")
}

func guestResourceSystemdPropertiesWithMeminfo(configPath, meminfoPath string) ([]string, error) {
	configBytes, err := os.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("cannot read guest config at %s: %w", configPath, err)
	}
	var seed guestSeed
	if err := DecodeStrict(configBytes, &seed); err != nil {
		return nil, fmt.Errorf("invalid guest config at %s: %w", configPath, err)
	}
	if seed.Version != guestSeedVersion {
		return nil, fmt.Errorf("invalid guest config at %s: version must be %d", configPath, guestSeedVersion)
	}
	if err := seed.Resources.Validate(); err != nil {
		return nil, fmt.Errorf("invalid guest config at %s: invalid resources: %w", configPath, err)
	}
	actualMemory, err := guestMemoryTotalBytes(meminfoPath)
	if err != nil {
		return nil, fmt.Errorf("cannot verify guest memory for config at %s: %w", configPath, err)
	}
	if err := validateGuestMemoryCapacity(seed.Resources, actualMemory); err != nil {
		return nil, fmt.Errorf("invalid guest config at %s: %w", configPath, err)
	}
	return guestResourceProperties(seed.Resources), nil
}

func guestResourceProperties(resources guestResources) []string {
	return []string{
		fmt.Sprintf("MemoryHigh=%d", resources.ServiceMemoryHighBytes),
		fmt.Sprintf("MemoryMax=%d", resources.ServiceMemoryMaxBytes),
		"MemorySwapMax=0",
		fmt.Sprintf("CPUQuota=%d%%", resources.ServiceCPUQuotaMicros/1000),
		fmt.Sprintf("TasksMax=%d", resources.ServicePidsMax),
	}
}

func validateGuestMemoryCapacity(resources guestResources, actualMemoryBytes int64) error {
	if actualMemoryBytes <= 0 {
		return errors.New("guest reports no available memory")
	}
	if resources.ServiceMemoryMaxBytes >= actualMemoryBytes {
		return fmt.Errorf("service memory max %d bytes must be below guest MemTotal %d bytes", resources.ServiceMemoryMaxBytes, actualMemoryBytes)
	}
	return nil
}

func guestMemoryTotalBytes(path string) (int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) == 0 || fields[0] != "MemTotal:" {
			continue
		}
		if len(fields) != 3 || fields[2] != "kB" {
			return 0, errors.New("MemTotal must be a positive kB value")
		}
		value, err := strconv.ParseInt(fields[1], 10, 64)
		if err != nil || value <= 0 || value > int64(^uint64(0)>>1)/1024 {
			return 0, errors.New("MemTotal must be a positive kB value")
		}
		return value * 1024, nil
	}
	if err := scanner.Err(); err != nil {
		return 0, fmt.Errorf("read memory information: %w", err)
	}
	return 0, fmt.Errorf("MemTotal is missing from %s", path)
}

// GuestConfiguration reads the KubeVirt guest's public config and Sandbox launch
// file, then builds the isolated launch configuration specified by the shared guest schema.
// It intentionally does not inherit the runner's environment into harnesses.
func GuestConfiguration(path, launchPath string) (Config, Endpoint, Endpoint, error) {
	if path == "" {
		path = guestConfigPath
	}
	if launchPath == "" {
		launchPath = guestLaunchPath
	}
	configBytes, err := os.ReadFile(path)
	if err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("cannot read guest config at %s: %w", path, err)
	}
	var seed guestSeed
	if err := DecodeStrict(configBytes, &seed); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: %w", path, err)
	}
	if seed.Version != guestSeedVersion {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: version must be %d", path, guestSeedVersion)
	}
	if err := seed.Resources.Validate(); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: invalid resources: %w", path, err)
	}
	if err := validateEndpoint("control", seed.Control); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: %w", path, err)
	}
	if err := validateEndpoint("ingress", seed.Ingress); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: %w", path, err)
	}
	llmBaseURL, err := validateHTTPOrigin("llm_base_url", seed.LLMBaseURL)
	if err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: %w", path, err)
	}
	proxyURL, err := validateHTTPOrigin("proxy_url", seed.ProxyURL)
	if err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: %w", path, err)
	}
	if seed.PlatformInstructions == "" {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: platform_instructions must be nonempty", path)
	}

	launchBytes, err := os.ReadFile(launchPath)
	if err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("cannot read Sandbox launch file at %s: %w", launchPath, err)
	}
	var launch SandboxLaunch
	if err := DecodeStrict(launchBytes, &launch); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid Sandbox launch file at %s: %w", launchPath, err)
	}
	if launch.Sandbox.Namespace == "" || launch.Sandbox.Name == "" || launch.Sandbox.UID == "" {
		return Config{}, Endpoint{}, Endpoint{}, errors.New("invalid Sandbox launch file: Sandbox namespace, name and uid are required")
	}
	if launch.Bootstrap != nil && *launch.Bootstrap == "" {
		return Config{}, Endpoint{}, Endpoint{}, errors.New("invalid Sandbox launch file: bootstrap must be nonempty when present")
	}
	launch.PlatformInstructions = seed.PlatformInstructions

	identity := guestAgentUID
	group := guestAgentGID
	harnessEnvironment := guestHarnessEnvironment(proxyURL)
	for _, name := range slices.Sorted(maps.Keys(seed.HarnessEnv)) {
		if _, owned := harnessEnvironment[name]; owned {
			return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("invalid guest config at %s: harness_env must not set %s, which the guest owns", path, name)
		}
		harnessEnvironment[name] = seed.HarnessEnv[name]
	}
	config := Config{
		StateDir:           guestStateDir,
		Launch:             launch,
		HarnessEnvironment: harnessEnvironment,
		Claude:             &harness.LaunchConfig{Binary: "/run/current-system/sw/bin/claude", BaseURL: llmBaseURL, Token: workloadToken},
		Codex:              &harness.LaunchConfig{Binary: "/run/current-system/sw/bin/codex", BaseURL: llmBaseURL + "/v1", Token: workloadToken},
		ProcessIsolation: &AgentCgroups{
			Root:            "/sys/fs/cgroup/system.slice/agentplane-runner.service/workloads",
			AgentUID:        identity,
			AgentGID:        group,
			BlockDevices:    []string{guestWorkspaceDev},
			AggregateLimits: seed.Resources.Aggregate,
			ProcessLimits:   seed.Resources.Process,
		},
		WorkspaceRoot:     guestWorkspaceDir,
		InitializationCwd: guestWorkspaceDir,
	}
	if err := configureGuestNetworkEnvironment(harnessEnvironment, []string{seed.Control.Target, seed.Ingress.Target}); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, fmt.Errorf("configure guest runner network environment: %w", err)
	}
	return config, seed.Control, seed.Ingress, nil
}

func validateEndpoint(name string, endpoint Endpoint) error {
	if endpoint.Target == "" {
		return fmt.Errorf("%s.target must be nonempty", name)
	}
	if endpoint.Bearer == "" {
		return fmt.Errorf("%s.bearer must be nonempty", name)
	}
	return nil
}

func validateHTTPOrigin(name, value string) (string, error) {
	parsed, err := url.Parse(value)
	if err != nil {
		return "", fmt.Errorf("%s must be an HTTP(S) origin URL", name)
	}
	if (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Opaque != "" || parsed.Hostname() == "" || parsed.User != nil || (parsed.Path != "" && parsed.Path != "/") || parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" {
		return "", fmt.Errorf("%s must be an HTTP(S) origin URL", name)
	}
	if parsed.Host == "" {
		return "", fmt.Errorf("%s must be an HTTP(S) origin URL", name)
	}
	if port := parsed.Port(); port != "" {
		portNumber, err := strconv.Atoi(port)
		if err != nil || portNumber < 0 || portNumber > 65535 {
			return "", fmt.Errorf("%s has an invalid port", name)
		}
		if portNumber == 0 {
			return "", fmt.Errorf("%s must not use port 0", name)
		}
	}
	return strings.TrimSuffix(value, "/"), nil
}

func guestHarnessEnvironment(proxyURL string) map[string]string {
	return map[string]string{
		"HOME":                filepath.Join(guestWorkspaceDir, ".home"),
		"USER":                "agent",
		"LOGNAME":             "agent",
		"PATH":                "/run/current-system/sw/bin:" + guestRunnerDiskBin,
		"TZDIR":               "/usr/share/zoneinfo",
		"HTTP_PROXY":          proxyURL,
		"HTTPS_PROXY":         proxyURL,
		"http_proxy":          proxyURL,
		"https_proxy":         proxyURL,
		"NO_PROXY":            "127.0.0.1,localhost",
		"no_proxy":            "127.0.0.1,localhost",
		"SSL_CERT_FILE":       guestCABundle,
		"NIX_SSL_CERT_FILE":   guestCABundle,
		"CURL_CA_BUNDLE":      guestCABundle,
		"GIT_SSL_CAINFO":      guestCABundle,
		"REQUESTS_CA_BUNDLE":  guestCABundle,
		"NODE_EXTRA_CA_CERTS": guestCABundle,
		"PIP_CERT":            guestCABundle,
		"JAVA_TOOL_OPTIONS":   "-Djavax.net.ssl.trustStore=/run/agentplane/ca-certificates.p12 -Djavax.net.ssl.trustStoreType=PKCS12",
		"KUBECONFIG":          guestKubeconfig,
	}
}

func configureGuestNetworkEnvironment(environment map[string]string, directTargets []string) error {
	noProxy := []string{environment["NO_PROXY"]}
	seen := map[string]struct{}{}
	for _, target := range directTargets {
		parsed, err := url.Parse("//" + target)
		if err != nil {
			return fmt.Errorf("invalid direct service target %q", target)
		}
		host := parsed.Hostname()
		if host == "" {
			continue
		}
		if _, ok := seen[host]; ok {
			continue
		}
		seen[host] = struct{}{}
		noProxy = append(noProxy, host)
	}
	value := strings.Join(noProxy, ",")
	for key, current := range map[string]string{
		"HTTP_PROXY":    environment["HTTP_PROXY"],
		"HTTPS_PROXY":   environment["HTTPS_PROXY"],
		"http_proxy":    environment["http_proxy"],
		"https_proxy":   environment["https_proxy"],
		"SSL_CERT_FILE": environment["SSL_CERT_FILE"],
		"NO_PROXY":      value,
		"no_proxy":      value,
	} {
		if err := os.Setenv(key, current); err != nil {
			return fmt.Errorf("set %s: %w", key, err)
		}
	}
	return nil
}
