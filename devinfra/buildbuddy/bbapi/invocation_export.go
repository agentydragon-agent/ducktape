package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"

	bespb "github.com/buildbuddy-io/buildbuddy/proto/build_event_stream"
	"github.com/spf13/cobra"
)

// invocationExport is the stable, structured form consumed by CI planners.
// Keep these fields aligned with devinfra/buildbuddy/ci/bes.py's Invocation.
type invocationExport struct {
	Outputs           []invocationOutput      `json:"outputs"`
	TestStatus        map[string]string       `json:"test_status"`
	TestSummaries     []invocationTestSummary `json:"test_summaries"`
	Finished          bool                    `json:"finished"`
	Successful        bool                    `json:"successful"`
	Command           *string                 `json:"command"`
	RequestedPatterns *[]string               `json:"requested_patterns"`
	ExplicitCmdLine   *[]string               `json:"explicit_cmd_line"`
	CommitSHA         *string                 `json:"commit_sha"`
}

type invocationOutput struct {
	Label       string `json:"label"`
	Path        string `json:"path"`
	URI         string `json:"uri"`
	Digest      string `json:"digest"`
	Size        int64  `json:"size"`
	OutputGroup string `json:"output_group"`
	Aspect      string `json:"aspect"`
}

type invocationTestSummary struct {
	Label           string `json:"label"`
	ConfigurationID string `json:"configuration_id"`
	Status          string `json:"status"`
	AttemptCount    *int64 `json:"attempt_count,omitempty"`
	CachedCount     *int64 `json:"cached_count,omitempty"`
}

// Only these fields need raw JSON: protobuf scalars and repeated fields cannot
// distinguish an absent count/command line from one explicitly reported empty.
type invocationPresenceEvent struct {
	TestSummary *struct {
		AttemptCount json.RawMessage `json:"attemptCount"`
		CachedCount  json.RawMessage `json:"totalNumCached"`
	} `json:"testSummary"`
	OptionsParsed *struct {
		ExplicitCmdLine json.RawMessage `json:"explicitCmdLine"`
	} `json:"optionsParsed"`
}

func invocationExportCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "export <invocation-id>",
		Short: "Export a finished invocation as structured JSON",
		Args:  cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			raw, err := readInvocationEvents(c, args[0])
			if err != nil {
				return err
			}
			exported, err := parseInvocationExport(raw)
			if err != nil {
				return err
			}
			return writeInvocationExport(exported)
		},
	}
}

// writeInvocationExport emits JSON regardless of the global --json flag.
func writeInvocationExport(exported invocationExport) error {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	return encoder.Encode(exported)
}

// parseInvocationExport parses a raw BuildBuddy BES stream into the stable CI
// contract. Counts use pointers so an absent value differs from explicit zero.
func parseInvocationExport(raw []byte) (invocationExport, error) {
	var rawEvents []json.RawMessage
	if err := json.Unmarshal(raw, &rawEvents); err != nil {
		return invocationExport{}, fmt.Errorf("parse invocation event stream: %w", err)
	}
	if rawEvents == nil {
		return invocationExport{}, fmt.Errorf("invocation event stream is not a list")
	}

	artifacts, err := parseArtifacts(raw)
	if err != nil {
		return invocationExport{}, err
	}
	result := invocationExport{
		Outputs:       make([]invocationOutput, 0, len(artifacts)),
		TestStatus:    map[string]string{},
		TestSummaries: []invocationTestSummary{},
	}
	for _, artifact := range artifacts {
		if artifact.Kind != kindBuild {
			continue
		}
		path := artifact.Name
		if artifact.PathPrefix != "" {
			path = artifact.PathPrefix + "/" + path
		}
		result.Outputs = append(result.Outputs, invocationOutput{
			Label:       artifact.Label,
			Path:        path,
			URI:         artifact.URI,
			Digest:      artifact.Digest,
			Size:        artifact.Size,
			OutputGroup: artifact.OutputGroup,
			Aspect:      artifact.Aspect,
		})
	}

	finishedCount := 0
	successfulCount := 0
	var commands []string
	var explicitCmdLines []*[]string
	var requestedPatterns []string
	var commitSHAs []string
	for i, rawEvent := range rawEvents {
		var event bespb.BuildEvent
		if err := unmarshalJSON(rawEvent, &event); err != nil {
			return invocationExport{}, fmt.Errorf("parse invocation event %d: %w", i, err)
		}
		var presence invocationPresenceEvent
		if err := json.Unmarshal(rawEvent, &presence); err != nil {
			return invocationExport{}, fmt.Errorf("parse invocation event presence %d: %w", i, err)
		}

		if summary := event.GetTestSummary(); summary != nil {
			id := event.GetId().GetTestSummary()
			if id == nil || id.GetLabel() == "" {
				return invocationExport{}, fmt.Errorf("test summary event %d has no target label", i)
			}
			var attemptCountJSON, cachedCountJSON json.RawMessage
			if presence.TestSummary != nil {
				attemptCountJSON = presence.TestSummary.AttemptCount
				cachedCountJSON = presence.TestSummary.CachedCount
			}
			attemptCount, err := parseOptionalInt64(attemptCountJSON)
			if err != nil {
				return invocationExport{}, fmt.Errorf("parse test summary attempt count in event %d: %w", i, err)
			}
			cachedCount, err := parseOptionalInt64(cachedCountJSON)
			if err != nil {
				return invocationExport{}, fmt.Errorf("parse test summary cached count in event %d: %w", i, err)
			}
			configurationID := ""
			if config := id.GetConfiguration(); config != nil {
				configurationID = config.GetId()
			}
			label := id.GetLabel()
			status := summary.GetOverallStatus().String()
			result.TestStatus[label] = status
			result.TestSummaries = append(result.TestSummaries, invocationTestSummary{
				Label:           label,
				ConfigurationID: configurationID,
				Status:          status,
				AttemptCount:    attemptCount,
				CachedCount:     cachedCount,
			})
			continue
		}

		if finished := event.GetFinished(); finished != nil {
			finishedCount++
			if finished.GetExitCode().GetName() == "SUCCESS" {
				successfulCount++
			}
		}
		if started := event.GetStarted(); started != nil {
			commands = append(commands, started.GetCommand())
		}
		if options := event.GetOptionsParsed(); options != nil {
			if presence.OptionsParsed != nil {
				if explicit, ok := rawStringSlice(presence.OptionsParsed.ExplicitCmdLine); ok {
					explicitCmdLines = append(explicitCmdLines, &explicit)
				} else {
					explicitCmdLines = append(explicitCmdLines, nil)
				}
			} else {
				explicitCmdLines = append(explicitCmdLines, nil)
			}
		}
		if pattern := event.GetId().GetPattern(); pattern != nil {
			requestedPatterns = append(requestedPatterns, pattern.GetPattern()...)
		}
		if status := event.GetWorkspaceStatus(); status != nil {
			for _, item := range status.GetItem() {
				if item.GetKey() == "COMMIT_SHA" {
					commitSHAs = append(commitSHAs, item.GetValue())
				}
			}
		}
	}

	result.Finished = finishedCount == 1
	result.Successful = finishedCount == 1 && successfulCount == 1
	if len(commands) == 1 {
		result.Command = stringPointer(commands[0])
	}
	if len(explicitCmdLines) == 1 && explicitCmdLines[0] != nil {
		result.ExplicitCmdLine = explicitCmdLines[0]
	}
	if len(requestedPatterns) > 0 {
		result.RequestedPatterns = &requestedPatterns
	}
	commitValues := map[string]bool{}
	for _, sha := range commitSHAs {
		commitValues[sha] = true
	}
	if len(commitValues) == 1 {
		for sha := range commitValues {
			if sha != "" {
				result.CommitSHA = stringPointer(sha)
			}
		}
	}
	return result, nil
}

func parseOptionalInt64(raw json.RawMessage) (*int64, error) {
	text := strings.TrimSpace(string(raw))
	if len(raw) == 0 || text == "null" {
		return nil, nil
	}
	if strings.HasPrefix(text, "\"") {
		var parsed string
		if err := json.Unmarshal([]byte(text), &parsed); err != nil {
			return nil, err
		}
		text = parsed
	}
	value, err := strconv.ParseInt(text, 10, 64)
	if err != nil {
		return nil, fmt.Errorf("expected an integer, got %s", text)
	}
	return &value, nil
}

func rawStringSlice(raw json.RawMessage) ([]string, bool) {
	if len(raw) == 0 {
		return nil, false
	}
	var values []json.RawMessage
	if err := json.Unmarshal(raw, &values); err != nil || values == nil {
		return nil, false
	}
	result := make([]string, 0, len(values))
	for _, item := range values {
		var value string
		if err := json.Unmarshal(item, &value); err != nil {
			return nil, false
		}
		result = append(result, value)
	}
	return result, true
}

func stringPointer(value string) *string { return &value }
