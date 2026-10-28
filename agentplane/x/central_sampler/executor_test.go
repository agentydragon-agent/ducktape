package centralsampler

import (
	"context"
	"encoding/json"
	"testing"
)

func TestExecutorRejectsMalformedInputBeforeDispatch(t *testing.T) {
	for _, tc := range []struct {
		name string
		tool string
		args map[string]any
	}{
		{"negative exec yield", "exec_command", map[string]any{"cmd": "touch /tmp/should-not-run", "yield_time_ms": json.Number("-1")}},
		{"fractional stdin yield", "write_stdin", map[string]any{"session_id": "test-process", "yield_time_ms": json.Number("1.5")}},
		{"non-string chars", "write_stdin", map[string]any{"session_id": "test-process", "chars": true}},
		{"non-boolean EOF", "write_stdin", map[string]any{"session_id": "test-process", "eof": "true"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// No store or transport: invalid inputs must fail before accessing either.
			executor := &Executor{}
			if _, err := executor.Invoke(context.Background(), tc.tool, json.RawMessage(mustJSON(tc.args))); err == nil {
				t.Fatal("malformed input accepted")
			}
		})
	}
}

func TestExecutorReadRejectsMissingOutput(t *testing.T) {
	for _, raw := range []string{
		`{}`, `{"chunks":null}`, `{"chunks":[null]}`, `{"chunks":[{}]}`,
		`{"chunks":[{"chunk":null}]}`, `{"chunks":[{"chunk":"invalid base64"}]}`,
	} {
		var result executorReadResult
		if err := json.Unmarshal([]byte(raw), &result); err == nil {
			t.Errorf("accepted malformed process/read result: %s", raw)
		}
	}
	// Pinned exec-server returns an empty array when there is no output yet.
	var result executorReadResult
	if err := json.Unmarshal([]byte(`{"chunks":[],"nextSeq":0,"exited":false,"exitCode":null,"closed":false,"failure":null}`), &result); err != nil {
		t.Fatal(err)
	}
}
