local I = import '../../specimens/lib.libsonnet';

// iss-003-timestamps
// Timestamps: Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int, suffix units in names).
//
// Instances:
// - internal/llm/tools/: download.go (`Timeout`/`maxTimeout`), fetch.go (`Timeout int`), tools.go (`StartedAt`/`UpdatedAt int64` ms epoch)
// - internal/message/: content.go (`{Started,Finished,Created,Updated}At`, `Finish.Time`), message.go (Watermarks.*TS and Message timestamps; UpdatedAt microseconds)
// - internal/history/file.go: CreatedAt/UpdatedAt int64
// - internal/tui/components/chat/: chat.go (lastUserMessageTime int64 epoch seconds), messages/renderer.go (timeout int seconds)
// - internal/pubsub/broker.go: now := time.Now().UnixMilli()
// - internal/session/session.go: CreatedAt/UpdatedAt int64
// - internal/transform/transform.go: CreatedAt int64
//
// Align types: prefer time.Time / time.Duration or explicit unit-suffixed integer names.

I.issueWithOccurrences(
  rationale='Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int, suffix units in names).',
  occurrences=[
    { files: { 'internal/llm/tools/download.go': [[17, 27], [155, 166]] } },
    { files: { 'internal/llm/tools/fetch.go': [[1, 6], [60, 68], [120, 124]] } },
    { files: { 'internal/llm/tools/tools.go': [[1, 10]] } },
    { files: { 'internal/message/content.go': [[41, 62], [338, 378]] } },
    { files: { 'internal/message/message.go': [[120, 136], [228, 236]] } },
    { files: { 'internal/history/file.go': [[1, 20]] } },
    { files: { 'internal/tui/components/chat/chat.go': [[500, 520]] } },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [[420, 436]] } },
    { files: { 'internal/pubsub/broker.go': [[50, 58], [160, 172]] } },
    { files: { 'internal/session/session.go': [[21, 23], [140, 146]] } },
    { files: { 'internal/transform/transform.go': [[34, 38]] } },
  ],
)
