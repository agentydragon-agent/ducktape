package main

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	bespb "github.com/buildbuddy-io/buildbuddy/proto/build_event_stream"
	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
)

type artifact struct {
	Label string `json:"label"`
	Name  string `json:"name"`
	URI   string `json:"uri"`
}

func artifactCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "artifact <invocation-id> [name-substr]",
		Short: "Manage build artifacts",
		Long: `List or fetch build artifacts from a BuildBuddy invocation.

  bbapi artifact <id>              list artifacts
  bbapi artifact <id> <substr>     stream matching artifact to stdout (legacy)

Prefer the explicit subcommands:
  bbapi artifact list <id>
  bbapi artifact cat  <id> <substr>     stream to stdout
  bbapi artifact download <id> <substr> save to file`,
		Args: cobra.RangeArgs(1, 2),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			artifacts, err := listArtifactsResolved(c, args[0])
			if err != nil {
				return err
			}
			if len(args) == 1 {
				return printArtifacts(artifacts)
			}
			return catArtifact(c, artifacts, args[1])
		},
	}
	cmd.AddCommand(artifactListCmd())
	cmd.AddCommand(artifactCatCmd())
	cmd.AddCommand(artifactDownloadCmd())
	return cmd
}

func artifactListCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "list <invocation-id>",
		Aliases: []string{"ls"},
		Short:   "List artifacts for an invocation",
		Args:    cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			artifacts, err := listArtifactsResolved(c, args[0])
			if err != nil {
				return err
			}
			return printArtifacts(artifacts)
		},
	}
}

func artifactCatCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "cat <invocation-id> <name-substr>",
		Short: "Stream artifact content to stdout",
		Args:  cobra.ExactArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			artifacts, err := listArtifactsResolved(c, args[0])
			if err != nil {
				return err
			}
			return catArtifact(c, artifacts, args[1])
		},
	}
}

func artifactDownloadCmd() *cobra.Command {
	var output string
	cmd := &cobra.Command{
		Use:   "download <invocation-id> <name-substr>",
		Short: "Download artifact to a file (defaults to the artifact filename)",
		Args:  cobra.ExactArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			artifacts, err := listArtifactsResolved(c, args[0])
			if err != nil {
				return err
			}
			return downloadArtifactToFile(c, artifacts, args[1], output)
		},
	}
	cmd.Flags().StringVarP(&output, "output", "o", "", "output file path (default: artifact filename)")
	return cmd
}

func printArtifacts(artifacts []artifact) error {
	if jsonOutput {
		b, err := json.MarshalIndent(artifacts, "", "  ")
		if err != nil {
			return err
		}
		os.Stdout.Write(b)
		fmt.Println()
		return nil
	}
	t := newTable()
	t.header("LABEL", "NAME")
	for _, a := range artifacts {
		t.row(a.Label, a.Name)
	}
	t.flush()
	return nil
}

func resolveArtifact(artifacts []artifact, substr string) (artifact, error) {
	var matches []artifact
	for _, a := range artifacts {
		if strings.Contains(a.Label+"/"+a.Name, substr) {
			matches = append(matches, a)
		}
	}
	if len(matches) == 0 {
		seen := map[string]bool{}
		count := 0
		fmt.Fprintf(os.Stderr, "No artifacts matching %q\n", substr)
		if len(artifacts) > 0 {
			fmt.Fprintf(os.Stderr, "\nAvailable labels (first 5):\n")
			for _, a := range artifacts {
				if !seen[a.Label] {
					seen[a.Label] = true
					fmt.Fprintf(os.Stderr, "  %s\n", a.Label)
					count++
					if count >= 5 {
						remaining := 0
						for _, a2 := range artifacts {
							if !seen[a2.Label] {
								seen[a2.Label] = true
								remaining++
							}
						}
						if remaining > 0 {
							fmt.Fprintf(os.Stderr, "  ... (%d more labels)\n", remaining)
						}
						break
					}
				}
			}
			fmt.Fprintf(os.Stderr, "\nHint: match is against \"label/name\" (e.g., \"test_handlers/test.log\")\n")
		}
		return artifact{}, fmt.Errorf("no artifacts matching %q", substr)
	}
	if len(matches) > 1 {
		fmt.Fprintf(os.Stderr, "Multiple matches for %q:\n", substr)
		for _, a := range matches {
			fmt.Fprintf(os.Stderr, "  %s  %s\n", a.Label, a.Name)
		}
		fmt.Fprintf(os.Stderr, "Using first match: %s %s\n", matches[0].Label, matches[0].Name)
	}
	return matches[0], nil
}

func catArtifact(c *client, artifacts []artifact, substr string) error {
	match, err := resolveArtifact(artifacts, substr)
	if err != nil {
		return err
	}
	downloadURL := fmt.Sprintf("%s/file/download?bytestream_url=%s",
		c.baseURL, url.QueryEscape(match.URI))
	data, err := c.fetchURL(downloadURL)
	if err != nil {
		return err
	}
	_, err = os.Stdout.Write(data)
	return err
}

func downloadArtifactToFile(c *client, artifacts []artifact, substr string, output string) error {
	match, err := resolveArtifact(artifacts, substr)
	if err != nil {
		return err
	}
	if output == "" {
		output = filepath.Base(match.Name)
	}
	downloadURL := fmt.Sprintf("%s/file/download?bytestream_url=%s",
		c.baseURL, url.QueryEscape(match.URI))
	data, err := c.fetchURL(downloadURL)
	if err != nil {
		return err
	}
	if err := os.WriteFile(output, data, 0o644); err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "Downloaded to %s (%d bytes)\n", output, len(data))
	return nil
}

// listArtifactsResolved lists artifacts, auto-resolving workflow invocations to children.
func listArtifactsResolved(c *client, invocationID string) ([]artifact, error) {
	ids, err := resolveInvocationIDs(c, invocationID)
	if err != nil {
		return nil, err
	}
	var all []artifact
	for _, id := range ids {
		arts, err := listArtifacts(c, id)
		if err != nil {
			return nil, fmt.Errorf("list artifacts for %s: %w", id, err)
		}
		all = append(all, arts...)
	}
	return all, nil
}

func listArtifacts(c *client, invocationID string) ([]artifact, error) {
	besURL := fmt.Sprintf("%s/file/download?invocation_id=%s&artifact=raw_json",
		c.baseURL, url.QueryEscape(invocationID))
	data, err := c.fetchURL(besURL)
	if err != nil {
		return nil, fmt.Errorf("fetch BES event stream: %w", err)
	}
	var rawEvents []json.RawMessage
	if err := json.Unmarshal(data, &rawEvents); err != nil {
		return nil, fmt.Errorf("parse BES event stream: %w", err)
	}
	var result []artifact
	for _, raw := range rawEvents {
		var ev bespb.BuildEvent
		if err := protojson.Unmarshal(raw, &ev); err != nil {
			return nil, fmt.Errorf("parse BES event: %w", err)
		}
		tr := ev.GetTestResult()
		if tr == nil {
			continue
		}
		label := ""
		if tid := ev.GetId().GetTestResult(); tid != nil {
			label = tid.GetLabel()
		}
		for _, f := range tr.GetTestActionOutput() {
			result = append(result, artifact{Label: label, Name: f.GetName(), URI: f.GetUri()})
		}
	}
	return result, nil
}
