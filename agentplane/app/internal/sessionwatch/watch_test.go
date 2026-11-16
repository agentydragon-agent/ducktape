package sessionwatch

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"testing"
	"time"

	apppb "github.com/agentydragon/ducktape/agentplane/app/appservicepb"
	dispatcherpb "github.com/agentydragon/ducktape/agentplane/session_dispatcher/dispatcher/api/session/session_dispatcherpb"
	"github.com/google/uuid"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/encoding/protojson"
)

type testStream struct {
	grpc.ClientStream
	ctx    context.Context
	frames chan *dispatcherpb.WatchSessionsResponse
}

func (s *testStream) Recv() (*dispatcherpb.WatchSessionsResponse, error) {
	select {
	case frame := <-s.frames:
		return frame, nil
	case <-s.ctx.Done():
		return nil, s.ctx.Err()
	}
}

type testClient struct {
	requests chan *dispatcherpb.WatchSessionsRequest
	frames   chan *dispatcherpb.WatchSessionsResponse
}

func (c *testClient) WatchSessions(ctx context.Context, request *dispatcherpb.WatchSessionsRequest, _ ...grpc.CallOption) (grpc.ServerStreamingClient[dispatcherpb.WatchSessionsResponse], error) {
	c.requests <- request
	return &testStream{ctx: ctx, frames: c.frames}, nil
}

type testOpener struct {
	opened chan uuid.UUID
	err    error
}

func (o *testOpener) OpenThread(ctx context.Context, id uuid.UUID) error {
	if o.err != nil {
		return o.err
	}
	o.opened <- id
	return nil
}

func upsert(id, token string) *dispatcherpb.WatchSessionsResponse {
	return &dispatcherpb.WatchSessionsResponse{ResumeToken: token, Frame: &dispatcherpb.WatchSessionsResponse_Session{Session: &dispatcherpb.Session{SessionId: id}}}
}

func checkpoint(token string) *dispatcherpb.WatchSessionsResponse {
	return &dispatcherpb.WatchSessionsResponse{ResumeToken: token, Frame: &dispatcherpb.WatchSessionsResponse_CaughtUp{CaughtUp: &dispatcherpb.CaughtUp{}}}
}

func TestOneUpstreamServesTwoBrowserSnapshotsAndResumes(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	client := &testClient{requests: make(chan *dispatcherpb.WatchSessionsRequest, 4), frames: make(chan *dispatcherpb.WatchSessionsResponse, 4)}
	opener := &testOpener{opened: make(chan uuid.UUID, 4)}
	watch := New(client, opener)
	stopped := make(chan error, 1)
	go func() { stopped <- watch.Run(ctx) }()
	defer func() {
		cancel()
		select {
		case <-stopped:
		case <-time.After(time.Second):
			t.Error("shared watch did not stop")
		}
	}()
	if request := <-client.requests; request.GetResumeToken() != "" {
		t.Fatal("fresh replica did not request snapshot")
	}
	server := httptest.NewServer(watch.Handler())
	defer server.Close()
	firstID := uuid.NewString()
	client.frames <- upsert(firstID, "test-token-one")
	client.frames <- checkpoint("test-token-one")
	for range 2 {
		response, err := server.Client().Get(server.URL + "/v1/sessions:watch")
		if err != nil {
			t.Fatal(err)
		}
		decoder := json.NewDecoder(response.Body)
		found := false
		for {
			var envelope struct {
				Result json.RawMessage `json:"result"`
			}
			if err := decoder.Decode(&envelope); err != nil {
				t.Fatal(err)
			}
			frame := &apppb.WatchSessionInventoryResponse{}
			if err := protojson.Unmarshal(envelope.Result, frame); err != nil {
				t.Fatal(err)
			}
			for _, session := range frame.GetSessions() {
				found = found || session.GetSessionId() == firstID
			}
			if frame.GetCaughtUp() {
				if !found || !frame.GetUpdatesConnected() {
					t.Fatal("snapshot was not complete and connected")
				}
				break
			}
		}
		response.Body.Close()
	}
	select {
	case <-client.requests:
		t.Fatal("browser opened another upstream watch")
	default:
	}
	client.frames <- &dispatcherpb.WatchSessionsResponse{Frame: &dispatcherpb.WatchSessionsResponse_ReconnectRequired{}}
	select {
	case request := <-client.requests:
		if request.GetResumeToken() != "test-token-one" {
			t.Fatalf("resume token = %q", request.GetResumeToken())
		}
	case <-time.After(time.Second):
		t.Fatal("upstream did not renew its watch")
	}
	secondID := uuid.NewString()
	client.frames <- upsert(secondID, "test-token-two")
	client.frames <- checkpoint("test-token-two")
	select {
	case id := <-opener.opened:
		if id.String() != firstID {
			t.Fatal(id)
		}
	case <-time.After(time.Second):
		t.Fatal("first metadata missing")
	}
	select {
	case id := <-opener.opened:
		if id.String() != secondID {
			t.Fatal(id)
		}
	case <-time.After(time.Second):
		t.Fatal("second metadata missing")
	}
}

func TestFailedMetadataDoesNotAdvanceCheckpoint(t *testing.T) {
	client := &testClient{requests: make(chan *dispatcherpb.WatchSessionsRequest, 1), frames: make(chan *dispatcherpb.WatchSessionsResponse, 1)}
	watch := New(client, &testOpener{err: errors.New("test database unavailable")})
	client.frames <- upsert(uuid.NewString(), "test-uncommitted-token")
	token := "test-last-applied-token"
	if err := watch.follow(t.Context(), &token); err == nil {
		t.Fatal("failed metadata accepted")
	}
	if token != "test-last-applied-token" {
		t.Fatal("failed metadata advanced checkpoint")
	}
	frame, _, _ := watch.read(0)
	if len(frame.Sessions) != 0 {
		t.Fatal("failed metadata published Session")
	}
}

func TestBoundedSnapshotCoalescesUpsertsAndRetainsStaleView(t *testing.T) {
	watch := New(nil, nil)
	for n := uint64(1); n <= 205; n++ {
		id := uuid.NewString()
		watch.sessions[id] = entry{session: &dispatcherpb.Session{SessionId: id}, revision: n}
	}
	watch.revision = 205
	watch.initialized = true
	watch.connected = true
	first, cursor, changed := watch.read(0)
	if len(first.Sessions) != 100 || first.CaughtUp {
		t.Fatal("snapshot batch unbounded or prematurely caught up")
	}
	second, cursor, _ := watch.read(cursor)
	if len(second.Sessions) != 100 || second.CaughtUp {
		t.Fatal("second snapshot batch invalid")
	}
	third, _, _ := watch.read(cursor)
	if len(third.Sessions) != 5 || !third.CaughtUp {
		t.Fatal("snapshot did not finish")
	}
	watch.disconnected()
	select {
	case <-changed:
	default:
		t.Fatal("connection loss did not wake browsers")
	}
	stale, _, _ := watch.read(0)
	if len(stale.Sessions) != 100 || stale.UpdatesConnected {
		t.Fatal("connection loss discarded retained view or stayed live")
	}
}
