package api

import (
	"io"
	"strings"
	"testing"
	"time"

	historypb "github.com/agentydragon/ducktape/agentplane/history_service/history_servicepb"
	"github.com/agentydragon/ducktape/agentplane/history_service/storage"
	"github.com/agentydragon/ducktape/agentplane/history_service/testing/spans"
	eventpb "github.com/agentydragon/ducktape/agentplane/proto/event"
	eventlogpb "github.com/agentydragon/ducktape/agentplane/proto/event_log"
	"github.com/google/uuid"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/emptypb"
)

type following struct {
	t      *testing.T
	stream grpc.ServerStreamingClient[historypb.FollowSessionResponse]
}

func (s testServer) follow(t *testing.T, request *historypb.FollowSessionRequest) following {
	t.Helper()
	stream, err := s.client.FollowSession(bearing(t, readerToken), request)
	if err != nil {
		t.Fatal(err)
	}
	return following{t: t, stream: stream}
}

func (f following) receive() *historypb.FollowSessionResponse {
	f.t.Helper()
	response, err := f.stream.Recv()
	if err != nil {
		f.t.Fatalf("FollowSession ended: %v", err)
	}
	return response
}

func (f following) wantEntries(cursors ...uint64) *historypb.FollowSessionResponse {
	f.t.Helper()
	response := f.receive()
	entries := response.GetEntries().GetEntries()
	if len(entries) != len(cursors) {
		f.t.Fatalf("entries frame has %d entries, want cursors %v: %v", len(entries), cursors, response)
	}
	for i, cursor := range cursors {
		if entries[i].GetCursor() != cursor {
			f.t.Fatalf("entries frame cursors do not match: %v, want %v", entries, cursors)
		}
	}
	return response
}

func (f following) wantCaughtUp(through uint64) *historypb.FollowSessionResponse {
	f.t.Helper()
	response := f.receive()
	if response.GetCaughtUp() == nil || response.GetThroughCursor() != through {
		f.t.Fatalf("want caught_up through %d, received %v", through, response)
	}
	return response
}

func (f following) wantReconnectAndCleanEnd() {
	f.t.Helper()
	response := f.receive()
	if response.GetReconnectRequired() == nil {
		f.t.Fatalf("want reconnect_required, received %v", response)
	}
	if _, err := f.stream.Recv(); err != io.EOF {
		f.t.Fatalf("want a clean stream end, received %v", err)
	}
}

func testTurnCompletedEntry(cursor uint64) *eventlogpb.EventEntry {
	entry := testEntry(cursor)
	entry.Event = &eventpb.Event{Observation: &eventpb.Event_TurnCompleted{TurnCompleted: &eventpb.TurnCompleted{TurnId: "test-turn"}}}
	return entry
}

func appendFollowEntries(t *testing.T, server testServer, sessionID uuid.UUID, entries ...*eventlogpb.EventEntry) {
	t.Helper()
	if _, err := server.history.Append(t.Context(), sessionID, entries); err != nil {
		t.Fatal(err)
	}
}

func TestFollowSessionReadsFromCursorAndContinuesWithLiveEntries(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	appendFollowEntries(t, server, sessionID, testEntry(1), testEntry(2))

	follow := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 1}, Follow: true,
	})
	follow.wantEntries(2)
	follow.wantCaughtUp(2)

	appendFollowEntries(t, server, sessionID, testEntry(3))
	follow.wantEntries(3)
	follow.wantCaughtUp(3)
}

func TestFollowSessionFilteredCursorReconnectHasNoGapOrDuplicate(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	appendFollowEntries(t, server, sessionID, testTurnCompletedEntry(1), testEntry(2))
	kinds := []historypb.EventKind{historypb.EventKind_EVENT_KIND_TURN_COMPLETED}

	follow := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Kinds: kinds, Follow: true,
	})
	follow.wantEntries(1)
	follow.wantCaughtUp(2)
	appendFollowEntries(t, server, sessionID, testEntry(3))
	resume := follow.wantCaughtUp(3).GetThroughCursor()

	// Reconnect from the filtered cursor, then commit the next matching event.
	appendFollowEntries(t, server, sessionID, testTurnCompletedEntry(4))
	reconnected := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: resume}, Kinds: kinds,
	})
	reconnected.wantEntries(4)
	reconnected.wantCaughtUp(4)
	if _, err := reconnected.stream.Recv(); err != io.EOF {
		t.Fatalf("non-following reconnect should end after caught_up, got %v", err)
	}
}

func TestFollowSessionStartsBackAndAtTail(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	appendFollowEntries(t, server, sessionID, testEntry(1), testEntry(2), testTurnCompletedEntry(3), testEntry(4))

	back := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_Back{Back: &historypb.StartBack{
			Kind: historypb.EventKind_EVENT_KIND_HARNESS_STDERR, Count: 2,
		}},
	})
	back.wantEntries(2, 3, 4)
	back.wantCaughtUp(4)
	if _, err := back.stream.Recv(); err != io.EOF {
		t.Fatalf("non-following back read should end after caught_up, got %v", err)
	}

	tail := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_Tail{Tail: &emptypb.Empty{}}, Follow: true,
	})
	tail.wantCaughtUp(4)
	appendFollowEntries(t, server, sessionID, testEntry(5))
	tail.wantEntries(5)
	tail.wantCaughtUp(5)
}

func TestFollowSessionRejectsMissingHistoryAndInvalidInputs(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	unknownSession := uuid.NewString()
	tests := map[string]struct {
		request *historypb.FollowSessionRequest
		want    codes.Code
	}{
		"unknown Session": {
			request: &historypb.FollowSessionRequest{SessionId: unknownSession, Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}},
			want:    codes.NotFound,
		},
		"cursor past committed tail": {
			request: &historypb.FollowSessionRequest{SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 1}},
			want:    codes.OutOfRange,
		},
		"missing start": {request: &historypb.FollowSessionRequest{SessionId: sessionID.String()}, want: codes.InvalidArgument},
		"unknown kind filter": {
			request: &historypb.FollowSessionRequest{
				SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Kinds: []historypb.EventKind{historypb.EventKind(9999)},
			},
			want: codes.InvalidArgument,
		},
		"unspecified kind filter": {
			request: &historypb.FollowSessionRequest{
				SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Kinds: []historypb.EventKind{historypb.EventKind_EVENT_KIND_UNSPECIFIED},
			},
			want: codes.InvalidArgument,
		},
		"zero back count": {
			request: &historypb.FollowSessionRequest{SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_Back{Back: &historypb.StartBack{
				Kind: historypb.EventKind_EVENT_KIND_HARNESS_STDERR,
			}}},
			want: codes.InvalidArgument,
		},
	}
	for name, test := range tests {
		t.Run(name, func(t *testing.T) {
			stream, err := server.client.FollowSession(bearing(t, readerToken), test.request)
			if err == nil {
				_, err = stream.Recv()
			}
			if got := status.Code(err); got != test.want {
				t.Errorf("FollowSession error = %v, want %v", got, test.want)
			}
		})
	}
}

func TestFollowSessionStreamsSettlementAndLaterRemovalCorrections(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	span := spans.ClaudeText([]string{"hello", " world"}, spans.TextOptions{})
	appendFollowEntries(t, server, sessionID, span.Entries[:4]...)
	follow := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Follow: true,
	})
	follow.wantEntries(1, 2, 3, 4)
	follow.wantCaughtUp(4)

	// Appending the completion settles deltas that this follower already sent.
	appendFollowEntries(t, server, sessionID, span.Entries[4:]...)
	var gotCursors []uint64
	var settled *historypb.SettledDeltas
	for {
		response := follow.receive()
		switch {
		case response.GetEntries() != nil:
			for _, entry := range response.GetEntries().GetEntries() {
				gotCursors = append(gotCursors, entry.GetCursor())
			}
		case response.GetSettled() != nil:
			settled = response.GetSettled()
		case response.GetCaughtUp() != nil:
			if response.GetThroughCursor() != 8 {
				t.Fatalf("caught up through %d, want 8", response.GetThroughCursor())
			}
			break
		default:
			t.Fatalf("unexpected frame while awaiting settlement: %v", response)
		}
		if response.GetCaughtUp() != nil {
			break
		}
	}
	if len(gotCursors) != 2 || gotCursors[0] != 7 || gotCursors[1] != 8 {
		t.Fatalf("entries after settlement: %v, want retained completion cursors [7 8]", gotCursors)
	}
	if settled == nil || settled.GetCompletionCursor() != 8 || settled.GetChunkCount() != 2 || len(settled.GetRanges()) != 1 ||
		settled.GetRanges()[0].GetFirst() != 3 || settled.GetRanges()[0].GetLast() != 6 {
		t.Fatalf("settlement correction: %v", settled)
	}

	// Cleanup can remove an entry after the follower passed it; the same covered window gets corrected.
	tx, err := server.db.BeginTx(t.Context(), nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })
	if _, err := tx.ExecContext(t.Context(), "DELETE FROM session_event WHERE session_id = $1 AND cursor = 1", sessionID); err != nil {
		t.Fatal(err)
	}
	if _, err := tx.ExecContext(t.Context(), "INSERT INTO session_event_removed_range (session_id, first_cursor, last_cursor) VALUES ($1, 1, 1)", sessionID); err != nil {
		t.Fatal(err)
	}
	if _, err := tx.ExecContext(t.Context(), "SELECT pg_notify($1, '')", storage.ChannelHistory); err != nil {
		t.Fatal(err)
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	var replayedSettlement, gotRemoved bool
	for {
		response := follow.receive()
		switch {
		case response.GetSettled() != nil:
			replayedSettlement = replayedSettlement || proto.Equal(response.GetSettled(), settled)
		case response.GetRemoved() != nil:
			removed := response.GetRemoved()
			if removed.GetFirst() != 1 || removed.GetLast() != 1 {
				t.Fatalf("removed prior range correction: %v", response)
			}
			gotRemoved = true
		case response.GetCaughtUp() != nil:
			if response.GetThroughCursor() != 8 {
				t.Fatalf("after cleanup, caught up through %d, want 8", response.GetThroughCursor())
			}
			if !gotRemoved || !replayedSettlement {
				t.Fatalf("cleanup refresh replayed settlement=%v and removed=%v before caught_up", replayedSettlement, gotRemoved)
			}
			return
		default:
			t.Fatalf("unexpected cleanup correction frame: %v", response)
		}
	}
}

func TestFollowSessionOmitsSettlementForANonDeltaFilter(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	span := spans.ClaudeText([]string{"hello", " world"}, spans.TextOptions{})
	appendFollowEntries(t, server, sessionID, span.Entries...)
	follow := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0},
		Kinds: []historypb.EventKind{historypb.EventKind_EVENT_KIND_TURN_COMPLETED},
	})
	follow.wantCaughtUp(8)
	if _, err := follow.stream.Recv(); err != io.EOF {
		t.Fatalf("non-delta filter should end after caught_up without settlement, got %v", err)
	}
}

func TestFollowSessionContinuesAcrossProjectionEpochReplacement(t *testing.T) {
	server := newServer(t, time.Minute)
	sessionID, _ := server.record(t)
	if _, err := server.db.ExecContext(t.Context(), `INSERT INTO thread_checkpoint
		(thread_id, source_id, projection_epoch, through_cursor) VALUES ($1, NULL, 'old-epoch', 0)`, sessionID); err != nil {
		t.Fatal(err)
	}
	follow := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Follow: true,
	})
	follow.wantCaughtUp(0)
	if _, err := server.db.ExecContext(t.Context(), "UPDATE thread_checkpoint SET projection_epoch = 'replacement-epoch' WHERE thread_id = $1", sessionID); err != nil {
		t.Fatal(err)
	}
	appendFollowEntries(t, server, sessionID, testEntry(1))
	follow.wantEntries(1)
	follow.wantCaughtUp(1)
}

func TestFollowSessionReconnectsToAnotherReplicaAndHub(t *testing.T) {
	first := newServer(t, time.Hour)
	second := newServer(t, time.Hour)
	sessionID, _ := first.record(t)
	appendFollowEntries(t, first, sessionID, testEntry(1))

	follow := first.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Follow: true,
	})
	follow.wantEntries(1)
	follow.wantCaughtUp(1)
	first.service.Drain()
	follow.wantReconnectAndCleanEnd()

	reconnected := second.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 1}, Follow: true,
	})
	reconnected.wantCaughtUp(1)
	appendFollowEntries(t, second, sessionID, testEntry(2))
	reconnected.wantEntries(2)
	reconnected.wantCaughtUp(2)
}

func TestFollowSessionEndsItsLeaseWithReconnectRequired(t *testing.T) {
	server := newServer(t, 200*time.Millisecond)
	sessionID, _ := server.record(t)
	follow := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: sessionID.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0}, Follow: true,
	})
	follow.wantCaughtUp(0)
	follow.wantReconnectAndCleanEnd()
}

type blockedFollowStream struct {
	grpc.ServerStream
	release chan struct{}
}

func (s blockedFollowStream) Send(*historypb.FollowSessionResponse) error {
	<-s.release
	return nil
}

func TestFollowSessionBoundsAWriteTheCallerDoesNotRead(t *testing.T) {
	stream := blockedFollowStream{release: make(chan struct{})}
	t.Cleanup(func() { close(stream.release) })
	failed := make(chan error, 1)
	go func() {
		failed <- sendWithin(stream, 10*time.Millisecond, &historypb.FollowSessionResponse{})
	}()
	select {
	case err := <-failed:
		if got := status.Code(err); got != codes.DeadlineExceeded {
			t.Errorf("send status %v, want DeadlineExceeded", got)
		}
	case <-time.After(callDeadline):
		t.Fatal("the FollowSession write was not given up on")
	}
}

func TestFollowSessionBoundsEntryFramesAndAllowsOneOversizedEntry(t *testing.T) {
	server := newServer(t, time.Minute)
	countSession, _ := server.record(t)
	many := make([]*eventlogpb.EventEntry, 129)
	for i := range many {
		many[i] = testEntry(uint64(i + 1))
	}
	appendFollowEntries(t, server, countSession, many...)
	counted := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: countSession.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0},
	})
	firstFrame := counted.receive()
	if len(firstFrame.GetEntries().GetEntries()) != 128 {
		t.Fatalf("first count bounded frame had %d entries, want 128", len(firstFrame.GetEntries().GetEntries()))
	}
	counted.wantEntries(129)
	counted.wantCaughtUp(129)
	if _, err := counted.stream.Recv(); err != io.EOF {
		t.Fatalf("count bounded read should end after caught_up, got %v", err)
	}

	bytesSession, _ := server.record(t)
	oversized := testEntry(1)
	oversized.Event.Observation = &eventpb.Event_HarnessStderr{HarnessStderr: &eventpb.HarnessStderr{Text: strings.Repeat("x", storage.FollowBytesLimit+100)}}
	appendFollowEntries(t, server, bytesSession, oversized, testEntry(2))
	byBytes := server.follow(t, &historypb.FollowSessionRequest{
		SessionId: bytesSession.String(), Start: &historypb.FollowSessionRequest_AfterCursor{AfterCursor: 0},
	})
	oversizedFrame := byBytes.receive()
	if entries := oversizedFrame.GetEntries().GetEntries(); len(entries) != 1 || entries[0].GetCursor() != 1 {
		t.Fatalf("oversized entry was not sent alone: %v", oversizedFrame)
	}
	if size := proto.Size(oversizedFrame); size <= storage.FollowBytesLimit {
		t.Fatalf("oversized frame size %d did not exceed the configured byte bound", size)
	}
	byBytes.wantEntries(2)
	byBytes.wantCaughtUp(2)
	if _, err := byBytes.stream.Recv(); err != io.EOF {
		t.Fatalf("byte bounded read should end after caught_up, got %v", err)
	}
}
