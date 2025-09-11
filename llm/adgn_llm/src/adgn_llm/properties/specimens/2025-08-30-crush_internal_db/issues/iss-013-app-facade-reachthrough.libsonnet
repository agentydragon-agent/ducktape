local I = import '../../specimen_issues.libsonnet';

// iss-013-app-facade-reachthrough
// App façade vs reach-through: TUI frequently reaches through app to inner services (CoderAgent/Sessions/Permissions), creating a leaky façade and Law-of-Demeter violations.

I.issueWithOccurrences(
  id='iss-013-app-facade-reachthrough',
  rationale='App currently serves as both composition root and partial façade. TUI code reaches through app to call inner services (CoderAgent, Sessions, Permissions) directly, producing duplicated guards and unclear ownership. Pick one strategy: strengthen App as the agent façade (IsAgentBusy/RunAgent/CancelAgent/etc.) or treat App strictly as composition root and pass services by DI consistently.',
  occurrences=[
    { files: { 'internal/tui/page/chat/chat.go': [ [320,320], [335,336], [344,344], [352,355], [376,376], [679,679], [699,699], [820,820] ] }, note: 'chat page reaches through p.app.CoderAgent.* and p.app.Sessions.Create(...) in many places; prefer unified agent façade or DI.' },
    { files: { 'internal/tui/tui.go': [ [178,178], [192,192], [253,253], [417,417], [436,436] ] }, note: 'top-level TUI model uses a.app.CoderAgent.* for busy checks and a.app.Permissions for toggles/grants; centralize agent/permission interactions behind App or DI.' },
    { files: { 'internal/tui/components/chat/editor/editor.go': [ [144,149], [240,240], [333,333], [647,647] ] }, note: 'editor reaches through to m.app.CoderAgent.IsSessionBusy/IsBusy and m.app.Permissions — consider routing via App façade methods or inject services explicitly.' },
  ],
  properties=[],
)
