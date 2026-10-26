package runner

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestGuestConfigurationBuildsIsolatedHarnessSettings(t *testing.T) {
	preserveGuestEnvironment(t)
	configPath, launchPath := writeGuestFixture(
		t,
		map[string]any{
			"version":               2,
			"control":               map[string]string{"target": "control.test:7100", "bearer": "control-placeholder"},
			"ingress":               map[string]string{"target": "ingress.test:8081", "bearer": "ingress-placeholder"},
			"resources":             validGuestResources(),
			"llm_base_url":          "http://llm.test:8080/",
			"proxy_url":             "http://proxy.test:3128/",
			"platform_instructions": "Test platform guidance.",
			"console_autologin":     true,
			"harness_env":           map[string]string{"AGENTPLANE_ACTIONS_URL": "http://actions.test:8080"},
		},
		map[string]any{
			"sandbox":   map[string]string{"namespace": "test", "name": "sandbox", "uid": "sandbox-uid"},
			"bootstrap": "echo initialized",
		},
	)

	config, control, ingress, err := GuestConfiguration(configPath, launchPath)
	if err != nil {
		t.Fatal(err)
	}
	if control != (Endpoint{Target: "control.test:7100", Bearer: "control-placeholder"}) {
		t.Fatalf("control endpoint = %+v", control)
	}
	if ingress != (Endpoint{Target: "ingress.test:8081", Bearer: "ingress-placeholder"}) {
		t.Fatalf("ingress endpoint = %+v", ingress)
	}
	if config.StateDir != guestStateDir || config.WorkspaceRoot != guestWorkspaceDir || config.InitializationCwd != guestWorkspaceDir {
		t.Fatalf("guest paths = state %q, workspace %q, initialization %q", config.StateDir, config.WorkspaceRoot, config.InitializationCwd)
	}
	if config.Launch.Sandbox != (SandboxIdentity{Namespace: "test", Name: "sandbox", UID: "sandbox-uid"}) || config.Launch.Bootstrap == nil || *config.Launch.Bootstrap != "echo initialized" || config.Launch.PlatformInstructions != "Test platform guidance." {
		t.Fatalf("guest launch config = %+v", config.Launch)
	}
	if config.Claude == nil || config.Claude.BaseURL != "http://llm.test:8080" || config.Claude.Token != workloadToken {
		t.Fatalf("Claude launch config = %+v", config.Claude)
	}
	if config.Codex == nil || config.Codex.BaseURL != "http://llm.test:8080/v1" || config.Codex.Token != workloadToken {
		t.Fatalf("Codex launch config = %+v", config.Codex)
	}
	if config.ProcessIsolation == nil || config.ProcessIsolation.AgentUID != guestAgentUID || config.ProcessIsolation.AgentGID != guestAgentGID || !reflect.DeepEqual(config.ProcessIsolation.BlockDevices, []string{guestWorkspaceDev}) {
		t.Fatalf("guest process isolation = %+v", config.ProcessIsolation)
	}
	if config.ProcessIsolation.AggregateLimits.MemoryMaxBytes != 1140850688 || config.ProcessIsolation.ProcessLimits.MemoryMaxBytes != 805306368 {
		t.Fatalf("guest resource limits = aggregate %+v, process %+v", config.ProcessIsolation.AggregateLimits, config.ProcessIsolation.ProcessLimits)
	}
	for key, want := range map[string]string{
		"HTTP_PROXY":    "http://proxy.test:3128",
		"HTTPS_PROXY":   "http://proxy.test:3128",
		"SSL_CERT_FILE": guestCABundle,
		"NO_PROXY":      "127.0.0.1,localhost,control.test,ingress.test",
	} {
		if got := os.Getenv(key); got != want {
			t.Errorf("runner environment %s = %q, want %q", key, got, want)
		}
	}
	if config.HarnessEnvironment["KUBECONFIG"] != guestKubeconfig {
		t.Fatalf("guest harness KUBECONFIG = %q", config.HarnessEnvironment["KUBECONFIG"])
	}
	if got := config.HarnessEnvironment["AGENTPLANE_ACTIONS_URL"]; got != "http://actions.test:8080" {
		t.Fatalf("guest harness AGENTPLANE_ACTIONS_URL = %q", got)
	}
	if _, exists := config.HarnessEnvironment["ANTHROPIC_AUTH_TOKEN"]; exists {
		t.Error("guest runner configuration leaked the real Anthropic token into harness environment")
	}
	if _, exists := config.HarnessEnvironment["OPENAI_API_KEY"]; exists {
		t.Error("guest runner configuration leaked the real OpenAI key into harness environment")
	}
}

func TestGuestConfigurationRejectsInvalidSeedAndLaunch(t *testing.T) {
	oversizedAggregate := validGuestResources()
	oversizedAggregate["aggregate"].(map[string]any)["memory_max_bytes"] = 1207959553
	processExceedsAggregate := validGuestResources()
	processExceedsAggregate["process"].(map[string]any)["memory_max_bytes"] = 1140850689
	tests := []struct {
		name   string
		seed   map[string]any
		launch map[string]any
	}{
		{name: "unsupported version", seed: map[string]any{"version": 3}},
		{name: "aggregate memory exceeds service cap", seed: map[string]any{"resources": oversizedAggregate}},
		{name: "process memory exceeds aggregate", seed: map[string]any{"resources": processExceedsAggregate}},
		{name: "missing endpoint bearer", seed: map[string]any{"control": map[string]string{"target": "control.test:7100"}}},
		{name: "empty endpoint", seed: map[string]any{"ingress": map[string]string{"target": "", "bearer": "token"}}},
		{name: "non-http origin", seed: map[string]any{"llm_base_url": "ftp://llm.test"}},
		{name: "hostless origin", seed: map[string]any{"llm_base_url": "llm.test"}},
		{name: "origin path", seed: map[string]any{"llm_base_url": "https://llm.test/v1"}},
		{name: "origin credentials", seed: map[string]any{"llm_base_url": "https://user:secret@llm.test"}},
		{name: "invalid port", seed: map[string]any{"proxy_url": "http://proxy.test:65536"}},
		{name: "zero port", seed: map[string]any{"proxy_url": "http://proxy.test:0"}},
		{name: "empty platform instructions", seed: map[string]any{"platform_instructions": ""}},
		{name: "unknown seed field", seed: map[string]any{"unexpected": "value"}},
		{name: "harness_env overriding a guest-owned name", seed: map[string]any{"harness_env": map[string]string{"PATH": "/elsewhere"}}},
		{name: "missing Sandbox identity", launch: map[string]any{"sandbox": map[string]string{"namespace": "test", "name": "sandbox"}}},
		{name: "empty bootstrap", launch: map[string]any{"bootstrap": ""}},
		{name: "unknown launch field", launch: map[string]any{"unexpected": "value"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			preserveGuestEnvironment(t)
			seed := validGuestSeed()
			mergeGuestValues(seed, test.seed)
			launch := validGuestLaunch()
			mergeGuestValues(launch, test.launch)
			configPath, launchPath := writeGuestFixture(t, seed, launch)
			if _, _, _, err := GuestConfiguration(configPath, launchPath); err == nil {
				t.Fatal("GuestConfiguration accepted invalid input")
			}
		})
	}
}

func TestGuestResourcePropertiesModeValidatesSeedBeforeOutput(t *testing.T) {
	configPath := filepath.Join(t.TempDir(), "config.json")
	writeJSONFixture(t, configPath, validGuestSeed())
	command := exec.Command(os.Args[0], guestResourcePropertiesMode, configPath)
	output, err := command.Output()
	if err != nil {
		t.Fatalf("resource properties mode failed: %v", err)
	}
	want := strings.Join([]string{
		"MemoryHigh=1207959552",
		"MemoryMax=1342177280",
		"MemorySwapMax=0",
		"CPUQuota=100%",
		"TasksMax=1024",
		"",
	}, "\n")
	if string(output) != want {
		t.Fatalf("resource properties = %q, want %q", output, want)
	}

	invalid := validGuestSeed()
	invalid["resources"].(map[string]any)["service_memory_max_bytes"] = 0
	writeJSONFixture(t, configPath, invalid)
	command = exec.Command(os.Args[0], guestResourcePropertiesMode, configPath)
	output, err = command.CombinedOutput()
	if err == nil {
		t.Fatal("resource properties mode accepted invalid resource limits")
	}
	if strings.Contains(string(output), "MemoryHigh=") {
		t.Fatalf("invalid seed produced systemd properties: %q", output)
	}
}

func TestGuestMemoryCapacityRequiresLiveAllocationToMatchSeed(t *testing.T) {
	resources, err := guestResourcesFromMap(validGuestResources())
	if err != nil {
		t.Fatal(err)
	}
	staleTemplateResources := resources
	staleTemplateResources.GuestMemoryBytes = 3 * 1024 * 1024 * 1024
	staleTemplateResources.OSReserveBytes = 512 * 1024 * 1024
	staleTemplateResources.ServiceMemoryHighBytes = 2304 * 1024 * 1024
	staleTemplateResources.ServiceMemoryMaxBytes = 2560 * 1024 * 1024
	for _, test := range []struct {
		name      string
		resources guestResources
		actual    int64
		wantErr   bool
	}{
		{name: "service cap fits live memory", resources: resources, actual: 1500 * 1024 * 1024},
		{name: "stale smaller VM template", resources: staleTemplateResources, actual: 1536 * 1024 * 1024, wantErr: true},
		{name: "service cap consumes all memory", resources: resources, actual: resources.ServiceMemoryMaxBytes, wantErr: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			err := validateGuestMemoryCapacity(test.resources, test.actual)
			if (err != nil) != test.wantErr {
				t.Fatalf("validateGuestMemoryCapacity(%d) error = %v, wantErr %v", test.actual, err, test.wantErr)
			}
		})
	}
}

func TestGuestMemoryTotalBytesParsesMeminfoLines(t *testing.T) {
	path := filepath.Join(t.TempDir(), "meminfo")
	if err := os.WriteFile(path, []byte("MemTotal:       1536000 kB\nHugePages_Total: 0\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := guestMemoryTotalBytes(path)
	if err != nil {
		t.Fatal(err)
	}
	if want := int64(1536000 * 1024); got != want {
		t.Fatalf("MemTotal = %d, want %d", got, want)
	}
}

func guestResourcesFromMap(value map[string]any) (guestResources, error) {
	data, err := json.Marshal(value)
	if err != nil {
		return guestResources{}, err
	}
	var resources guestResources
	if err := DecodeStrict(data, &resources); err != nil {
		return guestResources{}, err
	}
	return resources, nil
}

func writeGuestFixture(t *testing.T, seed, launch any) (string, string) {
	t.Helper()
	directory := t.TempDir()
	configPath := filepath.Join(directory, "config.json")
	launchPath := filepath.Join(directory, "launch.json")
	writeJSONFixture(t, configPath, seed)
	writeJSONFixture(t, launchPath, launch)
	return configPath, launchPath
}

func writeJSONFixture(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
}

func validGuestSeed() map[string]any {
	return map[string]any{
		"version":               2,
		"control":               map[string]string{"target": "control.test:7100", "bearer": "control-placeholder"},
		"ingress":               map[string]string{"target": "ingress.test:8081", "bearer": "ingress-placeholder"},
		"resources":             validGuestResources(),
		"llm_base_url":          "http://llm.test:8080",
		"proxy_url":             "http://proxy.test:3128",
		"platform_instructions": "Test platform guidance.",
	}
}

func validGuestResources() map[string]any {
	return map[string]any{
		"guest_memory_bytes": 1610612736, "guest_vcpu_count": 1, "os_reserve_bytes": 268435456,
		"service_memory_high_bytes": 1207959552, "service_memory_max_bytes": 1342177280,
		"service_cpu_quota_micros": 100000, "service_pids_max": 1024,
		"aggregate": map[string]any{
			"cpu_quota_micros": 100000, "memory_max_bytes": 1140850688,
			"pids_max": 768, "read_bps": 52428800, "write_bps": 20971520,
			"read_iops": 1000, "write_iops": 500,
		},
		"process": map[string]any{
			"cpu_quota_micros": 100000, "memory_max_bytes": 805306368,
			"pids_max": 512, "read_bps": 52428800, "write_bps": 20971520,
			"read_iops": 1000, "write_iops": 500,
		},
	}
}

func validGuestLaunch() map[string]any {
	return map[string]any{"sandbox": map[string]string{"namespace": "test", "name": "sandbox", "uid": "sandbox-uid"}}
}

func mergeGuestValues(target, updates map[string]any) {
	for key, value := range updates {
		target[key] = value
	}
}

func preserveGuestEnvironment(t *testing.T) {
	t.Helper()
	keys := []string{"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy", "SSL_CERT_FILE"}
	values := make(map[string]string, len(keys))
	present := make(map[string]bool, len(keys))
	for _, key := range keys {
		values[key], present[key] = os.LookupEnv(key)
	}
	t.Cleanup(func() {
		for _, key := range keys {
			if present[key] {
				_ = os.Setenv(key, values[key])
			} else {
				_ = os.Unsetenv(key)
			}
		}
	})
}
