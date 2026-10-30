package centralsampler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
)

func TestCompletedItemTextJoinsReasoningSummaryParts(t *testing.T) {
	for _, test := range []struct {
		item string
		want string
	}{
		{`{"type":"reasoning","summary":[{"type":"summary_text","text":"**Plan**"},{"type":"summary_text","text":"Read the file."}]}`, "**Plan**\nRead the file."},
		{`{"type":"message","role":"assistant","content":[{"type":"output_text","text":"one "},{"type":"output_text","text":"answer"}]}`, "one answer"},
	} {
		var item ResponsesItem
		if err := json.Unmarshal([]byte(test.item), &item); err != nil {
			t.Fatal(err)
		}
		got, err := responsesText(item)
		if err != nil {
			t.Fatal(err)
		}
		if got != test.want {
			t.Fatalf("responsesText(%s) = %q, want %q", test.item, got, test.want)
		}
	}
}

func TestProviderKeepsOpaqueLargeJSONNumbersExact(t *testing.T) {
	stream := strings.Join([]string{
		`data: {"type":"response.output_item.done","item":{"type":"reasoning","opaque_sequence":9007199254740993}}`,
		"",
		`data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"reasoning","opaque_sequence":9007199254740993}]}}`,
		"",
		"",
	}, "\n")
	response, err := readProviderStream(context.Background(), strings.NewReader(stream), nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := canonicalJSON(response.Output); !strings.Contains(got, `"opaque_sequence":9007199254740993`) {
		t.Fatalf("opaque provider number changed during decoding: %s", got)
	}
	if got := canonicalJSON(response.Audit()); !strings.Contains(got, `"opaque_sequence":9007199254740993`) {
		t.Fatalf("opaque provider number changed in audit evidence: %s", got)
	}
}

func TestResponsesRequestUsesCodexToolsAndPreservesOpaqueContext(t *testing.T) {
	var item ResponsesItem
	if err := json.Unmarshal([]byte(`{"type":"reasoning","encrypted_content":"opaque","provider_sequence":9007199254740993}`), &item); err != nil {
		t.Fatal(err)
	}
	body, err := RequestBody("fixture-model", "fixture-session", []ResponsesItem{item}, nil, nil, ModelConfig{API: "responses", Responses: ResponsesConfig{Dialect: "lite"}, ExecEncoding: "freeform"})
	if err != nil {
		t.Fatal(err)
	}
	if body.Instructions == "" {
		t.Fatal("request has no Codex base instructions")
	}
	encoded, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	tools := map[string]ResponsesAdditionalTool{}
	for _, tool := range body.Input[0].Tools {
		tools[tool.Name] = tool
	}
	if exec := tools["exec"]; exec.Type != "custom" || exec.Format == nil || exec.Format.Type != "grammar" || exec.Format.Syntax != "lark" {
		t.Fatalf("exec is not a Lark-grammar freeform tool: %+v", exec)
	}
	wait := tools["wait"]
	var parameters struct {
		Required []string `json:"required"`
	}
	if err := json.Unmarshal(wait.Parameters, &parameters); err != nil {
		t.Fatal(err)
	}
	if wait.Type != "function" || !slices.Equal(parameters.Required, []string{"cell_id"}) {
		t.Fatalf("wait is not a function tool requiring cell_id: %+v", wait)
	}
	for _, expected := range []string{
		`"type":"additional_tools"`,
		`"include":["reasoning.encrypted_content"]`,
		`"store":false`,
		`"stream":true`,
		// The provider rejects Responses Lite requests without these.
		`"context":"all_turns"`,
		`"parallel_tool_calls":false`,
		`"encrypted_content":"opaque"`,
		`"provider_sequence":9007199254740993`,
	} {
		if !strings.Contains(string(encoded), expected) {
			t.Fatalf("Responses request lost %s: %s", expected, encoded)
		}
	}
}

func TestResponsesDialectAndExecEncodingAreIndependent(t *testing.T) {
	for _, mode := range []string{"standard", "lite"} {
		for _, encoding := range []string{"json", "freeform"} {
			t.Run(mode+"/"+encoding, func(t *testing.T) {
				config := ModelConfig{API: "responses", Responses: ResponsesConfig{Dialect: mode}, ExecEncoding: encoding}
				body, err := RequestBody("fixture", "session", nil, nil, nil, config)
				if err != nil {
					t.Fatal(err)
				}
				var wire map[string]json.RawMessage
				if err := json.Unmarshal(mustJSON(body), &wire); err != nil {
					t.Fatal(err)
				}
				tools := body.Tools
				if mode == "lite" {
					tools = body.Input[0].Tools
					if _, present := wire["tools"]; present {
						t.Fatal("Lite declares top-level tools")
					}
				} else {
					for _, private := range []string{"client_metadata", "reasoning", "include"} {
						if _, present := wire[private]; present {
							t.Fatalf("standard request includes %s", private)
						}
					}
					if strings.Contains(string(wire["input"]), "additional_tools") {
						t.Fatal("standard request includes additional_tools")
					}
				}
				if encoding == "json" {
					if len(tools) != 1 || tools[0].Name != "exec" || tools[0].Type != "function" {
						t.Fatalf("JSON tools: %+v", tools)
					}
					if strings.Contains(tools[0].Description, "Accepts raw JavaScript") {
						t.Fatal("JSON exec advertises raw input")
					}
				} else if len(tools) != 2 || tools[0].Type != "custom" || tools[1].Name != "wait" {
					t.Fatalf("freeform tools: %+v", tools)
				}
				for _, call := range []ResponsesToolCall{
					{Type: ResponsesItemFunctionCall, Name: "exec"},
					{Type: ResponsesItemCustomToolCall, Name: "exec"},
					{Type: ResponsesItemFunctionCall, Name: "wait"},
				} {
					want := encoding == "json" && call.Name == "exec" && call.Type == ResponsesItemFunctionCall || encoding == "freeform" && (call.Name == "wait" || call.Type == ResponsesItemCustomToolCall)
					if call.IsModelTool(config) != want {
						t.Fatalf("wrong tool validation: %+v", call)
					}
				}
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if got := r.Header.Get("x-openai-internal-codex-responses-lite"); (got == "true") != (mode == "lite") {
						t.Errorf("Lite header: %q", got)
					}
					_, _ = w.Write([]byte("data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"output\":[]}}\n\n"))
				}))
				defer server.Close()
				if _, err := Sample(context.Background(), server.Client(), server.URL, "fixture", body, nil, nil, false); err != nil {
					t.Fatal(err)
				}
			})
		}
	}
}

func TestStandardResponsesSerializesTextAndAsyncNotifications(t *testing.T) {
	call := ResponsesToolCall{Type: ResponsesItemFunctionCall, Name: "exec", CallID: "call"}
	output := call.OutputItem([]ResponsesContentPart{{Type: "input_text", Text: "result"}})
	notification := ResponsesItem{Type: ResponsesItemCustomToolOutput, CallID: "call", Output: []ResponsesContentPart{{Type: "input_text", Text: "later"}}}
	body, err := RequestBody("fixture", "session", []ResponsesItem{
		{Type: ResponsesItemFunctionCall, Name: "exec", CallID: "call", Arguments: `{"code":"text(1)"}`}, output, notification,
	}, nil, nil, ModelConfig{API: "responses", Responses: ResponsesConfig{Dialect: "standard"}, ExecEncoding: "json"})
	if err != nil {
		t.Fatal(err)
	}
	encoded := string(mustJSON(body))
	for _, expected := range []string{`"output":"result"`, `"role":"developer"`, `Asynchronous output from exec call call:\nlater`} {
		if !strings.Contains(encoded, expected) {
			t.Fatalf("missing %s in %s", expected, encoded)
		}
	}
	if strings.Contains(encoded, "custom_tool_call_output") {
		t.Fatal("standard notification became a duplicate tool output")
	}
	if body.Input[2].Type != ResponsesItemCustomToolOutput {
		t.Fatal("request encoding mutated durable context")
	}
}

func TestResponsesItemRetainsImageAndAudioContent(t *testing.T) {
	input := []byte(`[{"type":"input_image","image_url":"data:image/png;base64,opaque","detail":"high"},{"type":"input_audio","data":"opaque-audio","format":"wav"}]`)
	var content []ResponsesContentPart
	if err := json.Unmarshal(input, &content); err != nil {
		t.Fatal(err)
	}
	item := ResponsesItem{Type: ResponsesItemCustomToolOutput, CallID: "call-1", Output: content}
	encoded, err := json.Marshal(item)
	if err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{`"type":"input_image"`, `"image_url":"data:image/png;base64,opaque"`, `"type":"input_audio"`, `"format":"wav"`} {
		if !strings.Contains(string(encoded), expected) {
			t.Fatalf("Responses item lost %s: %s", expected, encoded)
		}
	}
}
