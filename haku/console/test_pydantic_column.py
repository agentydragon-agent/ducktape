"""Tests for haku-console's typed JSONB column."""

import pytest_bazel
from pydantic import BaseModel, ConfigDict

from haku.console.pydantic_column import PydanticColumn


class AliasedPayload(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda name: name.replace("snake_case", "camelCase"), populate_by_name=True
    )

    snake_case: str


def test_pydantic_column_handles_containers_and_aliases() -> None:
    column: PydanticColumn[list[AliasedPayload]] = PydanticColumn(list[AliasedPayload])
    payload = [AliasedPayload(snake_case="value")]

    stored = column.process_bind_param(payload, None)

    assert stored == [{"camelCase": "value"}]
    assert column.process_result_value(stored, None) == payload


if __name__ == "__main__":
    pytest_bazel.main()
