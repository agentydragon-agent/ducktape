import type { JSX } from "react";
import { z } from "zod";

import { Chip, CompactCall } from "./chips";
import { definePreview, type ArgumentsPreview } from "./entry";

// Every compact widget is backed by an exact schema: extra arguments require full review.
const resource = {
  apiVersion: z.string().min(1),
  kind: z.string().min(1),
  name: z.string().min(1),
  namespace: z.string().min(1),
};
const listSelectors = {
  fieldSelector: z.string().min(1).optional(),
  labelSelector: z.string().min(1).optional(),
};
const get = z.strictObject(resource);
const list = z.strictObject({
  apiVersion: resource.apiVersion,
  kind: resource.kind,
  namespace: resource.namespace.optional(),
  ...listSelectors,
});
const remove = z.strictObject({ ...resource, gracePeriodSeconds: z.int().nonnegative().optional() });
const logs = z.strictObject({
  name: z.string().min(1),
  namespace: z.string().min(1),
  container: z.string().min(1).optional(),
  previous: z.boolean().optional(),
  tail: z.int().nonnegative().optional(),
});
const events = z.strictObject({
  namespace: z.string().min(1).optional(),
  fieldSelector: z.string().min(1).optional(),
});

function ResourceChips({ args }: { args: z.infer<typeof get> }): JSX.Element {
  return (
    <>
      <Chip label="API" value={args.apiVersion} />
      <Chip label="kind" value={args.kind} />
      <Chip label="name" value={args.name} />
      <Chip label="namespace" value={args.namespace} />
    </>
  );
}

function Selectors({ args }: { args: z.infer<typeof list> }): JSX.Element {
  return (
    <>
      {args.fieldSelector !== undefined && <Chip label="field selector" value={args.fieldSelector} />}
      {args.labelSelector !== undefined && <Chip label="label selector" value={args.labelSelector} />}
    </>
  );
}

function Get({ args }: { args: z.infer<typeof get> }): JSX.Element {
  return (
    <CompactCall operation="Get resource">
      <ResourceChips args={args} />
    </CompactCall>
  );
}
function List({ args }: { args: z.infer<typeof list> }): JSX.Element {
  return (
    <CompactCall operation="List resources">
      <Chip label="API" value={args.apiVersion} />
      <Chip label="kind" value={args.kind} />
      <Chip label="namespace" value={args.namespace ?? "all namespaces / ignored if cluster-scoped"} />
      <Selectors args={args} />
    </CompactCall>
  );
}
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
function Events({ args }: { args: z.infer<typeof events> }): JSX.Element {
  return (
    <CompactCall operation="List events">
      <Chip label="namespace" value={args.namespace ?? "all namespaces"} />
      {args.fieldSelector !== undefined && <Chip label="field selector" value={args.fieldSelector} />}
    </CompactCall>
  );
}

export const resourcesGetCompact: ArgumentsPreview = definePreview(get, Get);
export const resourcesListCompact: ArgumentsPreview = definePreview(list, List);
export const resourcesDeleteCompact: ArgumentsPreview = definePreview(remove, Delete);
export const podsLogCompact: ArgumentsPreview = definePreview(logs, Logs);
export const eventsListCompact: ArgumentsPreview = definePreview(events, Events);
