package kubeapiproxy

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

type staticResourceScopes struct {
	namespaced bool
	err        error
	calls      []resourceScopeKey
}

func (scopes *staticResourceScopes) ResourceNamespaced(
	_ context.Context, apiGroup string, apiVersion string, resource string,
) (bool, error) {
	scopes.calls = append(scopes.calls, resourceScopeKey{apiGroup: apiGroup, apiVersion: apiVersion, resource: resource})
	return scopes.namespaced, scopes.err
}

func TestRequiredGrantScopeDistinguishesEveryScopeKind(t *testing.T) {
	named, err := requiredGrantScope(context.Background(), &staticResourceScopes{}, RequestAttributes{
		ResourceRequest: true, APIVersion: "v1", Namespace: "demo", Resource: "pods",
	})
	if err != nil || named.Kind != grantScopeNamespaces || strings.Join(named.Namespaces, ",") != "demo" {
		t.Fatalf("named namespace scope = %#v, error = %v", named, err)
	}

	namespacedResolver := &staticResourceScopes{namespaced: true}
	allNamespaces, err := requiredGrantScope(context.Background(), namespacedResolver, RequestAttributes{
		ResourceRequest: true, APIVersion: "v1", Resource: "pods",
	})
	if err != nil || allNamespaces.Kind != grantScopeAllNamespaces || len(allNamespaces.Namespaces) != 0 {
		t.Fatalf("all-namespaces scope = %#v, error = %v", allNamespaces, err)
	}

	clusterResolver := &staticResourceScopes{namespaced: false}
	cluster, err := requiredGrantScope(context.Background(), clusterResolver, RequestAttributes{
		ResourceRequest: true, APIGroup: "rbac.authorization.k8s.io", APIVersion: "v1", Resource: "clusterroles",
	})
	if err != nil || cluster.Kind != grantScopeCluster || len(cluster.Namespaces) != 0 {
		t.Fatalf("cluster scope = %#v, error = %v", cluster, err)
	}

	nonResource, err := requiredGrantScope(context.Background(), &staticResourceScopes{}, RequestAttributes{
		Verb: "get", Path: "/version",
	})
	if err != nil || nonResource.Kind != grantScopeNonResource || len(nonResource.Namespaces) != 0 {
		t.Fatalf("non-resource scope = %#v, error = %v", nonResource, err)
	}
}

func TestGrantScopeJSONOmitsNamespacesOutsideExactNamespaceScope(t *testing.T) {
	tests := []struct {
		name  string
		scope GrantScope
		want  string
	}{
		{
			name:  "exact namespaces",
			scope: GrantScope{Kind: grantScopeNamespaces, Namespaces: []string{"demo"}},
			want:  `{"kind":"namespaces","namespaces":["demo"]}`,
		},
		{name: "all namespaces", scope: GrantScope{Kind: grantScopeAllNamespaces}, want: `{"kind":"all_namespaces"}`},
		{name: "cluster", scope: GrantScope{Kind: grantScopeCluster}, want: `{"kind":"cluster"}`},
		{name: "non resource", scope: GrantScope{Kind: grantScopeNonResource}, want: `{"kind":"non_resource"}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := json.Marshal(test.scope)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != test.want {
				t.Fatalf("GrantScope JSON = %s, want %s", got, test.want)
			}
		})
	}
}

func TestDiscoveryScopeResolverUsesAuthenticatedUpstreamAndCaches(t *testing.T) {
	var calls int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		calls++
		if request.URL.Path != "/apis/apps/v1" {
			t.Errorf("discovery path = %q", request.URL.Path)
		}
		if request.Header.Get("Authorization") != "Bearer proxy-token" {
			t.Errorf("discovery authorization = %q", request.Header.Get("Authorization"))
		}
		_, _ = io.WriteString(w, `{"resources":[{"name":"deployments","namespaced":true}]}`)
	}))
	defer server.Close()
	upstream, _ := url.Parse(server.URL)
	resolver := newDiscoveryScopeResolver(
		upstream,
		bearerTransport{base: http.DefaultTransport, token: "proxy-token"},
	)
	for range 2 {
		namespaced, err := resolver.ResourceNamespaced(context.Background(), "apps", "v1", "deployments")
		if err != nil || !namespaced {
			t.Fatalf("namespaced = %v, error = %v", namespaced, err)
		}
	}
	if calls != 1 {
		t.Fatalf("discovery calls = %d, want 1", calls)
	}
}

func TestDiscoveryScopeResolverFailsClosedForUnknownResource(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, `{"resources":[{"name":"pods","namespaced":true}]}`)
	}))
	defer server.Close()
	upstream, _ := url.Parse(server.URL)
	resolver := newDiscoveryScopeResolver(upstream, http.DefaultTransport)
	if _, err := resolver.ResourceNamespaced(context.Background(), "", "v1", "nodes"); err == nil {
		t.Fatal("unknown resource was accepted")
	}
}
