// Copyright 2026 agentydragon
// SPDX-License-Identifier: Apache-2.0

package kubeapiproxy

import (
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func TestServiceAccountTransportReloadsProjectedToken(t *testing.T) {
	tokenFile := t.TempDir() + "/token"
	seen := make([]string, 0, 2)
	transport := &serviceAccountTransport{
		tokenFile: tokenFile,
		base: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			seen = append(seen, request.Header.Get("Authorization"))
			return &http.Response{
				StatusCode: http.StatusOK,
				Header:     make(http.Header),
				Body:       io.NopCloser(strings.NewReader("ok")),
				Request:    request,
			}, nil
		}),
	}
	request, _ := http.NewRequest(http.MethodGet, "https://kubernetes.test/version", nil)
	request.Header.Set("Authorization", "Bearer caller-must-not-survive")

	for _, token := range []string{"first-projected-token", "rotated-projected-token"} {
		if err := os.WriteFile(tokenFile, []byte(token+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		response, err := transport.RoundTrip(request)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
	}
	want := []string{"Bearer first-projected-token", "Bearer rotated-projected-token"}
	if strings.Join(seen, ",") != strings.Join(want, ",") {
		t.Fatalf("authorization headers = %#v, want %#v", seen, want)
	}
}

func TestServiceAccountTransportRejectsEmptyToken(t *testing.T) {
	tokenFile := t.TempDir() + "/token"
	if err := os.WriteFile(tokenFile, []byte("\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	transport := &serviceAccountTransport{
		tokenFile: tokenFile,
		base: roundTripFunc(func(*http.Request) (*http.Response, error) {
			t.Error("base transport called")
			return nil, nil
		}),
	}
	request, _ := http.NewRequest(http.MethodGet, "https://kubernetes.test/version", nil)
	if _, err := transport.RoundTrip(request); err == nil {
		t.Fatal("empty token was accepted")
	}
}
