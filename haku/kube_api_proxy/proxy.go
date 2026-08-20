// Package kubeapiproxy implements an approval-aware reverse proxy for the
// Kubernetes API. Request parsing uses Kubernetes apiserver's
// RequestInfoFactory so authorization follows kube-apiserver's own
// resource/verb interpretation.
package kubeapiproxy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

const (
	defaultAuthorizationTimeout = 3 * time.Second
	defaultRequestTimeout       = 30 * time.Second
	defaultMaxRequestBytes      = 10 << 20
)

// RequestAttributes is the canonical request shape sent to Haku Console.
type RequestAttributes struct {
	ResourceRequest bool   `json:"resource_request"`
	Verb            string `json:"verb"`
	APIGroup        string `json:"api_group,omitempty"`
	APIVersion      string `json:"api_version,omitempty"`
	Namespace       string `json:"namespace,omitempty"`
	Resource        string `json:"resource,omitempty"`
	Subresource     string `json:"subresource,omitempty"`
	Name            string `json:"name,omitempty"`
	Path            string `json:"path"`
	FieldSelector   string `json:"field_selector,omitempty"`
	LabelSelector   string `json:"label_selector,omitempty"`
}

// PolicyRule is the minimal Kubernetes RBAC rule required by one request.
type PolicyRule struct {
	APIGroups       []string `json:"api_groups,omitempty"`
	Resources       []string `json:"resources,omitempty"`
	Verbs           []string `json:"verbs"`
	ResourceNames   []string `json:"resource_names,omitempty"`
	NonResourceURLs []string `json:"non_resource_urls,omitempty"`
}

// AuthorizationRequest is the proxy-to-Console authorization contract.
type AuthorizationRequest struct {
	Attributes    RequestAttributes `json:"attributes"`
	RequiredRules []PolicyRule      `json:"required_rules"`
}

// AuthorizationResponse is returned by Haku Console after a Kubernetes
// SubjectAccessReview for the fixed deploy-configured subject.
type AuthorizationResponse struct {
	Allowed    bool       `json:"allowed"`
	Reason     string     `json:"reason,omitempty"`
	DecisionID string     `json:"decision_id,omitempty"`
	ValidUntil *time.Time `json:"valid_until,omitempty"`
}

// Config contains proxy-only configuration. Agent authority and Kubernetes
// authorization state intentionally remain Haku Console/Kubernetes responsibilities.
type Config struct {
	Upstream            *url.URL
	UpstreamTransport   http.RoundTripper
	AuthorizationURL    *url.URL
	AuthorizationClient *http.Client
	// AllowInsecureAuthorization is test/development-only. Production must
	// authenticate Console over TLS because this hop carries the Agent bearer.
	AllowInsecureAuthorization bool
	AuthorizationTimeout       time.Duration
	RequestTimeout             time.Duration
	MaxRequestBytes            int64
	Logger                     *slog.Logger
}

// NewHandler returns the complete proxy HTTP handler.
func NewHandler(config Config) (http.Handler, error) {
	if config.Upstream == nil || config.Upstream.Scheme == "" || config.Upstream.Host == "" {
		return nil, errors.New("Kubernetes upstream URL is required")
	}
	if config.AuthorizationURL == nil || config.AuthorizationURL.Scheme == "" || config.AuthorizationURL.Host == "" {
		return nil, errors.New("Haku authorization URL is required")
	}
	if config.AuthorizationURL.Scheme != "https" && !config.AllowInsecureAuthorization {
		return nil, errors.New("Haku authorization URL must use https")
	}
	if config.UpstreamTransport == nil {
		config.UpstreamTransport = http.DefaultTransport
	}
	if config.AuthorizationClient == nil {
		config.AuthorizationClient = http.DefaultClient
	}
	// Never follow an authority redirect with the caller's bearer. A redirect is
	// an authority failure, not a new place to disclose an Agent credential.
	authorizationClient := *config.AuthorizationClient
	authorizationClient.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	config.AuthorizationClient = &authorizationClient
	if config.AuthorizationTimeout <= 0 {
		config.AuthorizationTimeout = defaultAuthorizationTimeout
	}
	if config.RequestTimeout <= 0 {
		config.RequestTimeout = defaultRequestTimeout
	}
	if config.MaxRequestBytes <= 0 {
		config.MaxRequestBytes = defaultMaxRequestBytes
	}
	if config.Logger == nil {
		config.Logger = slog.Default()
	}

	resolver := newRequestInfoResolver()

	upstream := *config.Upstream
	reverseProxy := &httputil.ReverseProxy{
		Rewrite: func(proxyRequest *httputil.ProxyRequest) {
			proxyRequest.SetURL(&upstream)
			proxyRequest.Out.Host = upstream.Host
			// Forward only ordinary Kubernetes HTTP representation headers. The
			// caller's Haku credential, cookies, proxy metadata, API keys and
			// identity/impersonation headers must never reach kube-apiserver. The
			// configured transport adds the proxy's own Kubernetes credential.
			proxyRequest.Out.Header = upstreamHeaders(proxyRequest.Out.Header)
		},
		Transport: config.UpstreamTransport,
		ErrorHandler: func(w http.ResponseWriter, _ *http.Request, err error) {
			config.Logger.Error("Kubernetes upstream request failed", "error", err)
			http.Error(w, "Kubernetes API unavailable", http.StatusBadGateway)
		},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		serve(config, resolver, reverseProxy, w, request)
	}))
	return mux, nil
}

func serve(config Config, resolver RequestInfoResolver, upstream http.Handler, w http.ResponseWriter, request *http.Request) {
	authorization := request.Header.Get("Authorization")
	if !strings.HasPrefix(authorization, "Bearer ") || strings.TrimSpace(strings.TrimPrefix(authorization, "Bearer ")) == "" {
		http.Error(w, "Bearer authorization is required", http.StatusUnauthorized)
		return
	}
	if reason := unsupportedReason(request); reason != "" {
		writeJSON(w, http.StatusNotImplemented, map[string]string{"error": reason})
		return
	}

	if request.ContentLength > config.MaxRequestBytes {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "Kubernetes request body is too large"})
		return
	}
	request.Body = http.MaxBytesReader(w, request.Body, config.MaxRequestBytes)
	info, err := resolver.NewRequestInfo(request)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("cannot classify Kubernetes request: %v", err)})
		return
	}
	attributes := attributesFrom(info)
	if reason := unsupportedAttributes(attributes, request); reason != "" {
		writeJSON(w, http.StatusNotImplemented, map[string]string{"error": reason})
		return
	}

	decision, status, err := authorize(request.Context(), config, authorization, AuthorizationRequest{
		Attributes:    attributes,
		RequiredRules: []PolicyRule{requiredRule(attributes)},
	})
	if err != nil {
		config.Logger.Error("Haku authorization failed closed", "error", err)
		writeJSON(w, status, map[string]string{"error": err.Error()})
		return
	}
	if !decision.Allowed {
		reason := decision.Reason
		if reason == "" {
			reason = "Kubernetes standing policy denied this request"
		}
		config.Logger.Warn(
			"Kubernetes request denied",
			"decision_id", decision.DecisionID,
			"verb", attributes.Verb,
			"resource_request", attributes.ResourceRequest,
			"api_group", attributes.APIGroup,
			"namespace", attributes.Namespace,
			"resource", attributes.Resource,
			"subresource", attributes.Subresource,
			"name", attributes.Name,
			"path", attributes.Path,
			"reason", reason,
		)
		writeJSON(w, http.StatusForbidden, map[string]string{"error": reason})
		return
	}
	config.Logger.Info(
		"Kubernetes request authorized",
		"decision_id", decision.DecisionID,
		"valid_until", decision.ValidUntil,
		"verb", attributes.Verb,
		"resource_request", attributes.ResourceRequest,
		"api_group", attributes.APIGroup,
		"namespace", attributes.Namespace,
		"resource", attributes.Resource,
		"subresource", attributes.Subresource,
		"name", attributes.Name,
		"path", attributes.Path,
	)
	w.Header().Set("X-Haku-Kubernetes-Decision-ID", decision.DecisionID)

	deadline := time.Now().Add(config.RequestTimeout)
	if decision.ValidUntil != nil && decision.ValidUntil.Before(deadline) {
		deadline = *decision.ValidUntil
	}
	if !deadline.After(time.Now()) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "the Haku authorization decision has expired"})
		return
	}

	ctx, cancel := context.WithDeadline(request.Context(), deadline)
	defer cancel()
	upstream.ServeHTTP(w, request.WithContext(ctx))
}

func authorize(ctx context.Context, config Config, bearer string, body AuthorizationRequest) (AuthorizationResponse, int, error) {
	encoded, err := json.Marshal(body)
	if err != nil {
		return AuthorizationResponse{}, http.StatusInternalServerError, fmt.Errorf("encode authorization request: %w", err)
	}
	authorizationCtx, cancel := context.WithTimeout(ctx, config.AuthorizationTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(authorizationCtx, http.MethodPost, config.AuthorizationURL.String(), bytes.NewReader(encoded))
	if err != nil {
		return AuthorizationResponse{}, http.StatusInternalServerError, fmt.Errorf("construct authorization request: %w", err)
	}
	req.Header.Set("Authorization", bearer)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	response, err := config.AuthorizationClient.Do(req)
	if err != nil {
		return AuthorizationResponse{}, http.StatusServiceUnavailable, fmt.Errorf("Kubernetes authorization authority unavailable: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
		return AuthorizationResponse{}, response.StatusCode, fmt.Errorf("Haku rejected the caller credential")
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return AuthorizationResponse{}, http.StatusServiceUnavailable, fmt.Errorf("Kubernetes authorization authority returned %s", response.Status)
	}
	limited := io.LimitReader(response.Body, 1<<20)
	var decision AuthorizationResponse
	decoder := json.NewDecoder(limited)
	if err := decoder.Decode(&decision); err != nil {
		return AuthorizationResponse{}, http.StatusServiceUnavailable, fmt.Errorf("invalid Kubernetes authorization response: %w", err)
	}
	var trailing json.RawMessage
	if err := decoder.Decode(&trailing); err != io.EOF {
		return AuthorizationResponse{}, http.StatusServiceUnavailable, errors.New("invalid Kubernetes authorization response: trailing JSON")
	}
	if decision.Allowed && strings.TrimSpace(decision.DecisionID) == "" {
		return AuthorizationResponse{}, http.StatusServiceUnavailable, errors.New("invalid Kubernetes authorization response: allowed decision has no decision_id")
	}
	return decision, http.StatusOK, nil
}

func attributesFrom(info *RequestInfo) RequestAttributes {
	return RequestAttributes{
		ResourceRequest: info.IsResourceRequest,
		Verb:            info.Verb,
		APIGroup:        info.APIGroup,
		APIVersion:      info.APIVersion,
		Namespace:       info.Namespace,
		Resource:        info.Resource,
		Subresource:     info.Subresource,
		Name:            info.Name,
		Path:            info.Path,
		FieldSelector:   info.FieldSelector,
		LabelSelector:   info.LabelSelector,
	}
}

func requiredRule(attributes RequestAttributes) PolicyRule {
	if !attributes.ResourceRequest {
		return PolicyRule{Verbs: []string{attributes.Verb}, NonResourceURLs: []string{attributes.Path}}
	}
	resource := attributes.Resource
	if attributes.Subresource != "" {
		resource += "/" + attributes.Subresource
	}
	rule := PolicyRule{
		APIGroups: []string{attributes.APIGroup},
		Resources: []string{resource},
		Verbs:     []string{attributes.Verb},
	}
	if attributes.Name != "" {
		rule.ResourceNames = []string{attributes.Name}
	}
	return rule
}

func unsupportedReason(request *http.Request) string {
	if request.Method == http.MethodConnect {
		return "CONNECT tunneling is not implemented"
	}
	if request.Header.Get("Upgrade") != "" || headerContainsToken(request.Header, "Connection", "upgrade") {
		return "upgraded connections are not implemented"
	}
	return ""
}

func unsupportedAttributes(attributes RequestAttributes, request *http.Request) string {
	if attributes.Verb == "" {
		return "this HTTP method is not mapped to a Kubernetes authorization verb"
	}
	if attributes.Verb == "watch" || queryMayEnable(request.URL.Query()["watch"]) {
		return "Kubernetes watch requests are not implemented"
	}
	if attributes.Verb == "proxy" || attributes.Subresource == "proxy" {
		return "Kubernetes resource proxy requests are not implemented"
	}
	if attributes.Resource == "pods" {
		switch attributes.Subresource {
		case "exec", "attach", "portforward":
			return "interactive pod subresources are not implemented"
		case "log":
			if queryMayEnable(request.URL.Query()["follow"]) {
				return "following pod logs is not implemented"
			}
		}
	}
	return ""
}

var forwardedRequestHeaders = map[string]bool{
	"Accept":            true,
	"Accept-Encoding":   true,
	"Accept-Language":   true,
	"Cache-Control":     true,
	"Content-Encoding":  true,
	"Content-Type":      true,
	"If-Match":          true,
	"If-Modified-Since": true,
	"If-None-Match":     true,
	"Pragma":            true,
	"Range":             true,
	"User-Agent":        true,
}

func upstreamHeaders(source http.Header) http.Header {
	result := make(http.Header, len(forwardedRequestHeaders))
	for name, values := range source {
		canonical := http.CanonicalHeaderKey(name)
		if forwardedRequestHeaders[canonical] {
			result[canonical] = append([]string(nil), values...)
		}
	}
	return result
}

func headerContainsToken(header http.Header, name string, token string) bool {
	for _, value := range header.Values(name) {
		for _, part := range strings.Split(value, ",") {
			if strings.EqualFold(strings.TrimSpace(part), token) {
				return true
			}
		}
	}
	return false
}

// queryMayEnable is intentionally conservative: Kubernetes' request parsers
// accept several true spellings and, for watch, fall back to true for every
// non-empty value except the explicit false forms when decoding fails. Rejecting
// an invalid value is safe; forwarding a stream misclassified as ordinary is not.
func queryMayEnable(values []string) bool {
	if len(values) == 0 {
		return false
	}
	// Duplicate values are ambiguous across decoders; reject them rather than
	// authorize one interpretation and forward another.
	if len(values) != 1 {
		return true
	}
	switch strings.ToLower(strings.TrimSpace(values[0])) {
	case "0", "false":
		return false
	default:
		return true
	}
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
