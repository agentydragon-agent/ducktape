/*
Copyright 2016 The Kubernetes Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package kubeapiproxy

// This file is a deliberately small adaptation of Kubernetes apiserver's
// pkg/endpoints/request/requestinfo.go at v0.34.1. Keeping the request-path
// algorithm local avoids importing the entire apiserver dependency graph into
// a small security proxy. Differences from upstream are called out below.

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

// RequestInfo is the subset of upstream RequestInfo used by this proxy.
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

// RequestInfoFactory matches Kubernetes' /api and /apis request layout.
type RequestInfoFactory struct{}

var (
	specialVerbs               = map[string]bool{"proxy": true, "watch": true}
	specialVerbsNoSubresources = map[string]bool{"proxy": true}
	namespaceSubresources      = map[string]bool{"status": true, "finalize": true}
)

// NewRequestInfo is adapted from Kubernetes' RequestInfoFactory.NewRequestInfo.
func (*RequestInfoFactory) NewRequestInfo(request *http.Request) (*RequestInfo, error) {
	info := RequestInfo{
		Path: request.URL.Path,
		Verb: strings.ToLower(request.Method),
	}
	parts := splitPath(request.URL.Path)
	if len(parts) < 3 || (parts[0] != "api" && parts[0] != "apis") {
		return &info, nil
	}

	info.APIPrefix = parts[0]
	parts = parts[1:]
	if info.APIPrefix != "api" {
		if len(parts) < 3 {
			return &info, nil
		}
		info.APIGroup = parts[0]
		parts = parts[1:]
	}
	if len(parts) < 2 {
		return &info, nil
	}

	info.IsResourceRequest = true
	info.APIVersion = parts[0]
	parts = parts[1:]

	if specialVerbs[parts[0]] {
		if len(parts) < 2 {
			return &info, fmt.Errorf("unable to determine resource and namespace from URL %s", request.URL)
		}
		info.Verb = parts[0]
		parts = parts[1:]
	} else {
		switch request.Method {
		case http.MethodPost:
			info.Verb = "create"
		case http.MethodGet, http.MethodHead:
			info.Verb = "get"
		case http.MethodPut:
			info.Verb = "update"
		case http.MethodPatch:
			info.Verb = "patch"
		case http.MethodDelete:
			info.Verb = "delete"
		default:
			info.Verb = ""
		}
	}

	if len(parts) == 0 {
		return &info, fmt.Errorf("unable to determine resource from URL %s", request.URL)
	}
	if parts[0] == "namespaces" && len(parts) > 1 {
		info.Namespace = parts[1]
		if len(parts) > 2 && !namespaceSubresources[parts[2]] {
			parts = parts[2:]
		}
	}

	info.Parts = append([]string(nil), parts...)
	if len(info.Parts) >= 1 {
		info.Resource = info.Parts[0]
	}
	if len(info.Parts) >= 2 {
		info.Name = info.Parts[1]
	}
	if len(info.Parts) >= 3 && !specialVerbsNoSubresources[info.Verb] {
		info.Subresource = info.Parts[2]
	}

	query := request.URL.Query()
	if info.Name == "" && info.Verb == "get" {
		if queryMayEnable(query["watch"]) {
			info.Verb = "watch"
		} else {
			info.Verb = "list"
		}
		// Upstream also derives Name from an exactly matching metadata.name
		// field selector. We intentionally do not: treating that request as list
		// asks Haku for a broader permission and therefore fails conservatively.
		// TODO(#4428): reuse apimachinery's selector parser if field-selected
		// resourceNames become important enough to justify that dependency.
	}
	if info.Name == "" && info.Verb == "delete" {
		info.Verb = "deletecollection"
	}
	if info.Verb == "list" || info.Verb == "watch" || info.Verb == "deletecollection" {
		info.FieldSelector = query.Get("fieldSelector")
		info.LabelSelector = query.Get("labelSelector")
	}
	return &info, nil
}

func splitPath(path string) []string {
	trimmed := strings.Trim(path, "/")
	if trimmed == "" {
		return nil
	}
	return strings.Split(trimmed, "/")
}
