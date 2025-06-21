"""
Habitify MCP tools implementation.
"""

from datetime import datetime
from typing import Literal, Optional, cast

from .habitify_client import HabitifyClient
from .types import (
    DateRangeStatusItem,
    DateRangeStatusResult,
    ErrorResponse,
    HabitResult,
    HabitsResult,
    LogResult,
    ResultType,
    StatusResult,
)
from .utils import with_client
from .utils.date_utils import format_date_human, format_date_yyyy_mm_dd
from .utils.error_utils import create_error_response, create_validation_error
from .utils.habit_resolver import resolve_habit


def validate_habit_identifier(**kwargs) -> Optional[ErrorResponse]:
    """
    Validate that either an ID or name is provided to identify a habit.

    Returns:
        ErrorResponse if validation fails, or None if validation passes
    """
    id_param = kwargs.get("id")
    name_param = kwargs.get("name")

    if not id_param and not name_param:
        action = kwargs.get("action", "use")
        return create_validation_error(
            f"Either a habit ID or habit name is required to {action} a habit."
        )

    return None


@with_client
async def get_habits(client: HabitifyClient, include_archived: bool = False) -> ResultType:
    """
    MCP tool to get all habits.

    Args:
        client: HabitifyClient instance (injected by decorator)
        include_archived: Whether to include archived habits (default: False)

    Returns:
        Dict with habits or error information
    """
    habits = await client.get_habits()

    # Filter out archived habits if include_archived is False
    if not include_archived:
        habits = [habit for habit in habits if not habit.archived]

    # Return habits with count, using Pydantic model
    return HabitsResult(habits=habits, count=len(habits))


@with_client
async def get_habit(
    client: HabitifyClient, id: Optional[str] = None, name: Optional[str] = None
) -> ResultType:
    """
    Get a specific habit by ID or name.

    Args:
        client: HabitifyClient instance (injected by decorator)
        id: ID of the habit to retrieve
        name: Name or partial name of the habit to find

    Returns:
        Dict with habit details or error information
    """
    # Validate required arguments
    validation_error = validate_habit_identifier(id=id, name=name, action="get")
    if validation_error:
        return validation_error

    # If ID is provided, use direct lookup
    if id:
        try:
            habit = await client.get_habit(id)
            return HabitResult(habit=habit)
        except Exception as e:
            return create_error_response(e)

    # If name is provided, do a name-based lookup with detailed feedback
    if name:
        habits = await client.get_habits()

        # Find matching habits (case-insensitive)
        habit_name = name.lower().strip()
        matching_habits = [h for h in habits if habit_name in h.name.lower()]

        if not matching_habits:
            return create_validation_error(f'No habit found with name containing "{name}"')

        # Find exact match if available
        exact_match = next((h for h in matching_habits if h.name.lower() == habit_name), None)

        if exact_match:
            return HabitResult(habit=exact_match, match_type="exact")

        # If only one match, return it
        if len(matching_habits) == 1:
            return HabitResult(habit=matching_habits[0], match_type="partial")

        # Multiple matches, provide them as context
        return create_validation_error(
            f'Multiple habits found matching "{name}"',
            {
                "matches": [{"id": h.id, "name": h.name} for h in matching_habits[:5]],
                "total_matches": len(matching_habits),
            },
        )


@with_client
async def get_habit_status(
    client: HabitifyClient,
    id: Optional[str] = None,
    name: Optional[str] = None,
    date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    days: Optional[int] = None,
) -> ResultType:
    """
    MCP tool to get a habit's status for one or more dates.

    This function supports both single date and date range queries.
    For a single date, use the 'date' parameter.
    For a date range, use:
    - start_date and end_date for a specific range (inclusive)
    - start_date and days for N days from start date
    - end_date and days for N days before end date
    - just days for N days up to today

    All dates are inclusive (both start and end dates are included in results).

    Args:
        client: HabitifyClient instance (injected by decorator)
        id: ID of the habit to check
        name: Name of the habit to check (alternative to id)
        date: Single date to check in YYYY-MM-DD format (defaults to today if no range specified)
        start_date: Start date for range in YYYY-MM-DD format (inclusive)
        end_date: End date for range in YYYY-MM-DD format (inclusive)
        days: Number of days to include in range

    Returns:
        Dict with habit status or error information
    """
    # Validate required arguments
    validation_error = validate_habit_identifier(id=id, name=name, action="check")
    if validation_error:
        return validation_error

    # Check if we're doing a date range query or a single date query
    is_range_query = any([start_date, end_date, days])

    # If both date and range parameters are provided, return an error
    if date and is_range_query:
        return create_validation_error(
            "Cannot specify both date and date range parameters (start_date, end_date, days) simultaneously."
        )

    # Resolve the habit (either by ID or name)
    resolved = await resolve_habit(client, id=id, name=name)

    if isinstance(resolved, ErrorResponse):
        return resolved

    # If it's a range query
    if is_range_query:
        statuses = await client.check_habit_status_range(
            resolved.habit_id, start_date=start_date, end_date=end_date, days=days
        )

        # Convert to normalized format
        items = []

        # Track the actual date range
        first_date = None
        last_date = None

        # Process each status
        for status in statuses:
            date_str = format_date_yyyy_mm_dd(status.date)
            formatted_date = format_date_human(date_str)
            is_completed = status.status == "completed"

            # Build the status item
            items.append(
                DateRangeStatusItem(
                    date=date_str,
                    formatted_date=formatted_date,
                    status=status.status,
                    completed=is_completed,
                )
            )

            # Track date range
            if first_date is None or date_str < first_date:
                first_date = date_str
            if last_date is None or date_str > last_date:
                last_date = date_str

        # Create the date range result
        return DateRangeStatusResult(
            statuses=items,
            start_date=first_date or format_date_yyyy_mm_dd(None),
            end_date=last_date or format_date_yyyy_mm_dd(None),
            date_count=len(items),
        )
    else:
        # Single date query (original behavior)
        # Parse date if provided or default to today
        date_str = date or datetime.now().strftime("%Y-%m-%d")

        status = await client.check_habit_status(resolved.habit_id, date_str)

        # Format the status value for easier use by LLMs
        readable_date = format_date_human(date_str)

        # Status is now a Pydantic model, use attribute access
        return StatusResult(
            status=status.status,
            date=date_str,
            formatted_date=readable_date,
            completed=status.status == "completed",
        )


# log_habit function removed - redundant with set_habit_status


@with_client
async def set_habit_status(
    client: HabitifyClient,
    id: Optional[str] = None,
    name: Optional[str] = None,
    status: str = "completed",
    date: Optional[str] = None,
    note: Optional[str] = None,
    value: Optional[float] = None,
) -> ResultType:
    """
    Set a habit's status for a specific date.

    Args:
        client: HabitifyClient instance (injected by decorator)
        id: ID of the habit to update
        name: Name of the habit to update (alternative to id)
        status: Status to set: completed, skipped, failed, or none
        date: Date in YYYY-MM-DD format (defaults to today)
        note: Optional note to attach to the log
        value: Optional value for habits with numeric goals

    Returns:
        Dict with status update result or error information
    """
    # Validate required arguments
    validation_error = validate_habit_identifier(id=id, name=name, action="set")
    if validation_error:
        return validation_error

    if not status:
        return create_validation_error("Status is required to set a habit status.")

    # Validate status value
    valid_statuses = ["completed", "skipped", "failed", "none"]
    if status not in valid_statuses:
        return create_validation_error(
            f"Invalid status value: {status}. Status must be one of: {', '.join(valid_statuses)}"
        )

    # Resolve the habit (either by ID or name)
    resolved = await resolve_habit(client, id=id, name=name)

    # With Pydantic, we can properly use isinstance
    if isinstance(resolved, ErrorResponse):
        return resolved

    result = await client.set_habit_status(
        resolved.habit_id,
        cast(Literal["completed", "skipped", "failed", "none"], status),
        date,
        note,
        value,
    )

    # Format the response for easier use by LLMs
    date_str = format_date_human(date) if date else format_date_human(datetime.now())

    # Pydantic handles optional fields
    return LogResult(
        status=result.status,
        date=result.date,
        formatted_date=date_str,
        note=result.note,
        value=result.value,
    )
