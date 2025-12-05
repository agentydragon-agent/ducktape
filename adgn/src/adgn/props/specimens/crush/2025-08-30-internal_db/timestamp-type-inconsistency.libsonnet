local I = import '../../lib.libsonnet';

// - internal/pubsub/broker.go: now := time.Now().UnixMilli()
// - internal/session/session.go: CreatedAt/UpdatedAt int64
// - internal/transform/transform.go: CreatedAt int64
//
// Align types: prefer time.Time / time.Duration or explicit unit-suffixed integer names.

I.issueMulti(
  rationale= |||
    Use `time.Time` for timestamps, `time.Duration` for timeouts/durations (avoid bare ints; if you must use int, suffix units in names).
  |||,
  occurrences=[
    { files: { 'internal/llm/tools/download.go': [[17, 27], [155, 166]] }, note: 'download.go: `Timeout`/`maxTimeout` should be time.Duration or suffixed (timeoutMS)', expect_caught_from: [['internal/llm/tools/download.go']] },
    { files: { 'internal/llm/tools/fetch.go': [[1, 6], [60, 68], [120, 124]] }, note: 'fetch.go: `Timeout int` should be time.Duration', expect_caught_from: [['internal/llm/tools/fetch.go']] },
    { files: { 'internal/llm/tools/tools.go': [[1, 10]] }, note: 'tools.go: `StartedAt`/`UpdatedAt int64` should be time.Time or suffixed (ms epoch)', expect_caught_from: [['internal/llm/tools/tools.go']] },
    { files: { 'internal/message/content.go': [[41, 62], [338, 378]] }, note: 'content.go: `{Started,Finished,Created,Updated}At`, `Finish.Time` should be time.Time', expect_caught_from: [['internal/message/content.go']] },
    { files: { 'internal/message/message.go': [[120, 136], [228, 236]] }, note: 'message.go: Watermarks.*TS and Message timestamps should be time.Time (UpdatedAt microseconds)', expect_caught_from: [['internal/message/message.go']] },
    { files: { 'internal/history/file.go': [[1, 20]] }, note: 'file.go: CreatedAt/UpdatedAt int64 should be time.Time', expect_caught_from: [['internal/history/file.go']] },
    { files: { 'internal/tui/components/chat/chat.go': [[500, 520]] }, note: 'chat.go: lastUserMessageTime int64 should be time.Time (epoch seconds)', expect_caught_from: [['internal/tui/components/chat/chat.go']] },
    { files: { 'internal/tui/components/chat/messages/renderer.go': [[420, 436]] }, note: 'renderer.go: timeout int should be time.Duration (seconds)', expect_caught_from: [['internal/tui/components/chat/messages/renderer.go']] },
    { files: { 'internal/pubsub/broker.go': [[50, 58], [160, 172]] }, note: 'broker.go: now := time.Now().UnixMilli() should use time.Time directly', expect_caught_from: [['internal/pubsub/broker.go']] },
    { files: { 'internal/session/session.go': [[21, 23], [140, 146]] }, note: 'session.go: CreatedAt/UpdatedAt int64 should be time.Time', expect_caught_from: [['internal/session/session.go']] },
    { files: { 'internal/transform/transform.go': [[34, 38]] }, note: 'transform.go: CreatedAt int64 should be time.Time', expect_caught_from: [['internal/transform/transform.go']] },
  ],
)
