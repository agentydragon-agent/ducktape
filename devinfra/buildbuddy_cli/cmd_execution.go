package main

import (
	"fmt"

	"github.com/spf13/cobra"

	executionpb "github.com/buildbuddy-io/buildbuddy/proto/execution_stats"
)

func executionCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "execution <invocation-id>",
		Short: "List executions for an invocation (default), or use subcommands",
		Args:  cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			req := &executionpb.GetExecutionRequest{
				ExecutionLookup: &executionpb.ExecutionLookup{
					InvocationId: args[0],
				},
			}
			resp := &executionpb.GetExecutionResponse{}
			if err := c.call("GetExecution", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			t := newTable()
			t.header("EXECUTION", "STAGE", "STATUS")
			for _, ex := range resp.GetExecution() {
				status := "OK"
				if s := ex.GetStatus(); s != nil && s.GetCode() != 0 {
					status = fmt.Sprintf("code=%d %s", s.GetCode(), s.GetMessage())
				}
				t.row(ex.GetExecutionId(), ex.GetStage().String(), status)
			}
			t.flush()
			return nil
		},
	}
	cmd.AddCommand(executionSearchCmd())
	return cmd
}

func executionSearchCmd() *cobra.Command {
	var repo string
	var count int32
	cmd := &cobra.Command{
		Use:   "search",
		Short: "Search remote executions across invocations",
		RunE: func(_ *cobra.Command, _ []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			if repo == "" {
				repo, err = detectRepoURL()
				if err != nil {
					return fmt.Errorf("auto-detect repo (use --repo to override): %w", err)
				}
			}
			req := &executionpb.SearchExecutionRequest{
				Query: &executionpb.ExecutionQuery{
					RepoUrl: repo,
				},
				Count: count,
			}
			resp := &executionpb.SearchExecutionResponse{}
			if err := c.call("SearchExecution", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			t := newTable()
			t.header("INVOCATION", "EXECUTION", "STAGE", "STATUS", "PATTERN")
			for _, ewm := range resp.GetExecution() {
				ex := ewm.GetExecution()
				meta := ewm.GetInvocationMetadata()
				status := "OK"
				if s := ex.GetStatus(); s != nil && s.GetCode() != 0 {
					status = fmt.Sprintf("code=%d %s", s.GetCode(), s.GetMessage())
				}
				t.row(meta.GetId(), ex.GetExecutionId(), ex.GetStage().String(), status, meta.GetPattern())
			}
			t.flush()
			return nil
		},
	}
	cmd.Flags().StringVar(&repo, "repo", "", "Repository URL (default: auto-detect from git)")
	cmd.Flags().Int32Var(&count, "count", 20, "Number of results to return")
	return cmd
}
