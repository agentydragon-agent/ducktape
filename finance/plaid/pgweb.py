"""Query a pgweb deployment backed by a SELECT-only PostgreSQL role.

The server role enforces read-only access; this helper does not parse SQL.
"""

from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from agentplane.egress.rule_client import Rules, create_client, load_rules


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


def query(
    sql: str,
    *,
    rules: Rules | None = None,
    base_url: str = "http://plaid-pgweb.plaid-mcp.svc.cluster.local",
    username: str = "plaid",
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    if client is None:
        with create_client(timeout=60) as owned_client:
            return query(sql, rules=rules, base_url=base_url, username=username, client=owned_client)
    if rules is None:
        rules = load_rules(client=client)
    url = f"{base_url.rstrip('/')}/api/query"
    parsed = urlsplit(url)
    if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
        raise ValueError("pgweb base_url must have a hostname and no embedded credentials")
    credential = rules.find_credential(
        host=parsed.hostname, method="POST", path=parsed.path, target_method="METHOD_BASIC_PASSWORD"
    )
    response = client.post(url, data={"query": sql}, auth=httpx.BasicAuth(username, credential.placeholder))
    response.raise_for_status()
    result = QueryResult.model_validate(response.json())
    if len(set(result.columns)) != len(result.columns):
        raise ValueError("pgweb result has duplicate column names; use SQL aliases")
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]
