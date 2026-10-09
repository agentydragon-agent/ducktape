import type { JSX } from "react";
import { z } from "zod";

import { Chip, CompactCall } from "../chips";
import { definePreview, type ArgumentsPreview } from "../entry";

const events = z.strictObject({
  namespace: z.string().min(1).optional(),
  fieldSelector: z.string().min(1).optional(),
});

function Events({ args }: { args: z.infer<typeof events> }): JSX.Element {
  return (
    <CompactCall operation="List events">
      <Chip label="namespace" value={args.namespace ?? "all namespaces"} />
      {args.fieldSelector !== undefined && <Chip label="field selector" value={args.fieldSelector} />}
    </CompactCall>
  );
}

export const eventsListCompact: ArgumentsPreview = definePreview(events, Events);
