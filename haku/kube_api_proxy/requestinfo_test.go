package kubeapiproxy

import (
	"net/http"
	"testing"
)

func TestRequestInfoMatchesKubernetesResourceShapes(t *testing.T) {
	tests := []struct {
		method      string
		path        string
		verb        string
		group       string
		namespace   string
		resource    string
		subresource string
		name        string
	}{
		{http.MethodGet, "/apis/apps/v1/namespaces/prod/deployments/web/scale", "get", "apps", "prod", "deployments", "scale", "web"},
		{http.MethodPost, "/api/v1/namespaces/prod/configmaps", "create", "", "prod", "configmaps", "", ""},
		{http.MethodDelete, "/api/v1/namespaces/prod/pods", "deletecollection", "", "prod", "pods", "", ""},
		{http.MethodGet, "/api/v1/watch/namespaces/prod/pods", "watch", "", "prod", "pods", "", ""},
		{http.MethodGet, "/apis/apps/v1/deployments", "list", "apps", "", "deployments", "", ""},
		{http.MethodPatch, "/api/v1/namespaces/prod/pods/web/status", "patch", "", "prod", "pods", "status", "web"},
		{http.MethodHead, "/api/v1/nodes/worker-1", "get", "", "", "nodes", "", "worker-1"},
	}

	resolver := &RequestInfoFactory{}
	for _, test := range tests {
		request, err := http.NewRequest(test.method, "https://proxy.test"+test.path, nil)
		if err != nil {
			t.Fatal(err)
		}
		got, err := resolver.NewRequestInfo(request)
		if err != nil {
			t.Fatalf("%s %s: %v", test.method, test.path, err)
		}
		if !got.IsResourceRequest || got.Verb != test.verb || got.APIGroup != test.group || got.Namespace != test.namespace || got.Resource != test.resource || got.Subresource != test.subresource || got.Name != test.name {
			t.Errorf("%s %s: got %#v", test.method, test.path, got)
		}
	}
}

func TestRequestInfoTreatsDiscoveryAsNonResource(t *testing.T) {
	resolver := &RequestInfoFactory{}
	for _, path := range []string{"/", "/api", "/apis", "/apis/apps/v1", "/version", "/openapi/v3"} {
		request, _ := http.NewRequest(http.MethodGet, "https://proxy.test"+path, nil)
		got, err := resolver.NewRequestInfo(request)
		if err != nil {
			t.Fatal(err)
		}
		if got.IsResourceRequest || got.Verb != "get" || got.Path != path {
			t.Errorf("%s: got %#v", path, got)
		}
		rule := requiredRule(attributesFrom(got))
		if len(rule.NonResourceURLs) != 1 || rule.NonResourceURLs[0] != path {
			t.Errorf("%s: rule %#v", path, rule)
		}
	}
}

func TestAmbiguousWatchValuesFailConservativelyAsWatch(t *testing.T) {
	for _, query := range []string{"watch=", "watch=garbage", "watch=on", "watch=false&watch=true"} {
		request, _ := http.NewRequest(http.MethodGet, "https://proxy.test/api/v1/pods?"+query, nil)
		got, err := (&RequestInfoFactory{}).NewRequestInfo(request)
		if err != nil {
			t.Fatal(err)
		}
		if got.Verb != "watch" {
			t.Errorf("%s: verb = %q, want watch", query, got.Verb)
		}
	}
}
