import { Code, Text } from "@mantine/core";
import type { JSX } from "react";
import { z } from "zod";

import { definePreview, type ArgumentsPreview } from "./entry";

// Unknown arguments fail closed rather than making an unshown parameter actionable.
const podsInNamespace = z.strictObject({
  namespace: z.string().min(1),
  fieldSelector: z.string().min(1).optional(),
  labelSelector: z.string().min(1).optional(),
});

function PodsInNamespace({ args }: { args: z.infer<typeof podsInNamespace> }): JSX.Element {
  return (
    <Text size="sm" style={{ overflowWrap: "anywhere" }}>
      List pods in namespace <Code>{args.namespace}</Code>
      {args.fieldSelector !== undefined && (
        <>
          {" · field selector "}
          <Code>{args.fieldSelector}</Code>
        </>
      )}
      {args.labelSelector !== undefined && (
        <>
          {" · label selector "}
          <Code>{args.labelSelector}</Code>
        </>
      )}
    </Text>
  );
}

export const podsInNamespacePreview: ArgumentsPreview = definePreview(podsInNamespace, PodsInNamespace);

// This is intentionally a separate widget from the expanded card: each Action owns both
// representations, and only the compact one grants the collapsed strip a decision control.
function PodsInNamespaceCompact({ args }: { args: z.infer<typeof podsInNamespace> }): JSX.Element {
  return (
    <Text size="sm" style={{ overflowWrap: "anywhere" }}>
      Get pods · namespace <Code>{args.namespace}</Code>
      {args.fieldSelector !== undefined && (
        <>
          {" · field selector "}
          <Code>{args.fieldSelector}</Code>
        </>
      )}
      {args.labelSelector !== undefined && (
        <>
          {" · label selector "}
          <Code>{args.labelSelector}</Code>
        </>
      )}
    </Text>
  );
}

export const podsInNamespaceCompact: ArgumentsPreview = definePreview(podsInNamespace, PodsInNamespaceCompact);
