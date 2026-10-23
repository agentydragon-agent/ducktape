# Forgejo encryption-key cutover, 2026-10-23

Activated the SOPS `replacement` key from PR #11588 using the maintenance
configuration in PR #11597. The production migration implementation was unchanged.
Haku credential/token recovery is a separate step: re-encryption preserves values
and does not invalidate credentials recoverable from older backups.

## Restore point and migration

- Scaled Forgejo to zero at 02:49:51 UTC and waited until every application pod,
  including terminating pods, was absent. Preserved `app.ini` in the temporary
  `forgejo/forgejo-key-cutover-config-backup` Secret; no contents were printed.
- Final CNPG backup: `forgejo-key-cutover`, database `forgejo-db-ssd`, backup ID
  `20261023T025219`; completed 02:53:17 UTC. Begin/end LSN:
  `8E/610128A0` / `8E/62000110`. The previous isolated restore/reverse rehearsal
  is recorded separately; backup completion is not an additional restore drill.
- `forgejo-key-apply` committed all four Actions secrets and the one encrypted
  mirror address. `forgejo-key-verify` authenticated all five with `replacement`.
- An ephemeral salted HMAC baseline inside the in-cluster probe confirmed all
  five plaintext values were preserved. No values or comparison digests were
  printed or uploaded to CI.

Migration image (same OCI manifest digest as the rehearsal image):

```text
ghcr.io/agentydragon/forgejo-key-migration@sha256:89516e63d6fbf4161a5915e12b999379a55b213ff8325eaec36682dc82b3032f
```

## Production checks

At 03:16:11 UTC both final replicas were ready and independently passed:

- Secret projection selects `replacement`; `SECRET_KEY_URI` points at the
  mounted file; no populated inline key or environment override.
- Read-only comparison of all five records against the original baseline.
- Native Forgejo web login and mirror settings decryption, addressed directly
  to each Pod IP.

Replicas: `forgejo-797576cb89-qd2tk` on `ovh-ns103711` and
`forgejo-797576cb89-x8wd9` on `ovh-ns102453`. Both used the rehearsed Forgejo image:

```text
code.forgejo.org/forgejo/forgejo@sha256:8f97b55ca162ef3b538c6c78a2a077df9f2143c41d80b2bc6b6920f8d430df34
```

The public HTTPS version endpoint also returned `15.0.8+gitea-1.22.0`.

## Corrections found during execution

1. Haku's image-pull credential cannot access the `ducktape-ci` migration
   package. A preload through a managed credential in another namespace did not
   make the uncredentialed private-image pod start. PR #11617 switches to the
   independently available GHCR copy, whose digest and embedded source match.
2. The first read-only database check failed at connection establishment; a
   connectivity probe and the subsequent read-only Job succeeded. No `apply`
   retry was performed.
3. Flux removed ordinary `kubectl` maintenance patches. The pre-apply guard
   stopped without creating the migration Job. Suspending the parent and using
   `--field-manager=forgejo-cutover` made the pauses persist; all guards were
   confirmed before applying.
4. Chart 17.1.6 concatenated the pre-script's final `fi` with its `# END`
   comment. The standalone pre-script/config rehearsal missed this embedding
   boundary. Added a trailing newline, checked the complete rendered script's
   Bash syntax, and observed successful production startup. Both Secret script
   and Helm values were corrected while normal reconciliation was held.
5. Disabled upgrade retries/remediation during activation so Helm could not
   automatically deploy the old-key release against the migrated database.
   Restore normal remediation only after the replacement-key upgrade succeeds.
