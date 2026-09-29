# Thread conversation frontend

The Thread route lives here: `projected_session.tsx` presents the conversation and
operator commands, `thread_sync.ts` defines the view-facing contract, and
`thread_store.tsx` implements that contract with Electric. History rows, local
commands, disclosures, thread title, and chronological debug belong to this
feature. Shared shell, API client, and generic rendering components stay in the
parent frontend package; the sidebar's grouping logic stays beside its caller.

The Bazel targets remain in `../BUILD.bazel` and keep their names. This directory
move does not change the thread sync or scrolling contracts; see `../SPEC.md` for
the scroll guarantees and `../../../docs/thread_view_sync.md` for sync design.
