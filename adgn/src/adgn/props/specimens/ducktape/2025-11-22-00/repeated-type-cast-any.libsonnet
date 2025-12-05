local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    ToolExec.svelte lines 40-51 and ToolJson.svelte line 33 repeatedly cast item.content
    to `any` instead of using proper typed TypeScript models (ExecContent, JsonContent)
    that already exist in types.ts. ToolExec has `(item.content as any)` repeated 8
    times in 13 lines to access cmd, stdout, exit_code, is_error, etc.

    Problems: Bypasses TypeScript checking, enables typos that won't be caught, unclear
    what fields exist on content, no IDE autocomplete, duplication across components,
    types already exist but aren't being used.

    Use Svelte reactive statements with discriminated union type guards (check
    content_kind === 'Exec'/'Json' first, then TypeScript narrows type automatically).
    Benefits: type safety, no cast duplication, autocomplete, typo protection. Consider
    generating TypeScript types from Pydantic models to prevent this class of issues,
    add ESLint rules discouraging `as any`.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/web/src/components/ToolExec.svelte': [
      [40, 51],   // Repeated (item.content as any) casts
    ],
    'adgn/src/adgn/agent/web/src/components/ToolJson.svelte': [
      [33, 33],   // (c as any).content_kind and (c as any).result
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/web/src/components/ToolExec.svelte'],
    ['adgn/src/adgn/agent/web/src/components/ToolJson.svelte'],
  ],
)
