# Native remote-tool characterization

This experiment runs the unchanged npm Linux x86-64 Claude Code 2.1.296 binary
against scripted loopback Anthropic Messages and driver-hosted MCP fixtures. Its
independent archive pin leaves the production runner, stable native suite, and
RemoteIO experiment pins unchanged.

```sh
bbr test //agentplane/native/claude/x/remote_tools:test_characterization
```

The suite captures model requests before and after file access, native control
frames, CLI debug logs, a rejecting loopback bridge destination, read/edit state
across native resume and a fresh session, and explicit hook denial. All captures
go to Bazel undeclared outputs. The model responses are scripted; no custom
sampler, real Anthropic account, feature-cache override, or deployed service is
involved. `HTTP_PROXY` and `HTTPS_PROXY` point to a rejecting loopback endpoint;
the model fixture bypasses them through `NO_PROXY`.

The MCP fixture is deliberately a generic read tool with its own explicit path
boundary. It is a comparison with native file access, not an implementation of
remote native tools. The forwarding startup variants cannot establish account
eligibility or hosted bridge behavior. See the [investigation report](../../../../debug/claude_remote_tools_20261027.md)
for observed behavior and the remaining native-serving blocker.
