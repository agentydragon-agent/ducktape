package runner

import (
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/agentydragon/ducktape/agentplane/runner/harness"
)

// Configuration is the file contract used by every Runner deployment. Sandbox
// identity/bootstrap are supplied separately by the Sandbox Controller.
type Configuration struct {
	Version              int                           `json:"version"`
	StateDir             string                        `json:"state_dir"`
	WorkspaceRoot        *string                       `json:"workspace_root"`
	InitializationCwd    string                        `json:"initialization_cwd"`
	Control              Endpoint                      `json:"control"`
	Ingress              Endpoint                      `json:"ingress"`
	PlatformInstructions string                        `json:"platform_instructions"`
	RunnerEnvironment    Environment                   `json:"runner_environment"`
	HarnessEnvironment   *Environment                  `json:"harness_environment"`
	Claude               *HarnessConfiguration         `json:"claude"`
	Codex                *HarnessConfiguration         `json:"codex"`
	Isolation            *CgroupsConfiguration         `json:"isolation"`
	Executor             json.RawMessage               `json:"executor"`
	DebugCheckpoint      *DebugCheckpointConfiguration `json:"debug_checkpoint"`
}

type DebugCheckpointConfiguration struct {
	Name      string `json:"name"`
	CommandID string `json:"command_id"`
}

type Environment struct {
	Inherit []string          `json:"inherit"`
	Values  map[string]string `json:"values"`
}

func (e Environment) resolve(environ map[string]string) (map[string]string, error) {
	child := map[string]string{}
	for _, name := range e.Inherit {
		if err := validateEnvironmentName(name); err != nil {
			return nil, err
		}
		if value, ok := environ[name]; ok {
			child[name] = value
		} else {
			slog.Warn("inherited variable is absent from Runner environment", "name", name)
		}
	}
	for name, value := range e.Values {
		if err := validateEnvironmentName(name); err != nil {
			return nil, err
		}
		if strings.ContainsRune(value, 0) {
			return nil, fmt.Errorf("environment value %s contains NUL", name)
		}
		child[name] = value
	}
	return child, nil
}

func validateEnvironmentName(name string) error {
	if name == "" || strings.ContainsAny(name, "=\x00") {
		return errors.New("environment names must be nonempty and contain neither '=' nor NUL")
	}
	return nil
}

type HarnessConfiguration struct {
	Binary   string `json:"binary"`
	BaseURL  string `json:"base_url"`
	TokenEnv string `json:"token_env"`
}

func (h *HarnessConfiguration) resolve(environ map[string]string) (*harness.LaunchConfig, error) {
	if h == nil {
		return nil, nil
	}
	if !filepath.IsAbs(h.Binary) {
		return nil, errors.New("harness executable must be absolute")
	}
	u, err := url.Parse(h.BaseURL)
	if err != nil {
		return nil, err
	}
	if (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.Opaque != "" {
		return nil, errors.New("provider URL must be absolute HTTP(S) without credentials, query or fragment")
	}
	if u.Port() != "" {
		port, err := strconv.Atoi(u.Port())
		if err != nil || port < 1 || port > 65535 {
			return nil, errors.New("invalid provider URL port")
		}
	}
	if err := validateEnvironmentName(h.TokenEnv); err != nil {
		return nil, err
	}
	token := environ[h.TokenEnv]
	if token == "" {
		return nil, fmt.Errorf("provider token environment %s is required", h.TokenEnv)
	}
	return &harness.LaunchConfig{Binary: h.Binary, BaseURL: strings.TrimRight(h.BaseURL, "/"), Token: token}, nil
}

type CgroupsConfiguration struct {
	Root         string         `json:"root"`
	AgentUID     uint32         `json:"agent_uid"`
	AgentGID     uint32         `json:"agent_gid"`
	BlockDevices []string       `json:"block_devices"`
	Aggregate    ResourceLimits `json:"aggregate"`
	Process      ResourceLimits `json:"process"`
}

func (c *CgroupsConfiguration) resolve() (*AgentCgroups, error) {
	if c == nil {
		return nil, nil
	}
	if !filepath.IsAbs(c.Root) || c.AgentUID == 0 || c.AgentGID == 0 || len(c.BlockDevices) == 0 {
		return nil, errors.New("cgroups require an absolute root, non-root UID/GID and block devices")
	}
	for _, path := range c.BlockDevices {
		if !filepath.IsAbs(path) {
			return nil, errors.New("block device path must be absolute")
		}
	}
	groups := &AgentCgroups{Root: c.Root, AgentUID: c.AgentUID, AgentGID: c.AgentGID, BlockDevices: c.BlockDevices, AggregateLimits: c.Aggregate, ProcessLimits: c.Process}
	if err := groups.AggregateLimits.Validate(); err != nil {
		return nil, err
	}
	if err := groups.validateProcessLimits(groups.ProcessLimits); err != nil {
		return nil, err
	}
	return groups, nil
}

func resolveExecutor(data json.RawMessage, isolation *AgentCgroups) (*CodexExecutorConfig, error) {
	if len(data) == 0 || string(data) == "null" {
		return nil, nil
	}
	var kind struct {
		Kind string `json:"kind"`
	}
	if err := json.Unmarshal(data, &kind); err != nil {
		return nil, err
	}
	var result CodexExecutorConfig
	switch kind.Kind {
	case "container":
		var spec struct {
			Kind   string `json:"kind"`
			URL    string `json:"url"`
			Socket string `json:"socket"`
		}
		if err := DecodeStrict(data, &spec); err != nil {
			return nil, err
		}
		if spec.Socket == "" {
			return nil, errors.New("container executor socket is required")
		}
		result.URL, result.ContainerSocket = spec.URL, spec.Socket
	case "cgroup":
		var spec struct {
			Kind      string                `json:"kind"`
			URL       string                `json:"url"`
			Isolation *CgroupsConfiguration `json:"isolation"`
		}
		if err := DecodeStrict(data, &spec); err != nil {
			return nil, err
		}
		groups, err := spec.Isolation.resolve()
		if err != nil {
			return nil, err
		}
		result.URL, result.Isolation = spec.URL, groups
	default:
		return nil, fmt.Errorf("unknown executor kind %q", kind.Kind)
	}
	if err := result.validate(isolation); err != nil {
		return nil, err
	}
	return &result, nil
}

// LoadConfiguration validates and composes template policy, the image's explicitly
// inherited environment, and controller-owned launch data before opening state.
func LoadConfiguration(path, launchPath string) (Config, Endpoint, Endpoint, error) {
	config, control, ingress, environment, err := loadConfiguration(path, launchPath)
	if err != nil {
		return Config{}, Endpoint{}, Endpoint{}, err
	}
	for name, value := range environment {
		if err := os.Setenv(name, value); err != nil {
			return Config{}, Endpoint{}, Endpoint{}, err
		}
	}
	return config, control, ingress, nil
}

func loadConfiguration(path, launchPath string) (Config, Endpoint, Endpoint, map[string]string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, Endpoint{}, Endpoint{}, nil, err
	}
	var file Configuration
	if err := DecodeStrict(data, &file); err != nil {
		return Config{}, Endpoint{}, Endpoint{}, nil, fmt.Errorf("invalid Runner configuration: %w", err)
	}
	config, environment, err := file.compose(launchPath)
	return config, file.Control, file.Ingress, environment, err
}

func (f Configuration) compose(launchPath string) (Config, map[string]string, error) {
	if f.Version != 1 {
		return Config{}, nil, errors.New("Runner configuration version must be 1")
	}
	if !filepath.IsAbs(f.StateDir) || !filepath.IsAbs(f.InitializationCwd) || (f.WorkspaceRoot != nil && !filepath.IsAbs(*f.WorkspaceRoot)) {
		return Config{}, nil, errors.New("state, initialization and configured workspace paths must be absolute")
	}
	for name, endpoint := range map[string]Endpoint{"control": f.Control, "ingress": f.Ingress} {
		host, port, err := net.SplitHostPort(endpoint.Target)
		number, numberErr := strconv.Atoi(port)
		if err != nil || host == "" || numberErr != nil || number < 1 || number > 65535 || endpoint.Bearer == "" {
			return Config{}, nil, fmt.Errorf("invalid %s endpoint", name)
		}
	}
	if strings.TrimSpace(f.PlatformInstructions) == "" {
		return Config{}, nil, errors.New("platform instructions must be nonempty")
	}
	environ := map[string]string{}
	for _, entry := range os.Environ() {
		key, value, _ := strings.Cut(entry, "=")
		environ[key] = value
	}
	environment, err := f.RunnerEnvironment.resolve(environ)
	if err != nil {
		return Config{}, nil, err
	}
	maps.Copy(environ, environment)
	if f.HarnessEnvironment == nil {
		return Config{}, nil, errors.New("harness_environment is required")
	}
	child, err := f.HarnessEnvironment.resolve(environ)
	if err != nil {
		return Config{}, nil, err
	}
	if _, ok := child["CODEX_EXEC_SERVER_URL"]; ok {
		return Config{}, nil, errors.New("CODEX_EXEC_SERVER_URL is owned by Runner executor configuration")
	}
	claude, err := f.Claude.resolve(environ)
	if err != nil {
		return Config{}, nil, err
	}
	codex, err := f.Codex.resolve(environ)
	if err != nil {
		return Config{}, nil, err
	}
	isolation, err := f.Isolation.resolve()
	if err != nil {
		return Config{}, nil, err
	}
	executor, err := resolveExecutor(f.Executor, isolation)
	if err != nil {
		return Config{}, nil, err
	}
	if executor != nil && codex == nil {
		return Config{}, nil, errors.New("executor requires Codex")
	}
	launchBytes, err := os.ReadFile(launchPath)
	if err != nil {
		return Config{}, nil, err
	}
	var launch SandboxLaunch
	if err := DecodeStrict(launchBytes, &launch); err != nil {
		return Config{}, nil, err
	}
	if launch.Sandbox.Namespace == "" || launch.Sandbox.Name == "" || launch.Sandbox.UID == "" || (launch.Bootstrap != nil && *launch.Bootstrap == "") {
		return Config{}, nil, errors.New("Sandbox namespace, name, UID and nonempty optional bootstrap are required")
	}
	launch.PlatformInstructions = strings.TrimSpace(f.PlatformInstructions)
	config := Config{StateDir: f.StateDir, InitializationCwd: f.InitializationCwd, Launch: launch, HarnessEnvironment: child, Claude: claude, Codex: codex, ProcessIsolation: isolation, CodexExecutor: executor}
	if f.WorkspaceRoot != nil {
		config.WorkspaceRoot = *f.WorkspaceRoot
	}
	if f.DebugCheckpoint != nil {
		if f.DebugCheckpoint.Name == "" || f.DebugCheckpoint.CommandID == "" {
			return Config{}, nil, errors.New("checkpoint name and command ID must be nonempty")
		}
		config.DebugCheckpoint = &DebugCheckpointConfig{Name: f.DebugCheckpoint.Name, CommandID: f.DebugCheckpoint.CommandID}
	}
	return config, environment, nil
}
