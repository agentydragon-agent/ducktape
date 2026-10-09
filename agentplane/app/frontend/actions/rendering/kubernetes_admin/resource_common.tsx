import type { JSX } from "react";
import { z } from "zod";

import { Chip } from "../chips";

export const resource = {
  apiVersion: z.string().min(1),
  kind: z.string().min(1),
  name: z.string().min(1),
  namespace: z.string().min(1),
};

export function ResourceChips({ args }: { args: { apiVersion: string; kind: string; name: string; namespace: string } }): JSX.Element {
  return (
    <>
      <Chip label="API" value={args.apiVersion} />
      <Chip label="kind" value={args.kind} />
      <Chip label="name" value={args.name} />
      <Chip label="namespace" value={args.namespace} />
    </>
  );
}

