package kubeapiproxy

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type recordingAuthority struct {
	mu       sync.Mutex
	requests []AuthorizationRequest
	headers  []http.Header
	decision AuthorizationResponse
	status   int
}

func (a *recordingAuthority) ServeHTTP(w http.ResponseWriter, request *http.Request) {
	var body AuthorizationRequest
	if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	a.mu.Lock()
	a.requests = append(a.requests, body)
	a.headers = append(a.headers, request.Header.Clone())
	a.mu.Unlock()
	status := a.status
	if status == 0 {
		status = http.StatusOK
	}
	writeJSON(w, status, a.decision)
}

func allowedDecision() AuthorizationResponse {
	return AuthorizationResponse{Allowed: true, DecisionID: "sar:test"}
}

type bearerTransport struct {
	base  http.RoundTripper
	token string
}

func (t bearerTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	clone := request.Clone(request.Context())
	clone.Header.Set("Authorization", "Bearer "+t.token)
	return t.base.RoundTrip(clone)
}

func newTestProxy(t *testing.T, authority http.Handler, upstream http.Handler, mutate func(*Config)) *httptest.Server {
	t.Helper()
	authorityServer := httptest.NewServer(authority)
	t.Cleanup(authorityServer.Close)
	upstreamServer := httptest.NewServer(upstream)
	t.Cleanup(upstreamServer.Close)
	authorityURL, _ := url.Parse(authorityServer.URL + "/api/internal/kubernetes/authorize")
	upstreamURL, _ := url.Parse(upstreamServer.URL)
	config := Config{
		AuthorizationURL:           authorityURL,
		AllowInsecureAuthorization: true,
		Upstream:                   upstreamURL,
		UpstreamTransport:          bearerTransport{base: http.DefaultTransport, token: "proxy-kubernetes-token"},
	}
	if mutate != nil {
		mutate(&config)
	}
	handler, err := NewHandler(config)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return server
}

func request(t *testing.T, client *http.Client, method string, rawURL string, token string) *http.Response {
	t.Helper()
	req, err := http.NewRequest(method, rawURL, nil)
	if err != nil {
		t.Fatal(err)
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return response
}

func TestAuthorizationContractUsesSnakeCaseJSON(t *testing.T) {
	body, err := json.Marshal(AuthorizationRequest{
		Attributes: RequestAttributes{
			ResourceRequest: true,
			APIGroup:        "apps",
			APIVersion:      "v1",
			FieldSelector:   "metadata.name=web",
			LabelSelector:   "app=web",
		},
		RequiredScope: GrantScope{Kind: grantScopeNamespaces, Namespaces: []string{"demo"}},
		RequiredRules: []PolicyRule{{
			APIGroups:       []string{"apps"},
			Resources:       []string{"deployments"},
			ResourceNames:   []string{"web"},
			NonResourceURLs: []string{"/version"},
			Verbs:           []string{"get"},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	validUntil := time.Unix(1, 0).UTC()
	decisionBody, err := json.Marshal(AuthorizationResponse{
		Allowed: true, DecisionID: "sar:test", ValidUntil: &validUntil,
	})
	if err != nil {
		t.Fatal(err)
	}
	encoded := string(body) + string(decisionBody)
	for _, field := range []string{
		"resource_request",
		"api_group",
		"api_version",
		"field_selector",
		"label_selector",
		"required_scope",
		"required_rules",
		"api_groups",
		"resources",
		"resource_names",
		"non_resource_urls",
		"decision_id",
		"valid_until",
	} {
		if !strings.Contains(encoded, `"`+field+`"`) {
			t.Errorf("JSON does not contain %q: %s", field, encoded)
		}
	}
}

func TestNamedPodLogRequestIsAuthorizedAndForwarded(t *testing.T) {
	decision := allowedDecision()
	authority := &recordingAuthority{decision: decision}
	upstream := http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if got := request.Header.Get("Authorization"); got != "Bearer proxy-kubernetes-token" {
			t.Errorf("upstream authorization = %q", got)
		}
		for _, name := range []string{"Impersonate-User", "X-Remote-User", "Cookie", "Proxy-Authorization", "X-Api-Key", "X-Forwarded-For"} {
			if got := request.Header.Get(name); got != "" {
				t.Errorf("upstream received %s: %q", name, got)
			}
		}
		if got := request.Header.Get("Accept"); got != "application/json" {
			t.Errorf("upstream Accept = %q", got)
		}
		w.Header().Set("Content-Type", "text/plain")
		_, _ = w.Write([]byte("logs"))
	})
	proxy := newTestProxy(t, authority, upstream, nil)

	req, err := http.NewRequest(http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods/web/log?tailLines=25", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer caller-secret")
	req.Header.Set("Impersonate-User", "cluster-admin")
	req.Header.Set("X-Remote-User", "cluster-admin")
	req.Header.Set("Cookie", "console_session=secret")
	req.Header.Set("Proxy-Authorization", "Basic secret")
	req.Header.Set("X-Api-Key", "secret")
	req.Header.Set("X-Forwarded-For", "127.0.0.1")
	req.Header.Set("Accept", "application/json")
	response, err := proxy.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", response.StatusCode)
	}
	if got := response.Header.Get("X-Haku-Kubernetes-Decision-ID"); got != decision.DecisionID {
		t.Errorf("decision header = %q, want %q", got, decision.DecisionID)
	}

	authority.mu.Lock()
	defer authority.mu.Unlock()
	if len(authority.requests) != 1 {
		t.Fatalf("authorization requests = %d", len(authority.requests))
	}
	got := authority.requests[0]
	wantAttributes := RequestAttributes{
		ResourceRequest: true,
		Verb:            "get",
		APIVersion:      "v1",
		Namespace:       "demo",
		Resource:        "pods",
		Subresource:     "log",
		Name:            "web",
		Path:            "/api/v1/namespaces/demo/pods/web/log",
	}
	if got.Attributes != wantAttributes {
		t.Errorf("attributes = %#v, want %#v", got.Attributes, wantAttributes)
	}
	if got.RequiredScope.Kind != grantScopeNamespaces || strings.Join(got.RequiredScope.Namespaces, ",") != "demo" {
		t.Errorf("scope = %#v", got.RequiredScope)
	}
	if len(got.RequiredRules) != 1 {
		t.Fatalf("rules = %#v", got.RequiredRules)
	}
	rule := got.RequiredRules[0]
	if strings.Join(rule.APIGroups, ",") != "" || strings.Join(rule.Resources, ",") != "pods/log" || strings.Join(rule.Verbs, ",") != "get" || strings.Join(rule.ResourceNames, ",") != "web" {
		t.Errorf("rule = %#v", rule)
	}
	if got := authority.headers[0].Get("Authorization"); got != "Bearer caller-secret" {
		t.Errorf("authority authorization = %q", got)
	}
}

func TestListRequestProducesListRule(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"kind": "PodList"})
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods?labelSelector=app%3Dweb", "caller")
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", response.StatusCode)
	}
	authority.mu.Lock()
	defer authority.mu.Unlock()
	got := authority.requests[0]
	if got.Attributes.Verb != "list" || got.Attributes.LabelSelector != "app=web" {
		t.Errorf("attributes = %#v", got.Attributes)
	}
	if len(got.RequiredRules[0].ResourceNames) != 0 {
		t.Errorf("list rule unexpectedly has resourceNames: %#v", got.RequiredRules[0])
	}
}

func TestNameFieldSelectorUsesKubernetesResourceName(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"kind": "PodList"})
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods?fieldSelector=metadata.name%3Dweb", "caller")
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", response.StatusCode)
	}
	authority.mu.Lock()
	defer authority.mu.Unlock()
	got := authority.requests[0]
	if got.Attributes.Verb != "list" || got.Attributes.Name != "web" || got.Attributes.FieldSelector != "metadata.name=web" {
		t.Errorf("attributes = %#v", got.Attributes)
	}
	if strings.Join(got.RequiredRules[0].ResourceNames, ",") != "web" {
		t.Errorf("field-selected list rule = %#v", got.RequiredRules[0])
	}
}

func TestNonResourceRequestProducesNonResourceRule(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"gitVersion": "test"})
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/version", "caller")
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", response.StatusCode)
	}
	authority.mu.Lock()
	defer authority.mu.Unlock()
	rule := authority.requests[0].RequiredRules[0]
	if scope := authority.requests[0].RequiredScope; scope.Kind != grantScopeNonResource || len(scope.Namespaces) != 0 {
		t.Errorf("scope = %#v", scope)
	}
	if strings.Join(rule.NonResourceURLs, ",") != "/version" || strings.Join(rule.Verbs, ",") != "get" {
		t.Errorf("rule = %#v", rule)
	}
}

func TestUnnamespacedResourceScopeComesFromDiscovery(t *testing.T) {
	for _, test := range []struct {
		name       string
		path       string
		namespaced bool
		wantKind   string
	}{
		{name: "all namespaces", path: "/api/v1/pods", namespaced: true, wantKind: grantScopeAllNamespaces},
		{name: "cluster resource", path: "/api/v1/nodes", namespaced: false, wantKind: grantScopeCluster},
	} {
		t.Run(test.name, func(t *testing.T) {
			authority := &recordingAuthority{decision: allowedDecision()}
			resolver := &staticResourceScopes{namespaced: test.namespaced}
			proxy := newTestProxy(t, authority, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				writeJSON(w, http.StatusOK, map[string]string{"kind": "List"})
			}), func(config *Config) {
				config.ResourceScopes = resolver
			})
			response := request(t, proxy.Client(), http.MethodGet, proxy.URL+test.path, "caller")
			defer response.Body.Close()
			if response.StatusCode != http.StatusOK {
				t.Fatalf("status = %d", response.StatusCode)
			}
			authority.mu.Lock()
			defer authority.mu.Unlock()
			if scope := authority.requests[0].RequiredScope; scope.Kind != test.wantKind || len(scope.Namespaces) != 0 {
				t.Errorf("scope = %#v", scope)
			}
			if len(resolver.calls) != 1 {
				t.Fatalf("scope resolver calls = %#v", resolver.calls)
			}
		})
	}
}

func TestMissingBearerIsRejectedBeforeAuthority(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/pods", "")
	defer response.Body.Close()
	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d", response.StatusCode)
	}
	if len(authority.requests) != 0 {
		t.Fatalf("authority called %d times", len(authority.requests))
	}
}

func TestDeniedRequestIsNotForwarded(t *testing.T) {
	authority := &recordingAuthority{decision: AuthorizationResponse{Allowed: false, Reason: "standing policy denied secrets"}}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/secrets", "caller")
	defer response.Body.Close()
	if response.StatusCode != http.StatusForbidden {
		t.Fatalf("status = %d", response.StatusCode)
	}
}

func TestAuthorityFailureFailsClosed(t *testing.T) {
	authority := &recordingAuthority{status: http.StatusNotImplemented}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods", "caller")
	defer response.Body.Close()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status = %d", response.StatusCode)
	}
}

func TestAllowedDecisionRequiresDecisionIdentity(t *testing.T) {
	authority := &recordingAuthority{decision: AuthorizationResponse{Allowed: true}}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods", "caller")
	response.Body.Close()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status = %d", response.StatusCode)
	}
}

func TestAuthorityRedirectDoesNotForwardCallerBearer(t *testing.T) {
	var redirectTargetCalled atomic.Bool
	redirectTarget := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		redirectTargetCalled.Store(true)
	}))
	t.Cleanup(redirectTarget.Close)
	authority := http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		http.Redirect(w, request, redirectTarget.URL, http.StatusTemporaryRedirect)
	})
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods", "caller")
	response.Body.Close()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status = %d", response.StatusCode)
	}
	if redirectTargetCalled.Load() {
		t.Fatal("authorization client followed a redirect with the caller credential")
	}
}

func TestRequestContextEndsAtProxyRequestTimeout(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	upstreamDone := make(chan struct{})
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		<-request.Context().Done()
		close(upstreamDone)
	}), func(config *Config) {
		config.RequestTimeout = 100 * time.Millisecond
	})

	req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods/web/log", nil)
	req.Header.Set("Authorization", "Bearer caller")
	_, _ = proxy.Client().Do(req)
	select {
	case <-upstreamDone:
	case <-time.After(time.Second):
		t.Fatal("upstream request survived proxy timeout")
	}
}

func TestRequestContextEndsAtTemporaryDecisionExpiry(t *testing.T) {
	validUntil := time.Now().Add(100 * time.Millisecond)
	authority := &recordingAuthority{decision: AuthorizationResponse{
		Allowed: true, DecisionID: "grant:test", ValidUntil: &validUntil,
	}}
	upstreamDone := make(chan struct{})
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		<-request.Context().Done()
		close(upstreamDone)
	}), func(config *Config) {
		config.RequestTimeout = 5 * time.Second
	})

	req, _ := http.NewRequestWithContext(
		context.Background(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods/web/log", nil,
	)
	req.Header.Set("Authorization", "Bearer caller")
	_, _ = proxy.Client().Do(req)
	select {
	case <-upstreamDone:
	case <-time.After(time.Second):
		t.Fatal("upstream request survived temporary authorization expiry")
	}
}

func TestExpiredTemporaryDecisionIsNotForwarded(t *testing.T) {
	validUntil := time.Now().Add(-time.Second)
	authority := &recordingAuthority{decision: AuthorizationResponse{
		Allowed: true, DecisionID: "grant:expired", ValidUntil: &validUntil,
	}}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/api/v1/namespaces/demo/pods", "caller")
	response.Body.Close()
	if response.StatusCode != http.StatusForbidden {
		t.Fatalf("status = %d", response.StatusCode)
	}
}

func TestUnsupportedLongLivedAndInteractiveRequests(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)

	paths := []string{
		"/api/v1/namespaces/demo/pods?watch=true",
		"/api/v1/namespaces/demo/pods?watch=",
		"/api/v1/namespaces/demo/pods?watch=not-a-boolean",
		"/api/v1/namespaces/demo/pods?watch=false&watch=true",
		"/api/v1/namespaces/demo/pods/web/log?follow=1",
		"/api/v1/namespaces/demo/pods/web/log?follow=",
		"/api/v1/namespaces/demo/pods/web/log?follow=T",
		"/api/v1/namespaces/demo/pods/web/log?follow=not-a-boolean",
		"/api/v1/namespaces/demo/pods/web/exec",
		"/api/v1/namespaces/demo/pods/web/attach",
		"/api/v1/namespaces/demo/pods/web/portforward",
		"/api/v1/namespaces/demo/pods/web/proxy/path",
	}
	for _, path := range paths {
		response := request(t, proxy.Client(), http.MethodGet, proxy.URL+path, "caller")
		response.Body.Close()
		if response.StatusCode != http.StatusNotImplemented {
			t.Errorf("%s status = %d", path, response.StatusCode)
		}
	}
	if len(authority.requests) != 0 {
		t.Fatalf("authority called for unsupported request")
	}
}

func TestUnknownResourceMethodIsRejected(t *testing.T) {
	authority := &recordingAuthority{decision: allowedDecision()}
	proxy := newTestProxy(t, authority, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodOptions, proxy.URL+"/api/v1/namespaces/demo/pods", "caller")
	response.Body.Close()
	if response.StatusCode != http.StatusNotImplemented {
		t.Fatalf("status = %d", response.StatusCode)
	}
	if len(authority.requests) != 0 {
		t.Fatal("authority called for an unmapped method")
	}
}

func TestHealthDoesNotRequireAuthorization(t *testing.T) {
	proxy := newTestProxy(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Fatal("authority called")
	}), http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("upstream called")
	}), nil)
	response := request(t, proxy.Client(), http.MethodGet, proxy.URL+"/healthz", "")
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", response.StatusCode)
	}
}

func TestPlainHTTPAuthorityRequiresExplicitDevelopmentOptIn(t *testing.T) {
	upstream, _ := url.Parse("https://kubernetes.test")
	authority, _ := url.Parse("http://console.test/api/internal/kubernetes/authorize")
	if _, err := NewHandler(Config{Upstream: upstream, AuthorizationURL: authority}); err == nil {
		t.Fatal("plain HTTP authority was accepted without explicit opt-in")
	}
}
