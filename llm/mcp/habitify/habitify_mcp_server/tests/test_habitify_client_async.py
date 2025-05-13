"""
Tests for the Habitify API client.

Uses mock data based on the actual API responses seen in the reference YAML files.
"""

import datetime
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import yaml

from ..habitify_client import HabitifyClient, HabitifyError
from ..types import Habit, HabitStatus, Area

# Path to the API reference examples
REFERENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "habitify_api_reference"
)


def load_example(filename: str) -> dict:
    """Load an example response from a YAML file."""
    filepath = os.path.join(REFERENCE_DIR, filename)
    with open(filepath, "r") as f:
        return yaml.safe_load(f)


@pytest.fixture
def client():
    """Create a Habitify client with a mock API key."""
    with patch.dict(os.environ, {"HABITIFY_API_KEY": "test_api_key"}):
        client = HabitifyClient()
        yield client


@pytest.fixture
def mock_async_response():
    """Create a mock async response factory."""

    def _create_mock_async_response(filename: str, status_code: int = 200):
        """Create a mock async response from a reference file."""
        example = load_example(filename)

        mock_resp = AsyncMock(spec=httpx.Response)
        mock_resp.status_code = status_code
        mock_resp.raise_for_status.return_value = None

        # Set response headers
        mock_resp.headers = (
            example["response"]["headers"] if "headers" in example["response"] else {}
        )

        # Set response content
        if "json" in example["response"]:
            mock_resp.json.return_value = example["response"]["json"]
        elif "text" in example["response"]:
            mock_resp.text = example["response"]["text"]
            mock_resp.json.side_effect = json.JSONDecodeError("", "", 0)

        return mock_resp

    return _create_mock_async_response


class TestHabitifyClient:
    """Tests for the Habitify client using async methods only."""

    @pytest.mark.asyncio
    async def test_get_habits_async(self, client, mock_async_response):
        """Test the get_habits_async method."""
        # Mock the response
        mock_resp = mock_async_response("get_habits.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habits = await client.get_habits_async()

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits")

            # Check the returned data
            assert isinstance(habits, list)
            assert all(isinstance(habit, Habit) for habit in habits)
            assert len(habits) > 0

            # Check a specific habit attribute
            assert habits[0].id == "-Lo9NTLRX3aCxg-PjN25"
            assert not habits[0].archived

    @pytest.mark.asyncio
    async def test_get_habit_async(self, client, mock_async_response):
        """Test the get_habit_async method."""
        # Mock the response
        mock_resp = mock_async_response("get_habit_by_id.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habit = await client.get_habit_async("-Lo9NTLRX3aCxg-PjN25")

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits/-Lo9NTLRX3aCxg-PjN25")

            # Check the returned data
            assert isinstance(habit, Habit)
            assert habit.id == "-Lo9NTLRX3aCxg-PjN25"
            assert not habit.archived

    @pytest.mark.asyncio
    async def test_get_habit_not_found_async(self, client, mock_async_response):
        """Test the get_habit_async method with an invalid habit ID."""
        # Mock the error response
        mock_resp = mock_async_response("get_habit_invalid_id.yaml", status_code=500)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=mock_resp
        )

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method and check for an exception
            with pytest.raises(HabitifyError) as excinfo:
                await client.get_habit_async("invalid-id-that-does-not-exist")

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits/invalid-id-that-does-not-exist")

            # Check the error message
            assert "habit does not exist" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_get_areas_async(self, client, mock_async_response):
        """Test the get_areas_async method."""
        # Mock the response
        mock_resp = mock_async_response("get_areas.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            areas = await client.get_areas_async()

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/areas")

            # Check the returned data
            assert isinstance(areas, list)
            assert all(isinstance(area, Area) for area in areas)
            assert len(areas) > 0

            # Check a specific area attribute
            assert areas[0].id == "-LrYlUBnzjyceYei_k5Z"
            assert areas[0].name == "H****h"

    @pytest.mark.asyncio
    async def test_get_journal_async(self, client, mock_async_response):
        """Test the get_journal_async method."""
        # Create a test date
        today = datetime.date.today().isoformat()

        # Mock the response
        mock_resp = mock_async_response("get_journal.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habits = await client.get_journal_async(date=today)

            # Check that the correct URL was called with parameters
            mock_get.assert_called_once()
            url = mock_get.call_args[0][0]
            params = mock_get.call_args[1]["params"]

            assert url == "/journal"
            assert "target_date" in params
            assert params["order_by"] == "priority"

            # Check the returned data
            assert isinstance(habits, list)
            assert all(isinstance(habit, Habit) for habit in habits)

    @pytest.mark.asyncio
    async def test_get_journal_filtered_async(self, client, mock_async_response):
        """Test the get_journal_async method with filters."""
        # Create a test date
        today = datetime.date.today().isoformat()

        # Mock the response
        mock_resp = mock_async_response("get_journal_filtered.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method with filters
            habits = await client.get_journal_async(date=today, status="none", time_of_day="morning,evening")

            # Check that the correct URL was called with parameters
            mock_get.assert_called_once()
            url = mock_get.call_args[0][0]
            params = mock_get.call_args[1]["params"]

            assert url == "/journal"
            assert "target_date" in params
            assert params["status"] == "none"
            assert params["time_of_day"] == "morning,evening"

            # Check the returned data
            assert isinstance(habits, list)

    @pytest.mark.asyncio
    async def test_check_habit_status_async(self, client, mock_async_response):
        """Test the check_habit_status_async method."""
        # Mock the response
        mock_resp = mock_async_response("get_habit_status.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            status = await client.check_habit_status_async("-Lo9NTLRX3aCxg-PjN25", date="2025-05-09")

            # Check that the correct URL was called with parameters
            mock_get.assert_called_once()
            url = mock_get.call_args[0][0]
            params = mock_get.call_args[1]["params"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert "target_date" in params

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "completed"

    @pytest.mark.asyncio
    async def test_check_habit_status_invalid_date_async(self, client, mock_async_response):
        """Test the check_habit_status_async method with an invalid date format."""
        # Mock the error response
        mock_resp = mock_async_response("get_habit_status_(invalid_date_format).yaml", status_code=500)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=mock_resp
        )

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method and check for an exception
            with pytest.raises(HabitifyError) as excinfo:
                await client.check_habit_status_async("-Lo9NTLRX3aCxg-PjN25", date="2020-01-01")

            # Check that the correct URL was called
            mock_get.assert_called_once()

            # Check the error message
            assert "date format" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_check_habit_status_range_async(self, client, mock_async_response):
        """Test the check_habit_status_range_async method."""
        # Mock the response for all date checks
        mock_resp = mock_async_response("get_habit_status.yaml")

        # Create a custom side_effect function to track which dates were requested
        requested_dates = []
        original_get = client.client.get

        async def mock_get_with_date_tracking(url, **kwargs):
            # Record the requested date
            if "target_date" in kwargs.get("params", {}):
                target_date = kwargs["params"]["target_date"]
                requested_dates.append(target_date)
            return mock_resp

        # Patch the client's request method
        with patch.object(
            client.client, "get", side_effect=mock_get_with_date_tracking
        ) as mock_get:
            # Call the method with a date range
            statuses = await client.check_habit_status_range_async(
                "-Lo9NTLRX3aCxg-PjN25", start_date="2025-05-01", end_date="2025-05-05"
            )

            # Check the total number of calls
            assert mock_get.call_count == 5

            # Check the returned data
            assert isinstance(statuses, list)
            assert len(statuses) == 5
            assert all(isinstance(status, HabitStatus) for status in statuses)

            # Check that dates are sorted in chronological order
            dates = [status.date for status in statuses]
            assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_set_habit_status_async(self, client, mock_async_response):
        """Test the set_habit_status_async method."""
        # Mock the response
        mock_resp = mock_async_response("set_habit_status_(completed).yaml")

        # Patch the client's request method
        with patch.object(client.client, "put", return_value=mock_resp) as mock_put:
            # Call the method
            status = await client.set_habit_status_async(
                "-Lo9NTLRX3aCxg-PjN25",
                status="completed",
                date="2025-05-09",
                note="Test completed via async unit test",
                value=1.0,
            )

            # Check that the correct URL was called with the right body
            mock_put.assert_called_once()
            url = mock_put.call_args[0][0]
            body = mock_put.call_args[1]["json"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert body["status"] == "completed"
            assert "target_date" in body
            assert body["note"] == "Test completed via async unit test"
            assert body["value"] == 1.0

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "completed"
            assert status.note == "Test completed via async unit test"
            assert status.value == 1.0

    @pytest.mark.asyncio
    async def test_set_habit_status_skipped_async(self, client, mock_async_response):
        """Test the set_habit_status_async method with skipped status."""
        # Mock the response
        mock_resp = mock_async_response("set_habit_status_(skipped).yaml")

        # Patch the client's request method
        with patch.object(client.client, "put", return_value=mock_resp) as mock_put:
            # Call the method
            status = await client.set_habit_status_async(
                "-Lo9NTLRX3aCxg-PjN25",
                status="skipped",
                date="2025-05-09",
                note="Test skipped via async unit test",
            )

            # Check that the correct URL was called with the right body
            mock_put.assert_called_once()
            url = mock_put.call_args[0][0]
            body = mock_put.call_args[1]["json"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert body["status"] == "skipped"
            assert "target_date" in body
            assert body["note"] == "Test skipped via async unit test"
            assert "value" not in body

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "skipped"
            assert status.note == "Test skipped via async unit test"
            assert status.value is None