package kubeapiproxy

import (
	"fmt"
	"net/http"
	"strings"
)

// RequestInfoResolver maps one HTTP request to Kubernetes authorization
// attributes.
type RequestInfoResolver interface {
	NewRequestInfo(*http.Request) (*RequestInfo, error)
}

// RequestInfo contains the request-path fields needed to derive an RBAC rule.
type RequestInfo struct {
	IsResourceRequest bool
	Path              string
	Verb              string
	APIPrefix         string
	APIGroup          string
	APIVersion        string
	Namespace         string
	Resource          string
	Subresource       string
	Name              string
	Parts             []string
	FieldSelector     string
	LabelSelector     string
}

// RequestInfoFactory classifies the conventional /api and /apis URL grammars.
type RequestInfoFactory struct{}

type apiPath struct {
	prefix  string
	group   string
	version string
	parts   []string
}

func (*RequestInfoFactory) NewRequestInfo(request *http.Request) (*RequestInfo, error) {
	info := &RequestInfo{
		Path: request.URL.Path,
		Verb: strings.ToLower(request.Method),
	}
	path, ok := parseAPIPath(request.URL.Path)
	if !ok {
		return info, nil
	}

	info.IsResourceRequest = true
	info.APIPrefix = path.prefix
	info.APIGroup = path.group
	info.APIVersion = path.version

	parts := path.parts
	if isPathVerb(parts[0]) {
		if len(parts) == 1 {
			return info, fmt.Errorf("unable to determine resource and namespace from URL %s", request.URL)
		}
		info.Verb = parts[0]
		parts = parts[1:]
	} else {
		info.Verb = resourceVerb(request.Method)
	}

	parts = classifyNamespace(info, parts)
	if len(parts) == 0 {
		return info, fmt.Errorf("unable to determine resource from URL %s", request.URL)
	}
	info.Parts = append([]string(nil), parts...)
	info.Resource = parts[0]
	if len(parts) > 1 {
		info.Name = parts[1]
	}
	if len(parts) > 2 && info.Verb != "proxy" {
		info.Subresource = parts[2]
	}

	query := request.URL.Query()
	if info.Name == "" && info.Verb == "get" {
		if queryMayEnable(query["watch"]) {
			info.Verb = "watch"
		} else {
			info.Verb = "list"
		}
		// An exact metadata.name selector could narrow this to get. Keeping list
		// requests broader is conservative until selector parsing is shared with
		// Kubernetes rather than approximated here.
	}
	if info.Name == "" && info.Verb == "delete" {
		info.Verb = "deletecollection"
	}
	if verbSupportsSelectors(info.Verb) {
		info.FieldSelector = query.Get("fieldSelector")
		info.LabelSelector = query.Get("labelSelector")
	}
	return info, nil
}

func parseAPIPath(rawPath string) (apiPath, bool) {
	parts := splitPath(rawPath)
	if len(parts) < 3 {
		return apiPath{}, false
	}
	switch parts[0] {
	case "api":
		return apiPath{prefix: "api", version: parts[1], parts: parts[2:]}, true
	case "apis":
		if len(parts) < 4 {
			return apiPath{}, false
		}
		return apiPath{prefix: "apis", group: parts[1], version: parts[2], parts: parts[3:]}, true
	default:
		return apiPath{}, false
	}
}

func classifyNamespace(info *RequestInfo, parts []string) []string {
	if len(parts) < 2 || parts[0] != "namespaces" {
		return parts
	}
	info.Namespace = parts[1]
	if len(parts) > 2 && parts[2] != "status" && parts[2] != "finalize" {
		return parts[2:]
	}
	return parts
}

func resourceVerb(method string) string {
	switch method {
	case http.MethodPost:
		return "create"
	case http.MethodGet, http.MethodHead:
		return "get"
	case http.MethodPut:
		return "update"
	case http.MethodPatch:
		return "patch"
	case http.MethodDelete:
		return "delete"
	default:
		return ""
	}
}

func isPathVerb(part string) bool {
	return part == "proxy" || part == "watch"
}

func verbSupportsSelectors(verb string) bool {
	return verb == "list" || verb == "watch" || verb == "deletecollection"
}

func splitPath(path string) []string {
	trimmed := strings.Trim(path, "/")
	if trimmed == "" {
		return nil
	}
	return strings.Split(trimmed, "/")
}
