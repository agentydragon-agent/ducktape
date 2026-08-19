// Copyright 2026 agentydragon
// SPDX-License-Identifier: Apache-2.0

package kubeapiproxy

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

const defaultServiceAccountDirectory = "/var/run/secrets/kubernetes.io/serviceaccount"

// InClusterUpstream builds the API URL and rotating ServiceAccount bearer
// transport from Kubernetes' standard projected files. This is the small
// subset of client-go/rest.InClusterConfig needed by this proxy.
func InClusterUpstream() (*url.URL, http.RoundTripper, error) {
	host := os.Getenv("KUBERNETES_SERVICE_HOST")
	port := os.Getenv("KUBERNETES_SERVICE_PORT_HTTPS")
	if port == "" {
		port = os.Getenv("KUBERNETES_SERVICE_PORT")
	}
	if host == "" || port == "" {
		return nil, nil, fmt.Errorf("KUBERNETES_SERVICE_HOST and KUBERNETES_SERVICE_PORT_HTTPS are required")
	}

	serviceAccountDirectory := os.Getenv("HAKU_KUBE_SERVICEACCOUNT_DIRECTORY")
	if serviceAccountDirectory == "" {
		serviceAccountDirectory = defaultServiceAccountDirectory
	}
	caFile := filepath.Join(serviceAccountDirectory, "ca.crt")
	caPEM, err := os.ReadFile(caFile)
	if err != nil {
		return nil, nil, fmt.Errorf("read Kubernetes CA %s: %w", caFile, err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(caPEM) {
		return nil, nil, fmt.Errorf("Kubernetes CA %s contains no certificates", caFile)
	}
	upstream, err := url.Parse("https://" + net.JoinHostPort(strings.Trim(host, "[]"), port))
	if err != nil {
		return nil, nil, fmt.Errorf("construct Kubernetes API URL: %w", err)
	}
	base := &http.Transport{
		TLSClientConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
			RootCAs:    roots,
		},
		ForceAttemptHTTP2: true,
	}
	return upstream, &serviceAccountTransport{
		base:      base,
		tokenFile: filepath.Join(serviceAccountDirectory, "token"),
	}, nil
}

type serviceAccountTransport struct {
	base      http.RoundTripper
	tokenFile string
}

func (transport *serviceAccountTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	token, err := os.ReadFile(transport.tokenFile)
	if err != nil {
		return nil, fmt.Errorf("read projected Kubernetes ServiceAccount token: %w", err)
	}
	bearer := strings.TrimSpace(string(token))
	if bearer == "" {
		return nil, fmt.Errorf("projected Kubernetes ServiceAccount token is empty")
	}
	clone := request.Clone(request.Context())
	clone.Header = request.Header.Clone()
	clone.Header.Set("Authorization", "Bearer "+bearer)
	return transport.base.RoundTrip(clone)
}
