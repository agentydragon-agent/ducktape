# Debundle Authoring Followups

The tree-shaped authoring config has been reshaped and is compiled directly by
`debundle` when callers pass tree-shaped source arguments. Remaining work:

- Add a separate browser-harness asset root only if a real corpus needs static
  asset inputs to come from somewhere other than `inputs.root`.
