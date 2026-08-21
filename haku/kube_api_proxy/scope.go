package kubeapiproxy

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sync"
	"time"
)

const (
	grantScopeNamespaces    = "namespaces"
	grantScopeAllNamespaces = "all_namespaces"
	grantScopeCluster       = "cluster"
	grantScopeNonResource   = "non_resource"

	discoveryCacheTTL        = 5 * time.Minute
	maxDiscoveryResponseSize = 4 << 20
)

// GrantScope is the explicit scope required by one canonical Kubernetes request.
type GrantScope struct {
	Kind       string   `json:"kind"`
	Namespaces []string `json:"namespaces"`
}

// ResourceScopeResolver distinguishes all-namespaces resource requests from cluster resources.
// Kubernetes request paths alone cannot distinguish /api/v1/pods from /api/v1/nodes.
type ResourceScopeResolver interface {
	ResourceNamespaced(ctx context.Context, apiGroup string, apiVersion string, resource string) (bool, error)
}

type discoveryScopeResolver struct {
	upstream *url.URL
	client   *http.Client
	now      func() time.Time

	mu    sync.Mutex
	cache map[resourceScopeKey]resourceScopeCacheEntry
}

type resourceScopeKey struct {
	apiGroup   string
	apiVersion string
	resource   string
}

type resourceScopeCacheEntry struct {
	namespaced bool
	expiresAt  time.Time
}

type apiResourceList struct {
	Resources []apiResource `json:"resources"`
}

type apiResource struct {
	Name       string `json:"name"`
	Namespaced bool   `json:"namespaced"`
}

func newDiscoveryScopeResolver(upstream *url.URL, transport http.RoundTripper) ResourceScopeResolver {
	client := &http.Client{
		Transport: transport,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	return &discoveryScopeResolver{
		upstream: upstream,
		client:   client,
		now:      time.Now,
		cache:    make(map[resourceScopeKey]resourceScopeCacheEntry),
	}
}

func (resolver *discoveryScopeResolver) ResourceNamespaced(
	ctx context.Context, apiGroup string, apiVersion string, resource string,
) (bool, error) {
	key := resourceScopeKey{apiGroup: apiGroup, apiVersion: apiVersion, resource: resource}
	now := resolver.now()
	resolver.mu.Lock()
	cached, ok := resolver.cache[key]
	resolver.mu.Unlock()
	if ok && now.Before(cached.expiresAt) {
		return cached.namespaced, nil
	}

	path := "/api/" + url.PathEscape(apiVersion)
	if apiGroup != "" {
		path = "/apis/" + url.PathEscape(apiGroup) + "/" + url.PathEscape(apiVersion)
	}
	endpoint := resolver.upstream.ResolveReference(&url.URL{Path: path})
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return false, fmt.Errorf("construct Kubernetes discovery request: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	response, err := resolver.client.Do(request)
	if err != nil {
		return false, fmt.Errorf("Kubernetes discovery unavailable: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false, fmt.Errorf("Kubernetes discovery returned %s", response.Status)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxDiscoveryResponseSize+1))
	if err != nil {
		return false, fmt.Errorf("read Kubernetes discovery response: %w", err)
	}
	if len(body) > maxDiscoveryResponseSize {
		return false, errors.New("Kubernetes discovery response is too large")
	}
	var list apiResourceList
	if err := json.Unmarshal(body, &list); err != nil {
		return false, fmt.Errorf("decode Kubernetes discovery response: %w", err)
	}
	for _, item := range list.Resources {
		if item.Name != resource {
			continue
		}
		resolver.mu.Lock()
		resolver.cache[key] = resourceScopeCacheEntry{
			namespaced: item.Namespaced,
			expiresAt:  now.Add(discoveryCacheTTL),
		}
		resolver.mu.Unlock()
		return item.Namespaced, nil
	}
	return false, fmt.Errorf(
		"Kubernetes discovery did not report resource %q in %q/%q", resource, apiGroup, apiVersion,
	)
}

func requiredGrantScope(
	ctx context.Context, resolver ResourceScopeResolver, attributes RequestAttributes,
) (GrantScope, error) {
	if !attributes.ResourceRequest {
		return GrantScope{Kind: grantScopeNonResource, Namespaces: []string{}}, nil
	}
	if attributes.Namespace != "" {
		return GrantScope{Kind: grantScopeNamespaces, Namespaces: []string{attributes.Namespace}}, nil
	}
	if attributes.APIVersion == "" || attributes.Resource == "" {
		return GrantScope{}, errors.New("resource scope requires API version and resource")
	}
	namespaced, err := resolver.ResourceNamespaced(
		ctx, attributes.APIGroup, attributes.APIVersion, attributes.Resource,
	)
	if err != nil {
		return GrantScope{}, err
	}
	if namespaced {
		return GrantScope{Kind: grantScopeAllNamespaces, Namespaces: []string{}}, nil
	}
	return GrantScope{Kind: grantScopeCluster, Namespaces: []string{}}, nil
}
