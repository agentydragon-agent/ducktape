"""Habitify MCP tools implementation."""

from datetime import datetime
from typing import Literal, cast

from .habitify_client import HabitifyClient
from .types import (
    DateRangeStatusItem,
    DateRangeStatusResult,
    ErrorResponse,
    HabitResult,
    HabitsResult,
    LogResult,
    ResultType,
    Status,
    StatusResult,
)
from .utils.error_utils import create_error_response, create_validation_error
from .utils.habit_resolver import resolve_habit


def validate_habit_identifier(*, id: str | None, name: str | None, action: str = "use") -> ErrorResponse | None:
    """Validate that either an ID or name is provided to identify a habit."""
    if not id and not name:
        return create_validation_error(f"Either a habit ID or habit name is required to {action} a habit.")
    return None


async def _validate_and_resolve(
    client: HabitifyClient, *, id: str | None = None, name: str | None = None, action: str = "use"
) -> HabitResult | ErrorResponse:
    """Validate habit identifier and resolve habit or return ErrorResponse."""
    validation_error = validate_habit_identifier(id=id, name=name, action=action)
    if validation_error:
        return validation_error
    return await resolve_habit(client, id=id, name=name)


async def get_habits(client: HabitifyClient, *, include_archived: bool = False) -> ResultType:
    """Get all habits."""
    habits = await client.get_habits()
    if not include_archived:
        habits = [habit for habit in habits if not habit.archived]
    return HabitsResult(habits=habits, count=len(habits))


async def get_habit(client: HabitifyClient, *, id: str | None = None, name: str | None = None) -> ResultType:
    """Get a specific habit by ID or name."""
    validation_error = validate_habit_identifier(id=id, name=name, action="get")
    if validation_error:
        return validation_error

    if id:
        try:
            habit = await client.get_habit(id)
            return HabitResult(habit=habit)
        except Exception as e:
            return create_error_response(e)

    if name:
        habits = await client.get_habits()
        habit_name = name.lower().strip()
        matching_habits = [h for h in habits if habit_name in h.name.lower()]

        if not matching_habits:
            return create_validation_error(f'No habit found with name containing "{name}"')

        exact_match = next((h for h in matching_habits if h.name.lower() == habit_name), None)
        if exact_match:
            return HabitResult(habit=exact_match, match_type="exact")

        if len(matching_habits) == 1:
            return HabitResult(habit=matching_habits[0], match_type="partial")

        return create_validation_error(
            f'Multiple habits found matching "{name}"',
            {
                "matches": [{"id": h.id, "name": h.name} for h in matching_habits[:5]],
                "total_matches": len(matching_habits),
            },
        )

    return create_validation_error("Either a habit ID or habit name is required")


async def get_habit_status(
    client: HabitifyClient,
    *,
    id: str | None = None,
    name: str | None = None,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int | None = None,
) -> ResultType:
    """
    Get a habit's status for one or more dates.

    Single date: use 'date' parameter.
    Date range (inclusive): use start_date/end_date, start_date/days, end_date/days, or just days.
    """
    resolved = await _validate_and_resolve(client, id=id, name=name, action="check")
    if isinstance(resolved, ErrorResponse):
        return resolved

    is_range_query = any((start_date, end_date, days))

    if date and is_range_query:
        return create_validation_error(
            "Cannot specify both date and date range parameters (start_date, end_date, days) simultaneously."
        )

    if is_range_query:
        statuses = await client.check_habit_status_range(
            resolved.habit_id, start_date=start_date, end_date=end_date, days=days
        )

        items = []
        first_date = None
        last_date = None

        for status in statuses:
            items.append(DateRangeStatusItem(date=status.date, status=status.status))
            if first_date is None or status.date < first_date:
                first_date = status.date
            if last_date is None or status.date > last_date:
                last_date = status.date

        return DateRangeStatusResult(
            statuses=items,
            start_date=first_date or datetime.now().strftime("%Y-%m-%d"),
            end_date=last_date or datetime.now().strftime("%Y-%m-%d"),
            date_count=len(items),
        )

    date_str = date or datetime.now().strftime("%Y-%m-%d")
    status = await client.check_habit_status(resolved.habit_id, date_str)
    return StatusResult(status=status.status, date=date_str)


async def set_habit_status(
    client: HabitifyClient,
    *,
    id: str | None = None,
    name: str | None = None,
    status: Status = Status.COMPLETED,
    date: str | None = None,
    note: str | None = None,
    value: float | None = None,
) -> ResultType:
    """Set a habit's status for a specific date."""
    resolved = await _validate_and_resolve(client, id=id, name=name, action="set")
    if isinstance(resolved, ErrorResponse):
        return resolved

    result = await client.set_habit_status(
        resolved.habit_id, cast(Literal["completed", "skipped", "failed", "none"], status.value), date, note, value
    )
    return LogResult(status=result.status, date=result.date, note=result.note, value=result.value)
