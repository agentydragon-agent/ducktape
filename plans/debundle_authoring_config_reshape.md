# Debundle Authoring Followups

The tree-shaped authoring config has already been reshaped to keep output and
teardown policy in CLI/executable-spec space. Remaining work:

- Fold tree-shaped spec compilation into `debundle` itself, while keeping the
  executable spec path available.
- Build the folded executable spec as typed Rust data and emit any generated
  YAML through `serde_yaml`; do not assemble YAML text manually.
- Migrate downstream corpus configs before repinning consumers such as Gaffer.
- Revisit whether `ancillary_chunk_modules.yaml` should stay as a sidecar or
  move into a tree-shaped ownership layout of its own.
- Add a separate browser-harness asset root only if a real corpus needs static
  asset inputs to come from somewhere other than `inputs.root`.
