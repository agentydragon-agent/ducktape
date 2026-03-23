package main

import (
	"fmt"

	"github.com/spf13/cobra"

	targetpb "github.com/buildbuddy-io/buildbuddy/proto/target"
)

func targetCmd() *cobra.Command {
	var label string
	var filter string
	cmd := &cobra.Command{
		Use:   "target <invocation-id>",
		Short: "List targets in an invocation (default), or use subcommands",
		Args:  cobra.ExactArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			c, err := newClient()
			if err != nil {
				return err
			}
			req := &targetpb.GetTargetRequest{
				InvocationId: args[0],
				TargetLabel:  label,
				Filter:       filter,
			}
			resp := &targetpb.GetTargetResponse{}
			if err := c.call("GetTarget", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			t := newTable()
			t.header("STATUS", "DUR", "RULE", "LABEL")
			for _, g := range resp.GetTargetGroups() {
				for _, tgt := range g.GetTargets() {
					meta := tgt.GetMetadata()
					dur := fmtDurationUsec(tgt.GetTiming().GetDuration().AsDuration().Microseconds())
					lbl := meta.GetLabel()
					if tgt.GetRootCause() {
						lbl += " [ROOT CAUSE]"
					}
					t.row(tgt.GetStatus().String(), dur, meta.GetRuleType(), lbl)
				}
			}
			t.flush()
			return nil
		},
	}
	cmd.Flags().StringVar(&label, "label", "", "Filter to specific target label")
	cmd.Flags().StringVar(&filter, "filter", "", "Substring filter on target labels")
	cmd.AddCommand(targetHistorySubCmd())
	return cmd
}

func targetHistorySubCmd() *cobra.Command {
	var repo string
	var label string
	cmd := &cobra.Command{
		Use:   "history",
		Short: "Show pass/fail/flake history for targets",
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
			req := &targetpb.GetTargetHistoryRequest{
				Query: &targetpb.TargetQuery{
					RepoUrl: repo,
				},
				ServerSidePagination: true,
			}
			resp := &targetpb.GetTargetHistoryResponse{}
			if err := c.call("GetTargetHistory", req, resp); err != nil {
				return err
			}
			if jsonOutput {
				return printProtoJSON(resp)
			}
			for _, th := range resp.GetInvocationTargets() {
				if label != "" && th.GetTarget().GetLabel() != label {
					continue
				}
				fmt.Printf("Target: %s\n", th.GetTarget().GetLabel())
				t := newTable()
				t.header("STATUS", "DUR", "STARTED", "INVOCATION")
				for _, s := range th.GetTargetStatus() {
					started := s.GetTiming().GetStartTime().AsTime().Format("2006-01-02 15:04")
					dur := fmtDurationUsec(s.GetTiming().GetDuration().AsDuration().Microseconds())
					t.row(s.GetStatus().String(), dur, started, s.GetInvocationId())
				}
				t.flush()
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&repo, "repo", "", "Repository URL (default: auto-detect from git)")
	cmd.Flags().StringVar(&label, "label", "", "Filter to specific target label")
	return cmd
}
