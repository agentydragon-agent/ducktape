# Plaid mirror clients

`finance.plaid.pgweb.query(statement)` returns rows as dictionaries from pgweb's
`POST /api/query`. The default deployment uses HTTP Basic username `plaid` and
its password placeholder discovered from Agentplane's live rules. Override
`base_url` and `username` for another deployment; the matching rules must admit it.

Pass a SQLAlchemy `Select`. It is compiled with the PostgreSQL dialect and
inline escaped literals in memory because pgweb has no parameter-binding API.
Read-only access is also enforced by the deployment's PostgreSQL role.
Give result columns distinct names with SQL aliases;
duplicate names raise instead of silently overwriting values.

`finance.plaid.transaction_queries.select_transactions(account_ids)` projects
retained transactions for selected active, attached accounts, including the
JSON dates and merchant fields used by spend classification. Pending transactions
remain available for policy decisions. An empty account selection returns no rows.
