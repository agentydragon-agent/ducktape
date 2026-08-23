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

// InClusterConfig identifies the Kubernetes API and projected ServiceAccount
// files used by the proxy's upstream identity.
type InClusterConfig struct {
	ServiceHost             string
	ServicePort             string
	ServiceAccountDirectory string
}

// InClusterUpstream builds the API URL and rotating ServiceAccount bearer
// transport from Kubernetes' standard projected files.
func InClusterUpstream(config InClusterConfig) (*url.URL, http.RoundTripper, error) {
	if config.ServiceHost == "" || config.ServicePort == "" {
		return nil, nil, fmt.Errorf("Kubernetes service host and port are required")
	}
	if config.ServiceAccountDirectory == "" {
		return nil, nil, fmt.Errorf("Kubernetes ServiceAccount directory is required")
	}

	caFile := filepath.Join(config.ServiceAccountDirectory, "ca.crt")
	caPEM, err := os.ReadFile(caFile)
	if err != nil {
		return nil, nil, fmt.Errorf("read Kubernetes CA %s: %w", caFile, err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(caPEM) {
		return nil, nil, fmt.Errorf("Kubernetes CA %s contains no certificates", caFile)
	}
	upstream, err := url.Parse("https://" + net.JoinHostPort(strings.Trim(config.ServiceHost, "[]"), config.ServicePort))
	if err != nil {
		return nil, nil, fmt.Errorf("construct Kubernetes API URL: %w", err)
	}
	base := &http.Transport{
		TLSClientConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
			RootCAs:    roots,
		},
		// Kubernetes streaming subresources use HTTP/1.1 protocol upgrades.
		// A custom TLS configuration already disables HTTP/2 unless explicitly
		// forced; keep it that way so exec and port-forward can reach an
		// HTTP/2-capable apiserver.
	}
	return upstream, &serviceAccountTransport{
		base:      base,
		tokenFile: filepath.Join(config.ServiceAccountDirectory, "token"),
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
