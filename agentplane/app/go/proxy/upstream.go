// Package proxy contains the app's HTTP proxy primitives and thread Electric routes.
package proxy

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
	"unicode/utf8"
)

// UpstreamProxy opens streamed HTTP requests to one configured service.
//
// The returned client never follows redirects and has no whole-request timeout. Its default
// transport bounds connection establishment to five seconds, while the caller's context controls
// the lifetime of the response stream.
type UpstreamProxy struct {
	client  *http.Client
	baseURL *url.URL
}

// HandlerUpstream relays a request to an in-process generated HTTP facade. Its requests still use
// the same narrow headers and request context as UpstreamProxy, while the generated handler can
// carry them to its gRPC target without an HTTP hop. Responses expose only Content-Type from the
// generated handler and force the app's cache and buffering headers.
type HandlerUpstream struct {
	handler   http.Handler
	tokenFile string
}

// NewHandlerUpstream creates an adapter for a generated HTTP facade handler. If tokenFile is set,
// it rereads the projected service token for every request to preserve token rotation.
func NewHandlerUpstream(handler http.Handler, tokenFile string) *HandlerUpstream {
	return &HandlerUpstream{handler: handler, tokenFile: tokenFile}
}

// ForwardHTTP adapts the public facade route to the generated handler's /v1/ path and forwards the
// request-bound bearer as Authorization. The handler receives the caller's context so disconnect,
// session end and server drain cancel its gRPC call.
func (p *HandlerUpstream) ForwardHTTP(
	w http.ResponseWriter,
	request *http.Request,
	ctx context.Context,
	path string,
	bearer string,
) error {
	if p == nil || p.handler == nil {
		return errors.New("generated facade handler is not configured")
	}
	if request == nil || request.URL == nil {
		return errors.New("generated facade request is not configured")
	}
	if p.tokenFile != "" {
		token, err := os.ReadFile(p.tokenFile)
		if err != nil {
			return fmt.Errorf("read projected upstream token: %w", err)
		}
		bearer = strings.TrimSpace(string(token))
	}
	forwarded := request.Clone(ctx)
	forwarded.URL.Path = "/" + strings.TrimLeft(path, "/")
	forwarded.URL.RawPath = ""
	forwarded.URL.RawQuery = request.URL.RawQuery
	forwarded.URL.Fragment = ""
	forwarded.RequestURI = ""
	forwarded.Header = make(http.Header)
	for _, name := range []string{"Accept", "Content-Type", "User-Agent"} {
		value := request.Header.Get(name)
		if name == "User-Agent" {
			value = truncateRunes(value, 300)
		}
		if value != "" {
			forwarded.Header.Set(name, value)
		}
	}
	if bearer != "" {
		forwarded.Header.Set("Authorization", "Bearer "+bearer)
	}
	forwarded.Header.Set("Accept-Encoding", "identity")
	p.handler.ServeHTTP(newFacadeResponseWriter(w), forwarded)
	return nil
}

type facadeResponseWriter struct {
	underlying  http.ResponseWriter
	header      http.Header
	wroteHeader bool
}

// newFacadeResponseWriter keeps backend headers separate from the app's response headers.
func newFacadeResponseWriter(underlying http.ResponseWriter) http.ResponseWriter {
	filtered := &facadeResponseWriter{underlying: underlying, header: make(http.Header)}
	if _, ok := underlying.(http.Flusher); ok {
		return &flushingFacadeResponseWriter{facadeResponseWriter: filtered}
	}
	return filtered
}

func (w *facadeResponseWriter) Header() http.Header { return w.header }

func (w *facadeResponseWriter) WriteHeader(statusCode int) {
	if w.wroteHeader {
		return
	}
	w.wroteHeader = true
	if values := w.header.Values("Content-Type"); len(values) > 0 {
		w.underlying.Header().Set("Content-Type", values[0])
	}
	w.underlying.Header().Set("Cache-Control", "no-store")
	w.underlying.Header().Set("X-Accel-Buffering", "no")
	w.underlying.WriteHeader(statusCode)
}

func (w *facadeResponseWriter) Write(data []byte) (int, error) {
	if !w.wroteHeader {
		w.WriteHeader(http.StatusOK)
	}
	return w.underlying.Write(data)
}

func (w *facadeResponseWriter) Unwrap() http.ResponseWriter { return w.underlying }

type flushingFacadeResponseWriter struct {
	*facadeResponseWriter
}

func (w *flushingFacadeResponseWriter) Flush() { _ = w.FlushError() }

func (w *flushingFacadeResponseWriter) FlushError() error {
	if !w.wroteHeader {
		w.WriteHeader(http.StatusOK)
	}
	return http.NewResponseController(w.underlying).Flush()
}

// NewUpstreamProxy creates a streaming client for baseURL.
func NewUpstreamProxy(client *http.Client, baseURL string) (*UpstreamProxy, error) {
	base, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("parse upstream URL: %w", err)
	}
	if !base.IsAbs() || base.Host == "" || (base.Scheme != "http" && base.Scheme != "https") {
		return nil, fmt.Errorf("upstream URL must be an absolute HTTP(S) URL")
	}
	base.Path = ""
	base.RawPath = ""
	base.RawQuery = ""
	base.Fragment = ""
	return &UpstreamProxy{client: proxyClient(client), baseURL: base}, nil
}

// OpenRequest opens a streamed request. Only Accept, Content-Type, and User-Agent are forwarded
// from headers; browser credentials and cookies never cross the proxy boundary. The response body
// remains unread and must be closed by the caller.
func (p *UpstreamProxy) OpenRequest(
	ctx context.Context,
	method, path, query, bearer string,
	headers http.Header,
	body io.Reader,
) (*http.Response, error) {
	return p.openRequest(ctx, method, path, query, bearer, headers, body, representationHeaders)
}

var representationHeaders = map[string]struct{}{
	"accept":       {},
	"content-type": {},
	"user-agent":   {},
}

func (p *UpstreamProxy) openRequest(
	ctx context.Context,
	method, path, query, bearer string,
	headers http.Header,
	body io.Reader,
	allowedHeaders map[string]struct{},
) (*http.Response, error) {
	target := *p.baseURL
	target.Path = "/" + strings.TrimLeft(path, "/")
	target.RawPath = ""
	target.RawQuery = query
	request, err := http.NewRequestWithContext(ctx, method, target.String(), body)
	if err != nil {
		return nil, fmt.Errorf("build upstream request: %w", err)
	}
	for name, values := range headers {
		if _, ok := allowedHeaders[strings.ToLower(name)]; !ok || len(values) == 0 {
			continue
		}
		value := values[0]
		if strings.EqualFold(name, "User-Agent") {
			value = truncateRunes(value, 300)
		}
		request.Header.Set(name, value)
	}
	if bearer != "" {
		request.Header.Set("Authorization", "Bearer "+bearer)
	}
	// Match the Python client: avoid decompression so an upstream content-encoding and its bytes
	// remain a pair, and let the request context bound the stream rather than a total timeout.
	request.Header.Set("Accept-Encoding", "identity")
	response, err := p.client.Do(request)
	if err != nil {
		return nil, err
	}
	return response, nil
}

// relayResponse writes an upstream response while exposing only the selected headers.
func relayResponse(w http.ResponseWriter, response *http.Response, allowedHeaders map[string]struct{}, overrides http.Header) error {
	if response == nil {
		return errors.New("nil upstream response")
	}
	if response.Body != nil {
		defer response.Body.Close()
	}
	for name, values := range response.Header {
		if _, ok := allowedHeaders[strings.ToLower(name)]; !ok || len(values) == 0 {
			continue
		}
		w.Header().Set(name, values[0])
	}
	for name, values := range overrides {
		w.Header().Del(name)
		for _, value := range values {
			w.Header().Add(name, value)
		}
	}
	w.WriteHeader(response.StatusCode)
	if response.Body == nil {
		return nil
	}
	contentType := response.Header.Get("Content-Type")
	if strings.HasPrefix(contentType, "text/event-stream") || strings.HasPrefix(contentType, "application/x-ndjson") {
		controller := http.NewResponseController(w)
		if err := controller.Flush(); err != nil {
			return err
		}
		_, err := io.Copy(flushingStreamWriter{writer: w, controller: controller}, response.Body)
		return err
	}
	_, err := io.Copy(w, response.Body)
	return err
}

// Flush each upstream read before waiting for another: small live updates must not sit in
// net/http's output buffer until a later event arrives. Synchronous writes retain backpressure.
type flushingStreamWriter struct {
	writer     io.Writer
	controller *http.ResponseController
}

func (w flushingStreamWriter) Write(data []byte) (int, error) {
	n, err := w.writer.Write(data)
	if err != nil {
		return n, err
	}
	return n, w.controller.Flush()
}

// GeneratedFacadeRouteAllowed keeps operator proxy calls within a versioned, read/write facade.
func GeneratedFacadeRouteAllowed(method, path string) bool {
	if method != http.MethodGet && method != http.MethodPost && method != http.MethodPatch && method != http.MethodDelete {
		return false
	}
	if !strings.HasPrefix(path, "v1/") || strings.Contains(path, `\`) {
		return false
	}
	for _, segment := range strings.Split(path, "/") {
		if segment == "" || segment == "." || segment == ".." {
			return false
		}
	}
	return true
}

func proxyClient(client *http.Client) *http.Client {
	if client == nil {
		client = &http.Client{Transport: defaultProxyTransport()}
	}
	copy := *client
	if copy.Transport == nil {
		copy.Transport = defaultProxyTransport()
	}
	copy.Timeout = 0
	copy.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return &copy
}

func defaultProxyTransport() *http.Transport {
	return &http.Transport{
		Proxy:                 http.ProxyFromEnvironment,
		DialContext:           (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		ForceAttemptHTTP2:     true,
		TLSHandshakeTimeout:   5 * time.Second,
		ExpectContinueTimeout: time.Second,
		IdleConnTimeout:       90 * time.Second,
		MaxIdleConns:          100,
		DisableCompression:    true,
	}
}

func truncateRunes(value string, limit int) string {
	if utf8.RuneCountInString(value) <= limit {
		return value
	}
	count := 0
	for index := range value {
		if count == limit {
			return value[:index]
		}
		count++
	}
	return value
}
