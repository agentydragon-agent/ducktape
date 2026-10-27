# Plaid mirror clients

`finance.plaid.pgweb.query(sql)` returns rows as dictionaries from pgweb's
`POST /api/query`. The default deployment uses HTTP Basic username `plaid` and
its password placeholder discovered from Agentplane's live rules. Override
`base_url` and `username` for another deployment; the matching rules must admit it.

Read-only access is enforced by the deployment's PostgreSQL role. The helper does
not parse or restrict SQL. Give result columns distinct names with SQL aliases;
duplicate names raise instead of silently overwriting values.
