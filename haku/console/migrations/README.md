# Console schema baseline

`0135` is the frozen final schema of the former chain, retaining its last revision
ID. Databases already at `0135` apply nothing. An older deployment must reach
`0135` using the pre-squash image before adopting this baseline; do not stamp an
older database forward or reset it. Downgrade-to-base remains unsupported, as it
was for the previous console baseline.

The baseline uses explicit Alembic/SQLAlchemy definitions to create the surviving tables, types, functions, triggers,
constraints and indexes, including their physical legacy names. It preserves the
`haku-state` logical index registration, without resurrecting the removed chat
registration. The `vector` extension remains an external provisioning prerequisite
(CNPG in deployment, the fixture in tests), not a new superuser migration operation.

## Equivalence evidence

Dumps are independent verification artifacts, not executable migration code.

The original chain at `b78b07ffce` ran in disposable PostgreSQL CI:

- BuildBuddy invocation `f6cf5575-0d05-56d2-9cd4-868341e766f4`.
- Target `//haku/console:test_schema_baseline`.
- Artifact `test.outputs/haku_console_schema.sql`.

The baseline test compares a normalized schema-dump digest with that independent
capture and checks that upgrade-at-head preserves object OIDs and seed registration.
Only version banners, dump comments, psql restriction keys and blank lines are
excluded, not schema SQL. Existing current-schema/ORM and row-preservation tests
remain in `test_agent_authority_schema.py`.

Future migrations are ordinary children of `0135`. Retire the landing-only digest
assertion as the schema advances, rather than retaining historical migration tests
or treating it as a freeze on schema changes. Specimen snapshots are untouched.
