local I = import '../../specimen_issues.libsonnet';

// iss-021-parameter-rendering
// Centralize parameter rendering (URL/FilePath/Timeout) used in tool header and copy-to-clipboard code.

I.issueOneOccurrence(
  id='iss-021-parameter-rendering',
  rationale='Multiple places in renderer/tool.go build nearly identical parameter display strings (URL, File Path via fsext.PrettyPath, Timeout as seconds->duration). Centralize into shared helpers (e.g., formatParamFilePath, formatParamURL, formatParamTimeout) or a per-tool registry to avoid duplicated formatting logic and ensure consistent presentation across copy-to-clipboard and headers.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'internal/tui/components/chat/messages/tool.go': [[284,292],[317,322],[360,368]],
    'internal/tui/components/chat/messages/renderer.go': [[255,256],[293,304],[338,354],[460,460]],
  },
)
