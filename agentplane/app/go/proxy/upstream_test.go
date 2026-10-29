package proxy

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestOpenRequestFiltersHeadersAndStreamsRequest(t *testing.T) {
	userAgent := strings.Repeat("x", 301)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Errorf("read request body: %v", err)
		}
		if string(body) != "request body" {
			t.Errorf("request body = %q", body)
		}
		if r.Method != http.MethodPatch || r.URL.Path != "/v1/items/42" || r.URL.RawQuery != "dry_run=true" {
			t.Errorf("forwarded request = %s %s?%s", r.Method, r.URL.Path, r.URL.RawQuery)
		}
		if r.Header.Get("Authorization") != "Bearer operator-token" {
			t.Errorf("Authorization = %q", r.Header.Get("Authorization"))
		}
		if r.Header.Get("Accept") != "application/json" || r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("representation headers = %v", r.Header)
		}
		if len(r.Header.Get("User-Agent")) != 300 {
			t.Errorf("User-Agent length = %d", len(r.Header.Get("User-Agent")))
		}
		if r.Header.Get("Cookie") != "" || r.Header.Get("X-Secret") != "" {
			t.Errorf("unapproved headers crossed proxy: %v", r.Header)
		}
		if r.Header.Get("Accept-Encoding") != "identity" {
			t.Errorf("Accept-Encoding = %q", r.Header.Get("Accept-Encoding"))
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, "created")
	}))
	defer server.Close()
	proxy, err := NewUpstreamProxy(server.Client(), server.URL)
	if err != nil {
		t.Fatal(err)
	}
	headers := make(http.Header)
	headers.Set("Accept", "application/json")
	headers.Set("Content-Type", "application/json")
	headers.Set("User-Agent", userAgent)
	headers.Set("Cookie", "browser-cookie")
	headers.Set("Authorization", "browser-credential")
	headers.Set("X-Secret", "secret")
	response, err := proxy.OpenRequest(context.Background(), http.MethodPatch, "v1/items/42", "dry_run=true", "operator-token", headers, strings.NewReader("request body"))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusCreated || string(body) != "created" {
		t.Fatalf("upstream response = %d %q", response.StatusCode, body)
	}
}

func TestGeneratedFacadeRouteAllowed(t *testing.T) {
	for _, test := range []struct {
		method string
		path   string
		want   bool
	}{
		{http.MethodGet, "v1/items", true},
		{http.MethodPost, "v1/items:search", true},
		{http.MethodPatch, "v1/items/42", true},
		{http.MethodDelete, "v1/items/42", true},
		{http.MethodPut, "v1/items/42", false},
		{http.MethodPost, "v2/items", false},
		{http.MethodPost, "v1/../admin", false},
		{http.MethodPost, "v1//items", false},
		{http.MethodPost, `v1/items\admin`, false},
	} {
		t.Run(test.method+"_"+test.path, func(t *testing.T) {
			if got := GeneratedFacadeRouteAllowed(test.method, test.path); got != test.want {
				t.Fatalf("GeneratedFacadeRouteAllowed(%q, %q) = %v, want %v", test.method, test.path, got, test.want)
			}
		})
	}
}

func TestOpenRequestDoesNotFollowRedirects(t *testing.T) {
	redirected := false
	destination := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { redirected = true }))
	defer destination.Close()
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Location", destination.URL)
		w.WriteHeader(http.StatusTemporaryRedirect)
	}))
	defer origin.Close()
	proxy, err := NewUpstreamProxy(origin.Client(), origin.URL)
	if err != nil {
		t.Fatal(err)
	}
	response, err := proxy.OpenRequest(context.Background(), http.MethodGet, "v1/watch", "", "", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusTemporaryRedirect || redirected {
		t.Fatalf("status=%d destination called=%v", response.StatusCode, redirected)
	}
}

func TestRequestContextCancelsOpenStream(t *testing.T) {
	firstChunk := make(chan struct{})
	requestCanceled := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			t.Error("ResponseWriter does not support flush")
			return
		}
		_, _ = io.WriteString(w, "first\n")
		flusher.Flush()
		close(firstChunk)
		<-r.Context().Done()
		close(requestCanceled)
	}))
	defer server.Close()
	proxy, err := NewUpstreamProxy(server.Client(), server.URL)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	response, err := proxy.OpenRequest(ctx, http.MethodGet, "v1/watch", "", "", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if _, err := io.ReadFull(response.Body, make([]byte, len("first\n"))); err != nil {
		t.Fatal(err)
	}
	select {
	case <-firstChunk:
	case <-time.After(time.Second):
		t.Fatal("upstream did not begin streaming")
	}
	cancel()
	_ = response.Body.Close()
	select {
	case <-requestCanceled:
	case <-time.After(time.Second):
		t.Fatal("upstream request context was not canceled")
	}
}
