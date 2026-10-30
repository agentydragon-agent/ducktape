package main

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"os"
	"strings"
	"testing"
	"time"

	aclpb "github.com/buildbuddy-io/buildbuddy/proto/acl"
	bespb "github.com/buildbuddy-io/buildbuddy/proto/build_event_stream"
	bbspb "github.com/buildbuddy-io/buildbuddy/proto/buildbuddy_service"
	invocationpb "github.com/buildbuddy-io/buildbuddy/proto/invocation"
	targetpb "github.com/buildbuddy-io/buildbuddy/proto/target"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	grpcstatus "google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
)

type targetHistoryTestServer struct {
	bbspb.UnimplementedBuildBuddyServiceServer
	t            *testing.T
	searchResult *invocationpb.SearchInvocationResponse
	pageTokens   []string
	pages        map[string]*targetpb.GetTargetHistoryResponse
}

func (s *targetHistoryTestServer) SearchInvocation(context.Context, *invocationpb.SearchInvocationRequest) (*invocationpb.SearchInvocationResponse, error) {
	return s.searchResult, nil
}

func (s *targetHistoryTestServer) GetTargetHistory(_ context.Context, req *targetpb.GetTargetHistoryRequest) (*targetpb.GetTargetHistoryResponse, error) {
	pageToken := req.GetPageToken()
	s.pageTokens = append(s.pageTokens, pageToken)
	page, ok := s.pages[pageToken]
	if !ok {
		s.t.Errorf("unexpected page token %q", pageToken)
		return nil, grpcstatus.Error(codes.InvalidArgument, "unexpected page token")
	}
	return page, nil
}

func startTargetHistoryTestServer(t *testing.T, service *targetHistoryTestServer) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen for gRPC test server: %v", err)
	}
	server := grpc.NewServer()
	bbspb.RegisterBuildBuddyServiceServer(server, service)
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(server.Stop)
	t.Setenv("BUILDBUDDY_API_KEY", "test-key")
	t.Setenv("BUILDBUDDY_URL", "http://"+listener.Addr().String())
}

func decodeTargetHistoryPage(t *testing.T, data []byte) *targetpb.GetTargetHistoryResponse {
	t.Helper()
	response := &targetpb.GetTargetHistoryResponse{}
	if err := protojson.Unmarshal(data, response); err != nil {
		t.Fatalf("decode target history fixture: %v", err)
	}
	return response
}

func TestChooseLogsPrefersTheResultsThatFailed(t *testing.T) {
	logs := logsOf(parseOrFail(t, shardedStream), "//pkg:visual")
	chosen, why := chooseLogs(logs)
	if len(chosen) != 1 || chosen[0].GetId().GetTestResult().GetShard() != 2 {
		t.Errorf("chose %v", describeAll(chosen))
	}
	if !strings.Contains(why, "1 of 3") {
		t.Errorf("why = %q", why)
	}
}

func TestChooseLogsFallsBackToTheFirstWhenNothingFailed(t *testing.T) {
	logs := logsOf(parseOrFail(t, shardedStream), "//pkg:visual")
	logs[1].Status = bespb.TestStatus_PASSED
	chosen, why := chooseLogs(logs)
	if len(chosen) != 1 || chosen[0].GetId().GetTestResult().GetShard() != 1 {
		t.Errorf("chose %v", describeAll(chosen))
	}
	if !strings.Contains(why, "None failed") {
		t.Errorf("why = %q", why)
	}
}

func TestTargetHistoryPageCutoffRequiresValidTimestamps(t *testing.T) {
	page := &targetpb.GetTargetHistoryResponse{
		InvocationTargets: []*targetpb.TargetHistory{{
			TargetStatus: []*targetpb.TargetStatus{{}},
		}},
	}
	if targetHistoryPageIsOlderThan(page, time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("page with a missing invocation timestamp was treated as an old page")
	}
}

func TestTargetHistoryPaginatesMergesAndFiltersBothOutputModes(t *testing.T) {
	cases := []struct {
		name       string
		jsonOutput bool
		flags      map[string]string
	}{
		{
			name: "text filters before count",
			flags: map[string]string{
				"failures-only": "true",
				"since":         "2026-01-01",
				"count":         "1",
			},
		},
		{
			name:       "json filters merged pages",
			jsonOutput: true,
			flags: map[string]string{
				"label":         "//pkg:keep",
				"failures-only": "true",
				"since":         "2026-01-01",
			},
		},
		{
			name:       "json applies count",
			jsonOutput: true,
			flags: map[string]string{
				"failures-only": "true",
				"since":         "2026-01-01",
				"count":         "1",
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			firstPage := []byte(`{"invocationTargets":[
				{"target":{"label":"//pkg:passed"},"targetStatus":[{"status":"PASSED","invocationId":"passed-only","invocationCreatedAtUsec":"1772323200000000"}]},
				{"target":{"label":"//pkg:keep"},"targetStatus":[{"status":"PASSED","invocationId":"keep-pass","invocationCreatedAtUsec":"1772409600000000"}]}
			],"nextPageToken":"page-2"}`)
			secondPage := []byte(`{"invocationTargets":[
				{"target":{"label":"//pkg:keep"},"targetStatus":[{"status":"FAILED","invocationId":"keep-cutoff","invocationCreatedAtUsec":"1767225600000000"},{"status":"FAILED","invocationId":"old-failure","invocationCreatedAtUsec":"1767139200000000"}]},
				{"target":{"label":"//pkg:other"},"targetStatus":[{"status":"FAILED","invocationId":"other-failure","invocationCreatedAtUsec":"1767225600000000"}]}
			],"nextPageToken":"page-3"}`)
			thirdPage := []byte(`{"invocationTargets":[
				{"target":{"label":"//pkg:keep"},"targetStatus":[{"status":"FAILED","invocationId":"stale-page","invocationCreatedAtUsec":"1767052800000000"}]}
			],"nextPageToken":"page-4"}`)
			service := &targetHistoryTestServer{
				t: t,
				searchResult: &invocationpb.SearchInvocationResponse{
					Invocation: []*invocationpb.Invocation{{Acl: &aclpb.ACL{GroupId: "test-group"}}},
				},
				pages: map[string]*targetpb.GetTargetHistoryResponse{
					"":       decodeTargetHistoryPage(t, firstPage),
					"page-2": decodeTargetHistoryPage(t, secondPage),
					"page-3": decodeTargetHistoryPage(t, thirdPage),
				},
			}
			startTargetHistoryTestServer(t, service)

			previousJSONOutput := jsonOutput
			jsonOutput = tc.jsonOutput
			t.Cleanup(func() { jsonOutput = previousJSONOutput })

			cmd := targetHistorySubCmd()
			if err := cmd.Flags().Set("repo", "https://repo.test/project"); err != nil {
				t.Fatal(err)
			}
			for name, value := range tc.flags {
				if err := cmd.Flags().Set(name, value); err != nil {
					t.Fatal(err)
				}
			}
			output, err := captureTargetHistoryOutput(t, func() error { return cmd.RunE(cmd, nil) })
			if err != nil {
				t.Fatalf("run target history: %v", err)
			}
			if len(service.pageTokens) != 3 || service.pageTokens[0] != "" || service.pageTokens[1] != "page-2" || service.pageTokens[2] != "page-3" {
				t.Errorf("history page tokens = %q, want empty, page-2, page-3; page-4 must be skipped", service.pageTokens)
			}

			if tc.jsonOutput {
				response := &targetpb.GetTargetHistoryResponse{}
				if err := protojson.Unmarshal(output, response); err != nil {
					t.Fatalf("decode JSON output: %v\n%s", err, output)
				}
				if got := len(response.GetInvocationTargets()); got != 1 {
					t.Fatalf("JSON target count = %d, want 1", got)
				}
				history := response.GetInvocationTargets()[0]
				if got := history.GetTarget().GetLabel(); got != "//pkg:keep" {
					t.Errorf("JSON target label = %q", got)
				}
				if got := len(history.GetTargetStatus()); got != 1 || history.GetTargetStatus()[0].GetInvocationId() != "keep-cutoff" {
					t.Errorf("JSON statuses = %v, want only keep-cutoff", history.GetTargetStatus())
				}
				var fields map[string]json.RawMessage
				if err := json.Unmarshal(output, &fields); err != nil {
					t.Fatalf("decode JSON fields: %v", err)
				}
				if _, ok := fields["nextPageToken"]; ok {
					t.Errorf("JSON contains a stale nextPageToken: %s", output)
				}
				return
			}

			if got := strings.Count(string(output), "Target: //pkg:keep"); got != 1 {
				t.Errorf("text target count = %d, want one merged target:\n%s", got, output)
			}
			for _, excluded := range []string{"passed-only", "keep-pass", "old-failure", "other-failure", "stale-page"} {
				if strings.Contains(string(output), excluded) {
					t.Errorf("text output contains filtered invocation %q:\n%s", excluded, output)
				}
			}
			if !strings.Contains(string(output), "keep-cutoff") {
				t.Errorf("text output omits the inclusive cutoff history:\n%s", output)
			}
		})
	}
}

func captureTargetHistoryOutput(t *testing.T, run func() error) ([]byte, error) {
	t.Helper()
	reader, writer, err := os.Pipe()
	if err != nil {
		return nil, err
	}
	previousStdout := os.Stdout
	os.Stdout = writer
	defer func() {
		os.Stdout = previousStdout
		_ = reader.Close()
	}()
	runErr := run()
	if err := writer.Close(); err != nil {
		return nil, err
	}
	os.Stdout = previousStdout
	output, err := io.ReadAll(reader)
	if err != nil {
		return nil, err
	}
	return output, runErr
}
