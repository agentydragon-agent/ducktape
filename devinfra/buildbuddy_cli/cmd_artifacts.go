package main

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"strings"

	"github.com/spf13/cobra"
)

// BES event stream types (subset for test output artifacts).
// See build_event_stream.proto in github.com/bazelbuild/bazel.

type besEvent struct {
	ID         *besEventID    `json:"id,omitempty"`
	TestResult *besTestResult `json:"testResult,omitempty"`
}

type besEventID struct {
	TestResult *besTestResultID `json:"testResult,omitempty"`
}

type besTestResultID struct {
	Label string `json:"label,omitempty"`
}

type besTestResult struct {
	TestActionOutput []besFile `json:"testActionOutput,omitempty"`
}

type besFile struct {
	Name string `json:"name,omitempty"`
	URI  string `json:"uri,omitempty"`
}

type artifact struct {
	Label string `json:"label"`
	Name  string `json:"name"`
	URI   string `json:"uri"`
}

func artifactsCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "artifacts",
		Short: "List or download build/test artifacts",
	}
	cmd.AddCommand(artifactsLsCmd())
	cmd.AddCommand(artifactsGetCmd())
	return cmd
}

func artifactsLsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "ls <invocation-id>",
		Short: "List test output artifacts",
		Args:  cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			artifacts, err := listArtifacts(c, args[0])
			if err != nil {
				return err
			}
			if jsonOutput {
				b, err := json.MarshalIndent(artifacts, "", "  ")
				if err != nil {
					return err
				}
				os.Stdout.Write(b)
				fmt.Println()
				return nil
			}
			for _, a := range artifacts {
				fmt.Printf("%-60s  %s\n", a.Label, a.Name)
			}
			return nil
		},
	}
}

func artifactsGetCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "get <invocation-id> <name-substring>",
		Short: "Download an artifact by name match (prints to stdout)",
		Args:  cobra.ExactArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			artifacts, err := listArtifacts(c, args[0])
			if err != nil {
				return err
			}
			substr := args[1]
			var matches []artifact
			for _, a := range artifacts {
				if strings.Contains(a.Label+"/"+a.Name, substr) {
					matches = append(matches, a)
				}
			}
			if len(matches) == 0 {
				return fmt.Errorf("no artifacts matching %q", substr)
			}
			if len(matches) > 1 {
				fmt.Fprintf(os.Stderr, "Multiple matches for %q:\n", substr)
				for _, a := range matches {
					fmt.Fprintf(os.Stderr, "  %s  %s\n", a.Label, a.Name)
				}
				fmt.Fprintf(os.Stderr, "Using first match: %s %s\n", matches[0].Label, matches[0].Name)
			}
			downloadURL := fmt.Sprintf("%s/file/download?bytestream_url=%s",
				c.baseURL, url.QueryEscape(matches[0].URI))
			data, err := c.fetchURL(downloadURL)
			if err != nil {
				return err
			}
			_, err = os.Stdout.Write(data)
			return err
		},
	}
}

func listArtifacts(c *client, invocationID string) ([]artifact, error) {
	besURL := fmt.Sprintf("%s/file/download?invocation_id=%s&artifact=raw_json",
		c.baseURL, url.QueryEscape(invocationID))
	data, err := c.fetchURL(besURL)
	if err != nil {
		return nil, fmt.Errorf("fetch BES event stream: %w", err)
	}
	var events []besEvent
	if err := json.Unmarshal(data, &events); err != nil {
		return nil, fmt.Errorf("parse BES event stream: %w", err)
	}
	var result []artifact
	for _, ev := range events {
		if ev.TestResult == nil {
			continue
		}
		label := ""
		if ev.ID != nil && ev.ID.TestResult != nil {
			label = ev.ID.TestResult.Label
		}
		for _, f := range ev.TestResult.TestActionOutput {
			result = append(result, artifact{Label: label, Name: f.Name, URI: f.URI})
		}
	}
	return result, nil
}
