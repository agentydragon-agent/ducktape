package orchestrationv1

import (
	"encoding/json"
	"sync/atomic"
	"testing"
	"time"

	historypb "github.com/agentydragon/ducktape/agentplane/history_service/history_servicepb"
	eventpb "github.com/agentydragon/ducktape/agentplane/proto/event"
	eventlogpb "github.com/agentydragon/ducktape/agentplane/proto/event_log"
	"github.com/google/uuid"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
)

func turnArguments(t *testing.T, sandbox SandboxRef, session string, extra map[string]any) string {
	t.Helper()
	args := map[string]any{"sandbox": sandbox, "session_id": session}
	for key, value := range extra {
		args[key] = value
	}
	encoded, err := json.Marshal(args)
	if err != nil {
		t.Fatal(err)
	}
	return string(encoded)
}

func turnEntries(through uint64, events ...*eventpb.Event) *historypb.FollowSessionResponse {
	entries := make([]*eventlogpb.EventEntry, 0, len(events))
	for i, event := range events {
		entries = append(entries, &eventlogpb.EventEntry{Cursor: through - uint64(len(events)-1-i), Event: event})
	}
	return &historypb.FollowSessionResponse{ThroughCursor: through, Frame: &historypb.FollowSessionResponse_Entries{Entries: &historypb.Entries{Entries: entries}}}
}

func TestReadTurnsGroupsConfirmedInputToolsAndFinalAssistantText(t *testing.T) {
	f := newFixture(t)
	sandbox := f.launch(t, "test-turn-reader")
	session := uuid.NewString()
	f.history.hold(summaryOf(f, session, sandbox, nil))
	f.history.follow = func(request *historypb.FollowSessionRequest, stream grpc.ServerStreamingServer[historypb.FollowSessionResponse]) error {
		if request.GetBack().GetKind() != historypb.EventKind_EVENT_KIND_TURN_STARTED || request.GetBack().GetCount() != 2 || request.GetFollow() {
			t.Errorf("read start = %v", request)
		}
		// Split an item's start and completion across pages; reasoning and tools must not replace the final text.
		if err := stream.Send(turnEntries(
			4,
			&eventpb.Event{Observation: &eventpb.Event_TurnStarted{TurnStarted: &eventpb.TurnStarted{TurnId: "test-turn"}}},
			&eventpb.Event{Observation: &eventpb.Event_HarnessUserMessageConfirmed{HarnessUserMessageConfirmed: &eventpb.HarnessUserMessageConfirmed{TurnId: "test-turn", Text: "test input"}}},
			&eventpb.Event{Observation: &eventpb.Event_ItemStarted{ItemStarted: &eventpb.ItemStarted{ItemId: "test-text", Kind: eventpb.ItemKind_ITEM_KIND_ASSISTANT_TEXT}}},
			&eventpb.Event{Observation: &eventpb.Event_ItemCompleted{ItemCompleted: &eventpb.ItemCompleted{ItemId: "test-text", Outcome: &eventpb.ItemCompleted_Text{Text: "earlier"}}}},
		)); err != nil {
			return err
		}
		if err := stream.Send(turnEntries(
			10,
			&eventpb.Event{Observation: &eventpb.Event_ItemStarted{ItemStarted: &eventpb.ItemStarted{ItemId: "test-tool", Kind: eventpb.ItemKind_ITEM_KIND_TOOL_CALL, ToolName: "test_tool"}}},
			&eventpb.Event{Observation: &eventpb.Event_ItemCompleted{ItemCompleted: &eventpb.ItemCompleted{ItemId: "test-text", Outcome: &eventpb.ItemCompleted_Text{Text: "final test response"}}}},
			&eventpb.Event{Observation: &eventpb.Event_ItemStarted{ItemStarted: &eventpb.ItemStarted{ItemId: "test-reason", Kind: eventpb.ItemKind_ITEM_KIND_REASONING}}},
			&eventpb.Event{Observation: &eventpb.Event_ItemCompleted{ItemCompleted: &eventpb.ItemCompleted{ItemId: "test-reason", Outcome: &eventpb.ItemCompleted_Text{Text: "private reasoning"}}}},
			&eventpb.Event{Observation: &eventpb.Event_TurnCompleted{TurnCompleted: &eventpb.TurnCompleted{TurnId: "test-turn", Status: eventpb.TurnStatus_TURN_STATUS_COMPLETED}}},
			&eventpb.Event{Observation: &eventpb.Event_TurnStarted{TurnStarted: &eventpb.TurnStarted{TurnId: "test-running"}}},
		)); err != nil {
			return err
		}
		return stream.Send(&historypb.FollowSessionResponse{ThroughCursor: 12, Frame: &historypb.FollowSessionResponse_CaughtUp{CaughtUp: &emptypb.Empty{}}})
	}
	got := resultOf[Turns](f.attempt(t, f.caller, actionReadTurns, turnArguments(t, sandbox, session, map[string]any{"count": 2})))
	if len(got.Turns) != 2 {
		t.Fatalf("turns = %+v", got)
	}
	turn := got.Turns[0]
	if len(turn.Input) != 1 || turn.Input[0] != "test input" || len(turn.ToolCalls) != 1 || turn.ToolCalls[0].Name != "test_tool" || turn.FinalAssistantMessage == nil || *turn.FinalAssistantMessage != "final test response" || turn.Status == nil || *turn.Status != "TURN_STATUS_COMPLETED" {
		t.Errorf("completed turn = %+v", turn)
	}
	if got.Turns[1].Status != nil {
		t.Errorf("running turn status = %v", got.Turns[1].Status)
	}
	if cursor, err := resumeCursor(got.ResumeToken, sandbox, session); err != nil || cursor != 12 {
		t.Errorf("resume = %d, %v", cursor, err)
	}
}

func TestWaitRenewsAndStopsAtFirstCompletionInABatch(t *testing.T) {
	f := newFixture(t)
	sandbox := f.launch(t, "test-turn-waiter")
	session := uuid.NewString()
	f.history.hold(summaryOf(f, session, sandbox, nil))
	var calls atomic.Int32
	f.history.follow = func(request *historypb.FollowSessionRequest, stream grpc.ServerStreamingServer[historypb.FollowSessionResponse]) error {
		if !request.GetFollow() || len(request.GetKinds()) != 1 || request.GetKinds()[0] != historypb.EventKind_EVENT_KIND_TURN_COMPLETED {
			t.Errorf("wait request = %v", request)
		}
		if calls.Add(1) == 1 {
			if request.GetAfterCursor() != 2 {
				t.Errorf("initial cursor %d", request.GetAfterCursor())
			}
			return stream.Send(&historypb.FollowSessionResponse{ThroughCursor: 5, Frame: &historypb.FollowSessionResponse_ReconnectRequired{ReconnectRequired: &emptypb.Empty{}}})
		}
		if request.GetAfterCursor() != 5 {
			t.Errorf("renewal cursor %d", request.GetAfterCursor())
		}
		return stream.Send(turnEntries(
			7,
			&eventpb.Event{Observation: &eventpb.Event_TurnCompleted{TurnCompleted: &eventpb.TurnCompleted{TurnId: "test-first", Status: eventpb.TurnStatus_TURN_STATUS_FAILED, Error: "test failure"}}},
			&eventpb.Event{Observation: &eventpb.Event_TurnCompleted{TurnCompleted: &eventpb.TurnCompleted{TurnId: "test-next", Status: eventpb.TurnStatus_TURN_STATUS_COMPLETED}}},
		))
	}
	got := resultOf[TurnWait](f.attempt(t, f.caller, actionWaitForTurn, turnArguments(t, sandbox, session, map[string]any{"resume_token": resumeToken(sandbox, session, 2), "wait_seconds": 1})))
	if !got.Completed || got.Turn == nil || got.Turn.TurnID != "test-first" || got.Turn.Status != "TURN_STATUS_FAILED" || got.Turn.Error == nil {
		t.Fatalf("wait = %+v", got)
	}
	if cursor, err := resumeCursor(got.ResumeToken, sandbox, session); err != nil || cursor != 6 {
		t.Errorf("resume = %d, %v; want first completion6, leaving7 for next call", cursor, err)
	}
}

func TestWaitDeadlineReturnsNewestProgressAndRejectsBareEOF(t *testing.T) {
	f := newFixture(t)
	sandbox := f.launch(t, "test-bounded-wait")
	session := uuid.NewString()
	f.history.hold(summaryOf(f, session, sandbox, nil))
	f.executor.readBudget = 100 * time.Millisecond
	f.history.follow = func(_ *historypb.FollowSessionRequest, stream grpc.ServerStreamingServer[historypb.FollowSessionResponse]) error {
		if _, ok := stream.Context().Deadline(); !ok {
			t.Error("follow has no deadline")
		}
		if err := stream.Send(&historypb.FollowSessionResponse{ThroughCursor: 9, Frame: &historypb.FollowSessionResponse_CaughtUp{CaughtUp: &emptypb.Empty{}}}); err != nil {
			return err
		}
		<-stream.Context().Done()
		return status.FromContextError(stream.Context().Err()).Err()
	}
	args := turnArguments(t, sandbox, session, map[string]any{"resume_token": resumeToken(sandbox, session, 2), "wait_seconds": 30})
	got := resultOf[TurnWait](f.attempt(t, f.caller, actionWaitForTurn, args))
	if got.Completed || got.Turn != nil {
		t.Fatalf("wait = %+v", got)
	}
	if cursor, err := resumeCursor(got.ResumeToken, sandbox, session); err != nil || cursor != 9 {
		t.Errorf("resume = %d %v", cursor, err)
	}
	f.history.follow = func(_ *historypb.FollowSessionRequest, _ grpc.ServerStreamingServer[historypb.FollowSessionResponse]) error {
		return nil
	}
	if kind := f.attempt(t, f.caller, actionWaitForTurn, args).failure(); kind != "read_failed" {
		t.Errorf("bare EOF failure = %s", kind)
	}
}

func TestTurnReadsRefuseForeignSessionsAndTokens(t *testing.T) {
	f := newFixture(t)
	sandbox := f.launch(t, "test-read-scope")
	other := f.launch(t, "test-other-scope")
	session := uuid.NewString()
	f.history.hold(summaryOf(f, session, other, nil))
	for _, action := range []string{actionReadTurns, actionWaitForTurn} {
		extra := map[string]any{"count": 1}
		if action == actionWaitForTurn {
			extra = map[string]any{"resume_token": resumeToken(sandbox, session, 0), "wait_seconds": 1}
		}
		if kind := f.attempt(t, f.caller, action, turnArguments(t, sandbox, session, extra)).failure(); kind != "session_not_found" {
			t.Errorf("%s foreign read = %s", action, kind)
		}
	}
	f.history.hold(summaryOf(f, session, sandbox, nil))
	for _, token := range []string{"malformed", resumeToken(other, session, 0), resumeToken(sandbox, uuid.NewString(), 0)} {
		if kind := f.attempt(t, f.caller, actionWaitForTurn, turnArguments(t, sandbox, session, map[string]any{"resume_token": token, "wait_seconds": 1})).failure(); kind != "invalid_arguments" {
			t.Errorf("wrong-scope token = %s", kind)
		}
	}
	f.history.refuse(status.Error(codes.PermissionDenied, "test denied"))
	if kind := f.attempt(t, f.caller, actionReadTurns, turnArguments(t, sandbox, session, map[string]any{"count": 1})).failure(); kind != "read_failed" {
		t.Errorf("denied = %s", kind)
	}
	// The same Sandbox name after replacement is never enough, even when the Session evidence matches.
	sandbox.UID = "00000000-0000-0000-0000-000000000000"
	if kind := f.attempt(t, f.caller, actionReadTurns, turnArguments(t, sandbox, session, map[string]any{"count": 1})).failure(); kind != "sandbox_replaced" {
		t.Errorf("replaced = %s", kind)
	}
}
