local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale='App currently serves as both composition root and partial façade. TUI code reaches through app to call inner services (CoderAgent, Sessions, Permissions) directly, producing duplicated guards and unclear ownership. Pick one strategy: strengthen App as the agent façade (IsAgentBusy/RunAgent/CancelAgent/etc.) or treat App strictly as composition root and pass services by DI consistently.',
  occurrences=[
    {
      files: { 'internal/tui/page/chat/chat.go': [[320, 320], [335, 336], [344, 344], [352, 355], [376, 376], [679, 679], [699, 699], [820, 820]] },
      note: 'chat page reaches through p.app.CoderAgent.* and p.app.Sessions.Create(...) in many places; prefer unified agent façade or DI.',
      expect_caught_from: [['internal/tui/page/chat/chat.go']],
    },
    {
      files: { 'internal/tui/tui.go': [[178, 178], [192, 192], [253, 253], [417, 417], [436, 436]] },
      note: 'top-level TUI model uses a.app.CoderAgent.* for busy checks and a.app.Permissions for toggles/grants; centralize agent/permission interactions behind App or DI.',
      expect_caught_from: [['internal/tui/tui.go']],
    },
    {
      files: { 'internal/tui/components/chat/editor/editor.go': [[144, 149], [240, 240], [333, 333], [647, 647]] },
      note: 'editor reaches through to m.app.CoderAgent.IsSessionBusy/IsBusy and m.app.Permissions — consider routing via App façade methods or inject services explicitly.',
      expect_caught_from: [['internal/tui/components/chat/editor/editor.go']],
    },
  ],
)
