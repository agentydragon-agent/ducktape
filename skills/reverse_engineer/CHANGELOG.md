# reverse_engineer skill — changelog

Append-only log of edits to `SKILL.md`. Not packaged into the skill
tarball (`skill_package` srcs in `BUILD.bazel` only include `SKILL.md`
and `examples/`).

Each entry is a dated bullet with: what changed, what failure mode it's
addressing, and how we'll know if it helped.

## 2026-04-29

- **Added a "No speculation. Read it or test it." axiom** to the top of
  `SKILL.md`. Failure mode it targets: speculative-but-plausible asm
  reads producing recovered code that round-trips its own self-tests
  but doesn't match the binary's actual output. Specifically observed
  in the 1h Sonnet eval rollout
  (<evals/x/notes/2026_04_29_sonnet_review_haiku.md>) — Sonnet
  identified a cipher-shaped function, wrote a Feistel implementation
  that decrypted what it encrypted, but had the wrong key-derivation
  function (it had read a related-but-not-on-call-path routine), so
  the cipher was wrong. The new axiom phrases the principle generally:
  the signal for whether your RE impl is correct must be causally
  entangled with the actual artifact, not just internally consistent.
  How we'll know it helped: re-run the eval after the change. Watch
  for (a) earlier capture of a known plaintext/ciphertext pair from
  the running binary, (b) less time spent on disconnected
  cipher-shaped functions, (c) recovery that actually matches a
  binary-produced ciphertext.
