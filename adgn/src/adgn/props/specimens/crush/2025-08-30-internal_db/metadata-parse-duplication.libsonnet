local I = import '../../lib.libsonnet';


I.issue(
  rationale='Multiple renderers (bash/view/edit/multiedit) repeat the same pattern: attempt to unmarshal v.result.Metadata into a tool-specific metadata struct and, on error, fall back to rendering plain content. Centralize this into a small helper (e.g., tryUnmarshalMeta(v, &meta) (ok bool)) to avoid duplication and drift.',
  filesToRanges={
    'internal/tui/components/chat/messages/renderer.go': [[222, 226], [262, 266], [298, 301], [346, 350]],
  },
)
