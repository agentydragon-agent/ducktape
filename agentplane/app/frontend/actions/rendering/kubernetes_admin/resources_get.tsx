import type { JSX } from "react";
import { z } from "zod";

import { CompactCall } from "../chips";
import { definePreview, type ArgumentsPreview } from "../entry";

import { resource, ResourceChips } from "./resource_common";

const get = z.strictObject(resource);
function Get({ args }: { args: z.infer<typeof get> }): JSX.Element {
  return (
    <CompactCall operation="Get resource">
      <ResourceChips args={args} />
    </CompactCall>
  );
}

export const resourcesGetCompact: ArgumentsPreview = definePreview(get, Get);
