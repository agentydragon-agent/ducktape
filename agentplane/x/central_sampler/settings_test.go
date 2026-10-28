package centralsampler

import (
	"encoding/json"
	"strings"
	"testing"
)

func fixtureSettings() Settings {
	return Settings{
		DatabaseURL: "postgresql://fixture.invalid/sampler", Listen: "127.0.0.1:0", ServiceName: "fixture", Providers: map[string]Provider{"responses": {Endpoint: "https://model.invalid/responses", Credential: "test-credential", Models: []string{"test-model"}, ReasoningEfforts: []string{"", "high"}}}, Audience: "test-sampler", AllowedAccounts: []string{"test/client"}, CodeModeHost: "/fixture/host", ExecutorCodex: "/fixture/codex", Logs: "/fixture/logs", DirectExecutorURL: "ws://executor.invalid", MaxLiveSessions: 2, HostRSSBytes: 1024 * 1024, HostPids: 64, HostCPUQuotaUS: 100000, TurnTimeoutSeconds: 40, RPCTimeoutSeconds: 10, LeaseSeconds: 60,
	}
}

func TestSettingsRejectPartialAndUnknownConfiguration(t *testing.T) {
	for name, edit := range map[string]func(*Settings){
		"history token missing":   func(s *Settings) { s.HistoryTarget = "history.invalid:8080" },
		"gateway token missing":   func(s *Settings) { s.DirectExecutorURL = ""; s.GatewayTarget = "gateway.invalid:8080" },
		"two executor transports": func(s *Settings) { s.GatewayTarget = "gateway.invalid:8080"; s.GatewayTokenFile = "/fixture/token" },
		"no executor transport":   func(s *Settings) { s.DirectExecutorURL = "" },
		"unknown template": func(s *Settings) {
			s.DirectExecutorURL = ""
			s.GatewayTarget = "{host}:8080"
			s.GatewayTokenFile = "/fixture/token"
		},
		"zero capacity":   func(s *Settings) { s.MaxLiveSessions = 0 },
		"invalid account": func(s *Settings) { s.AllowedAccounts = []string{"test/client/other"} },
	} {
		t.Run(name, func(t *testing.T) {
			s := fixtureSettings()
			edit(&s)
			if s.Validate() == nil {
				t.Fatal("accepted invalid settings")
			}
		})
	}
	s := fixtureSettings()
	encoded, err := json.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	invalid := strings.TrimSuffix(string(encoded), "}") + `,"unknown":true}`
	if _, err := DecodeSettings(strings.NewReader(invalid)); err == nil {
		t.Fatal("accepted unknown setting")
	}
	invalid = strings.Replace(string(encoded), `"test-credential"`, `{"secret":"test-credential"}`, 1)
	if _, err := DecodeSettings(strings.NewReader(invalid)); err == nil {
		t.Fatal("accepted invalid credential type")
	}
	if _, err := DecodeSettings(strings.NewReader(string(encoded) + ` {}`)); err == nil {
		t.Fatal("accepted a second configuration object")
	}
}

func TestGatewayTemplateCannotInjectAddress(t *testing.T) {
	s := fixtureSettings()
	s.DirectExecutorURL = ""
	s.GatewayTarget = "{sandbox}-control.{namespace}.svc.cluster.local:8080"
	s.GatewayTokenFile = "/fixture/token"
	address, err := s.GatewayAddress("test", "executor")
	if err != nil || address != "executor-control.test.svc.cluster.local:8080" {
		t.Fatalf("address=%q err=%v", address, err)
	}
	for _, name := range []string{"bad.example", "UPPER", "", strings.Repeat("a", 64), "../other", "elsewhere:1234/"} {
		if _, err := s.GatewayAddress("test", name); err == nil {
			t.Fatalf("accepted executor name %q", name)
		}
	}
}
