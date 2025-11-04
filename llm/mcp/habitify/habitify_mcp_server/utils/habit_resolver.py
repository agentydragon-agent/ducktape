"""
Utility to resolve a habit by name or ID.
"""

from ..habitify_client import HabitifyClient, HabitifyError
from ..types import ErrorResponse, ResolvedHabit
from .error_utils import create_error_response, create_validation_error


async def resolve_habit(
    client: HabitifyClient, id: str | None = None, name: str | None = None
) -> ResolvedHabit | ErrorResponse:
    """
    Utility to resolve a habit by name or ID.

    Args:
        client: HabitifyClient instance to use for API requests
        id: ID of the habit to resolve
        name: Name of the habit to resolve

    Returns:
        Either a ResolvedHabit with the habit_id and habit_name, or an ErrorResponse
    """
    try:
        # Check if we have a direct ID
        if id:
            if isinstance(id, str):
                return ResolvedHabit(habit_id=id if id.startswith("-") else f"-{id}")
            return create_validation_error("Habit ID must be a string.")

        # If no name provided, return error
        if not name:
            return create_validation_error("Either id or name must be provided.")

        try:
            habits = await client.get_habits()

            # Find matching habits (case-insensitive)
            habit_name = name.lower().strip()
            matching_habits = [h for h in habits if habit_name in h.name.lower()]

            if not matching_habits:
                return create_validation_error(f'No habit found with name containing "{name}"')

            if len(matching_habits) > 1:
                # If there's an exact match, use it
                exact_match = next(
                    (h for h in matching_habits if h.name.lower() == habit_name), None
                )

                if exact_match:
                    return ResolvedHabit(
                        habit_id=exact_match.id,
                        habit_name=exact_match.name,
                        match_type="exact",
                    )

                # Otherwise return ambiguous match error
                matches = [{"id": h.id, "name": h.name} for h in matching_habits[:5]]
                return create_validation_error(
                    f'Multiple habits found matching "{name}"',
                    {"matches": matches, "total_matches": len(matching_habits)},
                )

            # If exactly one habit matches, return its ID
            return ResolvedHabit(
                habit_id=matching_habits[0].id,
                habit_name=matching_habits[0].name,
                match_type=(
                    "exact" if matching_habits[0].name.lower() == habit_name else "partial"
                ),
            )
        except HabitifyError as e:
            return create_error_response(e)
    except Exception as e:
        return create_error_response(e)
