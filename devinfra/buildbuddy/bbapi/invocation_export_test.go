package main

import (
	"encoding/json"
	"strings"
	"testing"
)

const invocationExportStream = `[
 {"id":{"namedSet":{"id":"inner"}},
  "namedSetOfFiles":{"files":[
    {"pathPrefix":["bazel-out","k8-fastbuild","bin"],"name":"pkg/app.whl",
     "uri":"bytestream://host/blobs/app/12","digest":"app","length":"12"},
    {"name":"pkg/same.txt","uri":"bytestream://host/blobs/source/3","digest":"source","length":"3"}]}},
 {"id":{"namedSet":{"id":"left"}},
  "namedSetOfFiles":{"fileSets":[{"id":"inner"}]}},
 {"id":{"namedSet":{"id":"right"}},
  "namedSetOfFiles":{"fileSets":[{"id":"inner"}],"files":[
    {"pathPrefix":["bazel-out","k8-fastbuild","bin"],"name":"pkg/same.txt",
     "uri":"bytestream://host/blobs/generated/3","digest":"generated","length":"3"}]}},
 {"id":{"namedSet":{"id":"lint"}},
  "namedSetOfFiles":{"files":[
    {"pathPrefix":["bazel-out","k8-fastbuild","bin"],"name":"pkg/app.mypy_stdout",
     "uri":"bytestream://host/blobs/lint/5","digest":"lint","length":"5"}]}},
 {"id":{"targetCompleted":{"label":"//pkg:app"}},
  "completed":{"outputGroup":[{"name":"default","fileSets":[{"id":"left"},{"id":"right"}]}]}},
 {"id":{"targetCompleted":{"label":"//pkg:app","aspect":"//devinfra/lint:linters.bzl%mypy_aspect"}},
  "completed":{"outputGroup":[{"name":"mypy","fileSets":[{"id":"lint"}]}]}},
 {"id":{"testSummary":{"label":"//pkg:test","configuration":{"id":"cfg-one"}}},
  "testSummary":{"overallStatus":"PASSED","attemptCount":0,"totalNumCached":"0"}},
 {"id":{"testSummary":{"label":"//pkg:test","configuration":{"id":"cfg-two"}}},
  "testSummary":{"overallStatus":"FLAKY"}},
 {"started":{"command":"test"}},
 {"id":{"pattern":{"pattern":["//pkg:...","//other:target"]}}},
 {"optionsParsed":{"explicitCmdLine":["test","//pkg:..."]}},
 {"workspaceStatus":{"item":[{"key":"COMMIT_SHA","value":"deadbeef"}]}},
 {"finished":{"exitCode":{"name":"SUCCESS"}}}
]`

func TestParseInvocationExportWalksFileSetDAGAndKeepsFullPaths(t *testing.T) {
	got, err := parseInvocationExport([]byte(invocationExportStream))
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Outputs) != 4 {
		t.Fatalf("got %d outputs, want one app wheel, two same-named files and one aspect report: %+v", len(got.Outputs), got.Outputs)
	}
	byPath := map[string]invocationOutput{}
	for _, output := range got.Outputs {
		byPath[output.Path] = output
	}
	if byPath["bazel-out/k8-fastbuild/bin/pkg/app.whl"].Digest != "app" {
		t.Errorf("nested wheel output missing or wrong: %+v", byPath)
	}
	if byPath["pkg/same.txt"].Digest != "source" || byPath["bazel-out/k8-fastbuild/bin/pkg/same.txt"].Digest != "generated" {
		t.Errorf("same-named files were collapsed across path prefixes: %+v", byPath)
	}
	if byPath["bazel-out/k8-fastbuild/bin/pkg/app.mypy_stdout"].Aspect != "//devinfra/lint:linters.bzl%mypy_aspect" ||
		byPath["bazel-out/k8-fastbuild/bin/pkg/app.mypy_stdout"].OutputGroup != "mypy" {
		t.Errorf("aspect output metadata missing: %+v", byPath)
	}
	for _, output := range got.Outputs {
		if output.Path == "bazel-out/k8-fastbuild/bin/pkg/app.whl" && output.Size != 12 {
			t.Errorf("size = %d, want 12", output.Size)
		}
	}
}

func TestParseInvocationExportPreservesSummaryPresenceAndConfigurations(t *testing.T) {
	got, err := parseInvocationExport([]byte(invocationExportStream))
	if err != nil {
		t.Fatal(err)
	}
	if len(got.TestSummaries) != 2 {
		t.Fatalf("got %d summaries, want both configurations", len(got.TestSummaries))
	}
	first, second := got.TestSummaries[0], got.TestSummaries[1]
	if first.ConfigurationID != "cfg-one" || first.Status != "PASSED" || first.AttemptCount == nil || *first.AttemptCount != 0 || first.CachedCount == nil || *first.CachedCount != 0 {
		t.Errorf("first summary lost explicit zero values: %+v", first)
	}
	if second.ConfigurationID != "cfg-two" || second.Status != "FLAKY" || second.AttemptCount != nil || second.CachedCount != nil {
		t.Errorf("second summary should retain absent count fields: %+v", second)
	}
	if got.TestStatus["//pkg:test"] != "FLAKY" {
		t.Errorf("test status should retain last summary value: %+v", got.TestStatus)
	}
	encoded, err := json.Marshal(got.TestSummaries)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(encoded), `"attempt_count":0`) || strings.Contains(string(encoded), `"cached_count":null`) {
		t.Errorf("JSON does not distinguish absent and zero counts: %s", encoded)
	}
}

func TestParseInvocationExportPreservesUnambiguousProvenance(t *testing.T) {
	got, err := parseInvocationExport([]byte(invocationExportStream))
	if err != nil {
		t.Fatal(err)
	}
	if !got.Finished || !got.Successful {
		t.Errorf("finished/successful = %v/%v, want true/true", got.Finished, got.Successful)
	}
	if got.Command == nil || *got.Command != "test" {
		t.Errorf("command = %v, want test", got.Command)
	}
	if got.RequestedPatterns == nil || strings.Join(*got.RequestedPatterns, ",") != "//pkg:...,//other:target" {
		t.Errorf("requested patterns = %v", got.RequestedPatterns)
	}
	if got.ExplicitCmdLine == nil || strings.Join(*got.ExplicitCmdLine, " ") != "test //pkg:..." {
		t.Errorf("explicit command line = %v", got.ExplicitCmdLine)
	}
	if got.CommitSHA == nil || *got.CommitSHA != "deadbeef" {
		t.Errorf("commit SHA = %v", got.CommitSHA)
	}
}

func TestParseInvocationExportRejectsAmbiguousProvenance(t *testing.T) {
	stream := `[
 {"started":{"command":"test"}},
 {"started":{"command":"build"}},
 {"optionsParsed":{"explicitCmdLine":["test"]}},
 {"optionsParsed":{"explicitCmdLine":["build"]}},
 {"id":{"pattern":{"pattern":["//pkg:..."]}}},
 {"workspaceStatus":{"item":[{"key":"COMMIT_SHA","value":"one"}]}},
 {"workspaceStatus":{"item":[{"key":"COMMIT_SHA","value":"two"}]}},
 {"finished":{"exitCode":{"name":"SUCCESS"}}},
 {"finished":{"exitCode":{"name":"SUCCESS"}}}
]`
	got, err := parseInvocationExport([]byte(stream))
	if err != nil {
		t.Fatal(err)
	}
	if got.Command != nil || got.ExplicitCmdLine != nil || got.CommitSHA != nil {
		t.Errorf("ambiguous provenance was guessed: %+v", got)
	}
	if got.RequestedPatterns == nil || strings.Join(*got.RequestedPatterns, ",") != "//pkg:..." {
		t.Errorf("requested patterns = %v", got.RequestedPatterns)
	}
	if got.Finished || got.Successful {
		t.Errorf("two finished events must not be reported as a uniquely finished invocation: %v/%v", got.Finished, got.Successful)
	}
}

func TestParseInvocationExportRejectsNonListInput(t *testing.T) {
	if _, err := parseInvocationExport([]byte(`{"event":true}`)); err == nil {
		t.Fatal("expected non-list stream to be rejected")
	}
}
