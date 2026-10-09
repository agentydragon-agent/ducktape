import type { JSX } from "react";
import { z } from "zod";

import { Chip, CompactCall } from "../chips";
import { definePreview, type ArgumentsPreview } from "../entry";

const logs = z.strictObject({
  name: z.string().min(1),
  namespace: z.string().min(1),
  container: z.string().min(1).optional(),
  previous: z.boolean().optional(),
  tail: z.int().nonnegative().optional(),
});

function Logs({ args }: { args: z.infer<typeof logs> }): JSX.Element {
  return (
    <CompactCall operation="Get pod logs">
      <Chip label="pod" value={args.name} />
      <Chip label="namespace" value={args.namespace} />
      <Chip label="container" value={args.container ?? "default"} />
      <Chip label="previous" value={args.previous === true ? "yes" : "no"} />
      <Chip label="tail" value={args.tail ?? 100} />
    </CompactCall>
  );
}

export const podsLogCompact: ArgumentsPreview = definePreview(logs, Logs);
