import type { JSX } from "react";
import { Code, Stack, Text } from "@mantine/core";

import { type ActionPresentation, expandsForRejectedArguments } from "../presentation";
import { definePreview, type ArgumentsPreview } from "../entry";
import {
  type SearchPullRequestsArguments,
  zSearchPullRequestsArguments,
} from "../../schemas/github/search_pull_requests";

function SearchPullRequestsLabel(): JSX.Element {
  return (
    <Text size="sm" fw={600}>
      Search GitHub pull requests
    </Text>
  );
}

function SearchPullRequestsArgumentsView({ args }: { args: SearchPullRequestsArguments }): JSX.Element {
  return (
    <Stack gap={2}>
      <Text size="sm" style={{ overflowWrap: "anywhere" }}>
        Query: <Code style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{args.query}</Code>
      </Text>
      {args.owner !== undefined && (
        <Text size="sm" style={{ overflowWrap: "anywhere" }}>
          Owner filter: <Code>{args.owner}</Code>
        </Text>
      )}
      {args.repo !== undefined && (
        <Text size="sm" style={{ overflowWrap: "anywhere" }}>
          Repository filter: <Code>{args.repo}</Code>
        </Text>
      )}
      {args.page !== undefined && <Text size="sm">Page {args.page}</Text>}
      {args.perPage !== undefined && <Text size="sm">{args.perPage} results per page</Text>}
      {args.sort !== undefined && <Text size="sm">Sort by {args.sort}</Text>}
      {args.order !== undefined && <Text size="sm">Order: {args.order}</Text>}
      {args.fields !== undefined && (
        <Text size="sm" style={{ overflowWrap: "anywhere" }}>
          Fields: {args.fields.length > 0 ? args.fields.join(", ") : "none"}
        </Text>
      )}
    </Stack>
  );
}

export function offersCardDecisionButtonsSearchPullRequests(args: unknown): boolean {
  return zSearchPullRequestsArguments.safeParse(args).success;
}

export const searchPullRequestsLabel: ArgumentsPreview = definePreview(
  zSearchPullRequestsArguments,
  SearchPullRequestsLabel
);
export const searchPullRequestsArguments: ArgumentsPreview = definePreview(
  zSearchPullRequestsArguments,
  SearchPullRequestsArgumentsView
);

export const searchPullRequestsPresentation: ActionPresentation = {
  label: searchPullRequestsLabel,
  pane: { collapsed: searchPullRequestsArguments, opened: searchPullRequestsArguments },
  details: { arguments: searchPullRequestsArguments },
  offersCardDecisionButtons: offersCardDecisionButtonsSearchPullRequests,
  compactCardExpands: expandsForRejectedArguments(zSearchPullRequestsArguments),
};
