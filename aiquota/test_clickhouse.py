import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_bazel

from aiquota.api import BackgroundCollector, CollectorMetrics, QuotaSnapshot, RawUpstreamResponse
from aiquota.clickhouse import ClickHouseSnapshotSink
from aiquota.models import AllQuotas, FetchSuccess, ProviderFetch, ProviderQuota, QuotaWindow

if __name__ == "__main__":
    pytest_bazel.main()

pytestmark = pytest.mark.asyncio


def _snapshot() -> QuotaSnapshot:
    observed_at = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    raw_bytes = b'{"five_hour":{"utilization":45.0}}\n'
    return QuotaSnapshot(
        quotas=AllQuotas(
            fetched_at=observed_at,
            providers=[
                ProviderQuota(
                    provider="claude",
                    last_output=ProviderFetch(
                        fetched_at=observed_at,
                        result=FetchSuccess(
                            windows=[
                                QuotaWindow(
                                    used_percent=45.0,
                                    reset_seconds=3600,
                                    window_seconds=5 * 3600,
                                    reset_at=observed_at + timedelta(hours=1),
                                )
                            ]
                        ),
                    ),
                )
            ],
        ),
        raw_responses={
            "claude": RawUpstreamResponse(
                status_code=200,
                content_type="application/json",
                body={"five_hour": {"utilization": 45.0}},
                body_base64=base64.b64encode(raw_bytes).decode(),
                body_sha256="82c2c21a2c01aff1604fa70e5efc172054c0aafa9f53c9387c20dc133789ae09",
                body_size_bytes=len(raw_bytes),
            )
        },
    )


async def test_clickhouse_sink_batches_raw_and_typed_rows() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    sink = ClickHouseSnapshotSink(
        url="http://clickhouse:8123",
        username="aiquota_ingest",
        password="secret",
        transport=httpx.MockTransport(handler),
    )

    assert await sink.write(_snapshot()) == 2
    assert len(requests) == 1
    raw_query = requests[0].url.params["query"]
    assert raw_query == "INSERT INTO aiquota.raw_http_observations FORMAT JSONEachRow"
    assert requests[0].url.params["async_insert_deduplicate"] == "1"
    assert requests[0].url.params["insert_deduplication_token"]
    raw_row = json.loads(requests[0].content)
    assert base64.b64decode(raw_row["raw_body_base64"]) == b'{"five_hour":{"utilization":45.0}}\n'
    assert raw_row["raw_body_size_bytes"] == 35
    assert raw_row["normalized_body"]
    assert raw_row["quota_windows"] == [
        ["", 45.0, 55.0, "2026-08-22T02:00:00+00:00", 3600, 18000, None, None, None, None]
    ]


async def test_background_collector_forces_refresh_and_records_success() -> None:
    class Fetcher:
        force_refresh: bool | None = None

        async def fetch(self, force_refresh: bool = False) -> QuotaSnapshot:
            self.force_refresh = force_refresh
            return _snapshot()

    class Sink:
        snapshot: QuotaSnapshot | None = None

        async def write(self, snapshot: QuotaSnapshot) -> int:
            self.snapshot = snapshot
            return 2

    fetcher = Fetcher()
    sink = Sink()
    metrics = CollectorMetrics()
    collector = BackgroundCollector(fetcher, sink, interval=timedelta(minutes=5), metrics=metrics)

    await collector.poll_once()

    assert fetcher.force_refresh is True
    assert sink.snapshot is not None
    assert collector.has_persisted is True
    rendered = metrics.registry.collect()
    assert any(metric.name == "aiquota_collector_ready" for metric in rendered)
