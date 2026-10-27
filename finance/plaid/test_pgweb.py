import base64

import httpx
import pytest
import pytest_bazel

from agentplane.egress.rule_client import Credential, Policy, Rule, Rules, StringList, Target
from finance.plaid.pgweb import QueryError, query


@pytest.mark.parametrize("rows", [[[1, None]], []])
def test_query(rows: list[list[int | None]]) -> None:
    rules = Rules(
        policies=[
            Policy(
                name="test",
                rules=[
                    Rule(
                        hosts=["pgweb.example.test"],
                        methods=StringList(values=["POST"]),
                        paths=StringList(values=["/api/query"]),
                        credential=Credential(
                            name="plaid-pgweb",
                            placeholder="inert-test-password",
                            targets=[Target(method="METHOD_BASIC_PASSWORD", header="Authorization")],
                        ),
                    )
                ],
            )
        ]
    )

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://pgweb.example.test/api/query"
        assert request.content == b"query=SELECT+1%2C+NULL"
        assert (
            request.headers["Authorization"] == "Basic " + base64.b64encode(b"test-user:inert-test-password").decode()
        )
        return httpx.Response(200, json={"columns": ["number", "missing"], "rows": rows})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = query(
            "SELECT 1, NULL", rules=rules, base_url="http://pgweb.example.test", username="test-user", client=client
        )
    assert result == ([{"number": 1, "missing": None}] if rows else [])


@pytest.mark.parametrize("status", [200, 500])
def test_error_excludes_query_contents(status: int) -> None:
    rules = Rules(
        policies=[
            Policy(
                name="test",
                rules=[
                    Rule(
                        hosts=["pgweb.example.test"],
                        credential=Credential(
                            name="test",
                            placeholder="inert-placeholder",
                            targets=[Target(method="METHOD_BASIC_PASSWORD", header="Authorization")],
                        ),
                    )
                ],
            )
        ]
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={"error": "synthetic-sensitive-query-literal"})
            )
        ) as client,
        pytest.raises(QueryError) as error,
    ):
        query(
            "SELECT 'synthetic-sensitive-query-literal'",
            rules=rules,
            base_url="http://pgweb.example.test",
            client=client,
        )
    assert "synthetic-sensitive-query-literal" not in str(error.value)


if __name__ == "__main__":
    pytest_bazel.main()
