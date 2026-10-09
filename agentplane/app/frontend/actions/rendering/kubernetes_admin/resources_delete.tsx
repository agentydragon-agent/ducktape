import type { JSX } from "react";
import { z } from "zod";

import { Chip, CompactCall } from "../chips";
import { definePreview, type ArgumentsPreview } from "../entry";

import { resource, ResourceChips } from "./resource_common";

const remove = z.strictObject({ ...resource, gracePeriodSeconds: z.int().nonnegative().optional() });

function Delete({ args }: { args: z.infer<typeof remove> }): JSX.Element {
  return (
    <CompactCall operation="Delete resource">
      <ResourceChips args={args} />
      <Chip
        label="grace period"
        value={args.gracePeriodSeconds === undefined ? "default" : `${args.gracePeriodSeconds}s`}
      />
    </CompactCall>
  );
}

export const resourcesDeleteCompact: ArgumentsPreview = definePreview(remove, Delete);
