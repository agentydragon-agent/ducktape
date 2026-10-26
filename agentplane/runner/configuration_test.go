package runner

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func configurationFixture(t *testing.T) (map[string]any, string, string) {
	t.Helper()
	directory := t.TempDir()
	configPath, launchPath := filepath.Join(directory, "runner.json"), filepath.Join(directory, "launch.json")
	writeJSONFixture(t, launchPath, map[string]any{"sandbox": map[string]string{"namespace": "test", "name": "sandbox", "uid": "sandbox-uid"}, "bootstrap": "echo initialized"})
	value := map[string]any{
		"version": 1, "state_dir": filepath.Join(directory, "state"), "initialization_cwd": directory,
		"control":               map[string]string{"target": "gateway.test:7100", "bearer": "control-placeholder"},
		"ingress":               map[string]string{"target": "history.test:8081", "bearer": "ingress-placeholder"},
		"platform_instructions": "Test guidance.",
		"runner_environment":    map[string]any{"values": map[string]string{"TOOL_ROUTE": "http://tools.test"}},
		"harness_environment":   map[string]any{"inherit": []string{"PATH", "TOOL_ROUTE"}, "values": map[string]string{"HOME": directory}},
		"codex":                 map[string]string{"binary": "/opt/tools/codex", "base_url": "http://models.test/v1", "token_env": "RUNNER_TEST_PROVIDER_TOKEN"},
	}
	return value, configPath, launchPath
}

func configurationCgroups(root string) map[string]any {
	resources := validGuestResources()
	return map[string]any{"root": root, "agent_uid": 107, "agent_gid": 107, "block_devices": []string{"/dev/test-workspace"}, "aggregate": resources["aggregate"], "process": resources["process"]}
}

func TestConfigurationComposesBothIsolationModesWithoutOpeningState(t *testing.T) {
	t.Setenv("RUNNER_TEST_PROVIDER_TOKEN", "provider-secret")
	t.Setenv("PATH", "/image/bin")
	t.Setenv("UNDECLARED_SECRET", "must-not-inherit")
	for _, kind := range []string{"local", "container", "cgroup"} {
		t.Run(kind, func(t *testing.T) {
			value, path, launchPath := configurationFixture(t)
			switch kind {
			case "container":
				value["executor"] = map[string]any{"kind": "container", "url": "ws://127.0.0.1:4501", "socket": "/run/test/executor.sock"}
			case "cgroup":
				value["isolation"] = configurationCgroups("/sys/fs/cgroup/test/workloads")
				value["executor"] = map[string]any{"kind": "cgroup", "url": "ws://127.0.0.1:4501", "isolation": configurationCgroups("/sys/fs/cgroup/test/executors")}
			}
			writeJSONFixture(t, path, value)
			config, control, ingress, environment, err := loadConfiguration(path, launchPath)
			if err != nil {
				t.Fatal(err)
			}
			if control.Target != "gateway.test:7100" || ingress.Target != "history.test:8081" {
				t.Fatalf("endpoints = %v %v", control, ingress)
			}
			want := map[string]string{"PATH": "/image/bin", "TOOL_ROUTE": "http://tools.test", "HOME": filepath.Dir(path)}
			if !reflect.DeepEqual(config.HarnessEnvironment, want) {
				t.Fatalf("child environment = %v, want %v", config.HarnessEnvironment, want)
			}
			if environment["TOOL_ROUTE"] != "http://tools.test" || config.Codex.Token != "provider-secret" {
				t.Fatal("environment/provider configuration was not composed")
			}
			if config.Launch.PlatformInstructions != "Test guidance." || config.Launch.Bootstrap == nil || *config.Launch.Bootstrap != "echo initialized" {
				t.Fatalf("launch = %+v", config.Launch)
			}
			if _, err := os.Stat(config.StateDir); !os.IsNotExist(err) {
				t.Fatalf("configuration opened state: %v", err)
			}
			if (config.CodexExecutor == nil) != (kind == "local") || (config.ProcessIsolation != nil) != (kind == "cgroup") {
				t.Fatalf("incorrect isolation for %s", kind)
			}
		})
	}
}

func TestConfigurationRejectsInvalidPolicyBeforeEnvironmentChanges(t *testing.T) {
	t.Setenv("RUNNER_TEST_PROVIDER_TOKEN", "provider-secret")
	for _, test := range []struct {
		name   string
		update func(map[string]any)
	}{
		{"unknown field", func(v map[string]any) { v["unexpected"] = true }},
		{"old version", func(v map[string]any) { v["version"] = 2 }},
		{"relative state", func(v map[string]any) { v["state_dir"] = "relative" }},
		{"missing initialization cwd", func(v map[string]any) { delete(v, "initialization_cwd") }},
		{"empty workspace root", func(v map[string]any) { v["workspace_root"] = "" }},
		{"missing bearer", func(v map[string]any) { v["control"] = map[string]string{"target": "gateway.test:7100"} }},
		{"bad endpoint", func(v map[string]any) {
			v["ingress"] = map[string]string{"target": "host:notaport", "bearer": "placeholder"}
		}},
		{"partial provider", func(v map[string]any) { v["codex"] = map[string]string{"binary": "/opt/codex"} }},
		{"missing provider token", func(v map[string]any) { v["codex"].(map[string]string)["token_env"] = "ABSENT_PROVIDER_TOKEN" }},
		{"unknown executor", func(v map[string]any) { v["executor"] = map[string]string{"kind": "unknown"} }},
		{"partial container executor", func(v map[string]any) {
			v["executor"] = map[string]string{"kind": "container", "url": "ws://127.0.0.1:4501"}
		}},
		{"mixed executor policies", func(v map[string]any) {
			v["executor"] = map[string]any{"kind": "container", "url": "ws://127.0.0.1:4501", "socket": "/test/socket", "isolation": configurationCgroups("/test/executor")}
		}},
		{"cgroup executor without harness isolation", func(v map[string]any) {
			v["executor"] = map[string]any{"kind": "cgroup", "url": "ws://127.0.0.1:4501", "isolation": configurationCgroups("/test/executor")}
		}},
		{"manual execution override", func(v map[string]any) {
			v["harness_environment"] = map[string]any{"values": map[string]string{"CODEX_EXEC_SERVER_URL": "ws://127.0.0.1:9999"}}
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Setenv("TOOL_ROUTE", "original")
			value, path, launchPath := configurationFixture(t)
			test.update(value)
			writeJSONFixture(t, path, value)
			if _, _, _, err := LoadConfiguration(path, launchPath); err == nil {
				t.Fatal("accepted invalid configuration")
			}
			if os.Getenv("TOOL_ROUTE") != "original" {
				t.Fatal("invalid configuration modified process environment")
			}
		})
	}
}

func TestConfigurationRejectsLaunchFieldsOutsideControllerContract(t *testing.T) {
	t.Setenv("RUNNER_TEST_PROVIDER_TOKEN", "provider-secret")
	value, path, launchPath := configurationFixture(t)
	writeJSONFixture(t, path, value)
	for _, data := range []string{`{"sandbox":{"namespace":"test","name":"sandbox"}}`, `{"sandbox":{"namespace":"test","name":"sandbox","uid":"uid"},"bootstrap":""}`, `{"sandbox":{"namespace":"test","name":"sandbox","uid":"uid"},"platform_instructions":"override"}`} {
		var launch any
		if err := json.Unmarshal([]byte(data), &launch); err != nil {
			t.Fatal(err)
		}
		writeJSONFixture(t, launchPath, launch)
		if _, _, _, _, err := loadConfiguration(path, launchPath); err == nil {
			t.Fatalf("accepted invalid launch %s", data)
		}
	}
}
