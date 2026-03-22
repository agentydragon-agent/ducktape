package main

import (
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/spf13/cobra"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	cachepb "github.com/buildbuddy-io/buildbuddy/proto/cache"
	eventlogpb "github.com/buildbuddy-io/buildbuddy/proto/eventlog"
	executionpb "github.com/buildbuddy-io/buildbuddy/proto/execution_stats"
	invocationpb "github.com/buildbuddy-io/buildbuddy/proto/invocation"
)

var jsonOutput bool

func main() {
	root := &cobra.Command{
		Use:   "bbapi",
		Short: "Query the BuildBuddy API",
	}
	root.PersistentFlags().BoolVar(&jsonOutput, "json", false, "Output raw JSON")

	root.AddCommand(invocationsCmd())
	root.AddCommand(logCmd())
	root.AddCommand(executionsCmd())
	root.AddCommand(cacheCmd())
	root.AddCommand(artifactsCmd())

	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}

func invocationsCmd() *cobra.Command {
	var repo string
	var count int32
	cmd := &cobra.Command{
		Use:   "invocations",
		Short: "List recent invocations",
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
			req := &invocationpb.SearchInvocationRequest{
				Query: &invocationpb.InvocationQuery{RepoUrl: repo},
				Count: count,
			}
			resp := &invocationpb.SearchInvocationResponse{}
			if err := c.call("SearchInvocation", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			for _, inv := range resp.GetInvocation() {
				dur := fmtDurationUsec(inv.GetDurationUsec())
				created := time.UnixMicro(inv.GetCreatedAtUsec())
				sha := inv.GetCommitSha()
				if len(sha) > 8 {
					sha = sha[:8]
				}
				fmt.Printf("%-36s  %s  %5s  %-20s  %s  %s\n",
					inv.GetInvocationId(),
					created.Format("2006-01-02 15:04"),
					dur,
					inv.GetCommand()+" "+strings.Join(inv.GetPattern(), " "),
					inv.GetInvocationStatus().String(),
					sha,
				)
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&repo, "repo", "", "Repository URL (default: auto-detect from git)")
	cmd.Flags().Int32Var(&count, "count", 10, "Number of invocations to list")
	return cmd
}

func logCmd() *cobra.Command {
	var minLines int32
	cmd := &cobra.Command{
		Use:   "log <invocation-id>",
		Short: "Print build log",
		Args:  cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			req := &eventlogpb.GetEventLogChunkRequest{
				InvocationId: args[0],
				MinLines:     minLines,
			}
			resp := &eventlogpb.GetEventLogChunkResponse{}
			if err := c.call("GetEventLogChunk", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			os.Stdout.Write(resp.GetBuffer())
			return nil
		},
	}
	cmd.Flags().Int32Var(&minLines, "lines", 500, "Minimum lines to fetch")
	return cmd
}

func executionsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "executions <invocation-id>",
		Short: "List remote executions",
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
			for _, ex := range resp.GetExecution() {
				status := "OK"
				if s := ex.GetStatus(); s != nil && s.GetCode() != 0 {
					status = fmt.Sprintf("code=%d %s", s.GetCode(), s.GetMessage())
				}
				fmt.Printf("%-36s  stage=%-10s  %s\n",
					ex.GetExecutionId(),
					ex.GetStage().String(),
					status,
				)
			}
			return nil
		},
	}
}

func cacheCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "cache <invocation-id>",
		Short: "Show cache scorecard",
		Args:  cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			req := &cachepb.GetCacheScoreCardRequest{
				InvocationId: args[0],
			}
			resp := &cachepb.GetCacheScoreCardResponse{}
			if err := c.call("GetCacheScoreCard", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			for _, r := range resp.GetResults() {
				fmt.Printf("%-12s  %-40s  %s\n",
					r.GetActionMnemonic(),
					r.GetTargetId(),
					r.GetCacheType().String(),
				)
			}
			return nil
		},
	}
}

func printProtoJSON(msg proto.Message) error {
	b, err := protojson.MarshalOptions{Indent: "  "}.Marshal(msg)
	if err != nil {
		return err
	}
	_, err = os.Stdout.Write(b)
	fmt.Println()
	return err
}

func fmtDurationUsec(us int64) string {
	d := time.Duration(us) * time.Microsecond
	switch {
	case d >= time.Hour:
		return fmt.Sprintf("%.0fh", d.Hours())
	case d >= time.Minute:
		return fmt.Sprintf("%.0fm", d.Minutes())
	default:
		return fmt.Sprintf("%.0fs", d.Seconds())
	}
}
