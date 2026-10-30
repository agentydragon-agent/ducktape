package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestInvocationStatusDistinguishesAbsentFromFailedLookup(t *testing.T) {
	for _, code := range []int{200, 500} {
		t.Run(http.StatusText(code), func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/api/v1/GetInvocation" {
					t.Errorf("wrong endpoint %s", r.URL.Path)
				}
				var body struct {
					Selector struct {
						InvocationID string `json:"invocationId"`
					} `json:"selector"`
				}
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
				}
				if body.Selector.InvocationID != "absent" {
					t.Error(body)
				}
				w.WriteHeader(code)
				_, _ = io.WriteString(w, `{}`)
			}))
			defer s.Close()
			c := &client{baseURL: s.URL, http: s.Client(), apiKey: "test"}
			resp, err := getInvocationStatus(c, "absent")
			if code == 200 {
				if err != nil || len(resp.GetInvocation()) != 0 {
					t.Fatalf("absent: %v %v", resp, err)
				}
			} else if err == nil {
				t.Fatal("failed lookup looked like absence")
			}
		})
	}
}

func TestBlobBatchUsesAdvertisedURIsAndPreservesDestinations(t *testing.T) {
	root := t.TempDir()
	var mu sync.Mutex
	seen := map[string]string{}
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/file/download" {
			t.Errorf("unexpected path %s", r.URL.Path)
		}
		if r.Header.Get("x-buildbuddy-api-key") != "test" {
			t.Error("missing credential")
		}
		uri := r.URL.Query().Get("bytestream_url")
		mu.Lock()
		seen[uri] = r.URL.Query().Get("invocation_id")
		mu.Unlock()
		if strings.Contains(uri, "missing") {
			http.Error(w, "missing", 404)
			return
		}
		_, _ = io.WriteString(w, uri)
	}))
	defer s.Close()
	c := &client{baseURL: s.URL, http: s.Client(), apiKey: "test"}
	items := []blobDownload{{URI: "bytestream://host/blobs/a/1", Destination: filepath.Join(root, "nested", "one"), InvocationID: "inv-1"}, {URI: "bytestream://host/blobs/b/1", Destination: filepath.Join(root, "two"), InvocationID: "inv-2"}}
	if err := downloadBlobs(c, items); err != nil {
		t.Fatal(err)
	}
	for _, item := range items {
		got, err := os.ReadFile(item.Destination)
		if err != nil || string(got) != item.URI {
			t.Fatalf("download %s: %q %v", item.Destination, got, err)
		}
		if seen[item.URI] != item.InvocationID {
			t.Error("lost invocation fallback context")
		}
	}
	old := items[0].Destination
	if err := downloadBlobs(c, []blobDownload{{URI: "bytestream://host/missing", Destination: old}}); err == nil {
		t.Fatal("missing blob was successful")
	}
	if got, _ := os.ReadFile(old); string(got) != items[0].URI {
		t.Fatal("failed download replaced existing artifact")
	}
	if err := downloadBlobs(c, []blobDownload{items[0], items[0]}); err == nil {
		t.Fatal("duplicate destination accepted")
	}
}

func TestCancellationRequestsOnlyExplicitIDsAndAttemptsAllConcurrently(t *testing.T) {
	ids := []string{"11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"}
	var mu sync.Mutex
	seen := map[string]bool{}
	both := make(chan struct{})
	var once sync.Once
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/rpc/BuildBuddyService/CancelExecutions" {
			t.Errorf("wrong method %s", r.URL.Path)
		}
		var body struct {
			InvocationID string `json:"invocationId"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		mu.Lock()
		seen[body.InvocationID] = true
		if len(seen) == 2 {
			once.Do(func() { close(both) })
		}
		mu.Unlock()
		select {
		case <-both:
		case <-time.After(time.Second):
			t.Error("requests were serialized")
		}
		if body.InvocationID == ids[0] {
			http.Error(w, "failed", 500)
			return
		}
		_, _ = io.WriteString(w, `{}`)
	}))
	defer s.Close()
	c := &client{baseURL: s.URL, http: s.Client(), apiKey: "test"}
	if err := cancelInvocations(c, ids); err == nil {
		t.Fatal("failed cancellation not reported")
	}
	if len(seen) != 2 || !seen[ids[0]] || !seen[ids[1]] {
		t.Fatal(seen)
	}
	if err := cancelInvocations(c, []string{ids[0], "bad"}); err == nil {
		t.Fatal("invalid id accepted")
	}
}

func TestReadRPCRetriesWithoutDroppingRequestBody(t *testing.T) {
	calls := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Error(err)
		}
		if !strings.Contains(string(body), "invocationId") {
			t.Errorf("request body lost on attempt %d", calls)
		}
		if calls == 1 {
			http.Error(w, "transient", 503)
			return
		}
		_, _ = io.WriteString(w, `{}`)
	}))
	defer s.Close()
	c := &client{baseURL: s.URL, http: s.Client(), apiKey: "test", retries: 1}
	if _, err := getInvocationStatus(c, "id"); err != nil {
		t.Fatal(err)
	}
	if calls != 2 {
		t.Fatalf("calls=%d", calls)
	}
}
