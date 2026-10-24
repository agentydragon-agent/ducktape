package codex

import (
	"os"
	"path/filepath"
	"testing"

	eventpb "github.com/agentydragon/ducktape/agentplane/proto/event"
	"github.com/agentydragon/ducktape/agentplane/runner/go/harness"
)

func TestReadCodexHistoryIgnoresArrayCustomToolOutput(t *testing.T) {
	directory := t.TempDir()
	writeCodexHistory(t, directory, "thread-array-custom-output", `{"type":"response_item","payload":{"type":"message","id":"message-1","role":"assistant","content":[{"type":"output_text","text":"kept"}]}}
{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"custom-1","output":[{"type":"input_text","text":"tool output"}]}}
`)

	recovered, err := readCodexHistory(directory, "thread-array-custom-output", map[string]harness.ObservedItem{
		"message-1": {ItemID: "message-1", Kind: eventpb.ItemKind_ITEM_KIND_ASSISTANT_TEXT},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got := recovered["message-1"].Text; got != "kept" {
		t.Fatalf("recovered assistant text = %q, want %q", got, "kept")
	}
}

func TestReadCodexHistoryDecodesArrayCustomToolOutput(t *testing.T) {
	directory := t.TempDir()
	writeCodexHistory(t, directory, "thread-array-custom-call-output", `{"type":"response_item","payload":{"type":"custom_tool_call","call_id":"call-1"}}
{"type":"response_item","payload":{"type":"custom_tool_call_output","call_id":"call-1","output":[{"type":"input_text","text":"tool "},{"type":"input_text","text":"output"}]}}
`)

	observed := harness.ObservedItem{
		ItemID: "call-1", Kind: eventpb.ItemKind_ITEM_KIND_TOOL_CALL, Output: "tool output", Completed: true,
	}
	recovered, err := readCodexHistory(directory, "thread-array-custom-call-output", map[string]harness.ObservedItem{"call-1": observed})
	if err != nil {
		t.Fatal(err)
	}
	recoveredItem, ok := recovered["call-1"]
	if !ok {
		t.Fatal("function call output was not recovered")
	}
	if got := harness.CompareItem(observed, &recoveredItem).GetDisposition(); got != eventpb.RecoveryDisposition_RECOVERY_DISPOSITION_RETAINED {
		t.Fatalf("recovery disposition = %s, want retained", got)
	}
}

func TestReadCodexHistoryDecodesStringFunctionOutput(t *testing.T) {
	directory := t.TempDir()
	writeCodexHistory(t, directory, "thread-string-function-output", `{"type":"response_item","payload":{"type":"function_call","call_id":"call-1"}}
{"type":"response_item","payload":{"type":"function_call_output","call_id":"call-1","output":"tool output"}}
`)

	observed := harness.ObservedItem{
		ItemID: "call-1", Kind: eventpb.ItemKind_ITEM_KIND_TOOL_CALL, Output: "tool output", Completed: true,
	}
	recovered, err := readCodexHistory(directory, "thread-string-function-output", map[string]harness.ObservedItem{"call-1": observed})
	if err != nil {
		t.Fatal(err)
	}
	recoveredItem, ok := recovered["call-1"]
	if !ok {
		t.Fatal("function call output was not recovered")
	}
	if got := harness.CompareItem(observed, &recoveredItem).GetDisposition(); got != eventpb.RecoveryDisposition_RECOVERY_DISPOSITION_RETAINED {
		t.Fatalf("recovery disposition = %s, want retained", got)
	}
}

func writeCodexHistory(t *testing.T, directory, sessionID, records string) {
	t.Helper()
	path := filepath.Join(directory, "sessions", "2026", "10", "07", "rollout-"+sessionID+".jsonl")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(records), 0o600); err != nil {
		t.Fatal(err)
	}
}
