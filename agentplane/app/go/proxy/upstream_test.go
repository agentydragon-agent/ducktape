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

func TestRelayFlushesSmallLiveUpdatesAndCancelsUpstreamOnDisconnect(t *testing.T) {
	for _, contentType := range []string{"text/event-stream", "application/x-ndjson"} {
		t.Run(contentType, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			emit := make(chan string)
			upstreamClosed := make(chan struct{})
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				defer close(upstreamClosed)
				w.Header().Set("Content-Type", contentType)
				w.WriteHeader(http.StatusOK)
				w.(http.Flusher).Flush()
				for {
					select {
					case <-r.Context().Done():
						return
					case data := <-emit:
						_, _ = io.WriteString(w, data)
						w.(http.Flusher).Flush()
					}
				}
			}))
			defer upstream.Close()
			proxy, err := NewUpstreamProxy(upstream.Client(), upstream.URL)
			if err != nil {
				t.Fatal(err)
			}
			relay := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				response, err := proxy.OpenRequest(r.Context(), http.MethodGet, "watch", "", "", nil, nil)
				if err != nil {
					t.Errorf("open upstream: %v", err)
					return
				}
				_ = relayResponse(w, response, map[string]struct{}{"content-type": {}}, nil)
			}))
			defer relay.Close()
			request, err := http.NewRequestWithContext(ctx, http.MethodGet, relay.URL, nil)
			if err != nil {
				t.Fatal(err)
			}
			response, err := relay.Client().Do(request)
			if err != nil {
				t.Fatalf("headers did not arrive before the first update: %v", err)
			}
			defer response.Body.Close()
			for _, update := range []string{"data: first\n\n", "data: second\n\n"} {
				select {
				case emit <- update:
				case <-ctx.Done():
					t.Fatal(ctx.Err())
				}
				body := make([]byte, len(update))
				if _, err := io.ReadFull(response.Body, body); err != nil {
					t.Fatalf("small update was buffered until a later write: %v", err)
				}
				if string(body) != update {
					t.Fatalf("update = %q, want %q", body, update)
				}
			}
			if err := response.Body.Close(); err != nil {
				t.Fatal(err)
			}
			select {
			case <-upstreamClosed:
			case <-ctx.Done():
				t.Fatal("browser disconnect did not close the upstream watch")
			}
		})
	}
}

type boundedRelayBody struct {
	remaining int
	reads     int
	closed    bool
}

func (b *boundedRelayBody) Read(buffer []byte) (int, error) {
	b.reads++
	if b.remaining == 0 {
		return 0, io.EOF
	}
	n := min(len(buffer), b.remaining)
	clear(buffer[:n])
	b.remaining -= n
	return n, nil
}

func (b *boundedRelayBody) Close() error {
	b.closed = true
	return nil
}

type blockedRelayWriter struct {
	http.ResponseWriter
	writing chan struct{}
	dropped chan struct{}
}

func (w blockedRelayWriter) Write([]byte) (int, error) {
	close(w.writing)
	<-w.dropped
	return 0, io.ErrClosedPipe
}

func (w blockedRelayWriter) Flush() {}

func TestRelayBackpressureBoundsReadsAndWriteFailureClosesUpstream(t *testing.T) {
	body := &boundedRelayBody{remaining: 1 << 20}
	writer := blockedRelayWriter{
		ResponseWriter: httptest.NewRecorder(), writing: make(chan struct{}), dropped: make(chan struct{}),
	}
	done := make(chan error, 1)
	go func() {
		done <- relayResponse(writer, &http.Response{
			StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"text/event-stream"}}, Body: body,
		}, map[string]struct{}{"content-type": {}}, nil)
	}()
	select {
	case <-writer.writing:
	case <-time.After(5 * time.Second):
		t.Fatal("relay never started the browser write")
	}
	close(writer.dropped)
	select {
	case err := <-done:
		if err != io.ErrClosedPipe {
			t.Fatalf("relay write failure = %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("relay did not stop after the browser write failed")
	}
	if body.reads != 1 || body.remaining == 0 || !body.closed {
		t.Fatalf("upstream reads=%d remaining=%d closed=%t", body.reads, body.remaining, body.closed)
	}
}
