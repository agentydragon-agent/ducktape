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
def mock_response():
    """Create a mock response factory."""

    def _create_mock_response(filename: str, status_code: int = 200):
        """Create a mock response from a reference file."""
        example = load_example(filename)

        mock_resp = MagicMock(spec=httpx.Response)
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

    return _create_mock_response


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
    """Tests for the Habitify client."""

    def test_get_habits(self, client, mock_response):
        """Test the get_habits method."""
        # Mock the response
        mock_resp = mock_response("get_habits.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habits = client.get_habits()

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits")

            # Check the returned data
            assert isinstance(habits, list)
            assert all(isinstance(habit, Habit) for habit in habits)
            assert len(habits) > 0

            # Check a specific habit attribute
            assert habits[0].id == "-Lo9NTLRX3aCxg-PjN25"
            assert not habits[0].is_archived

    @pytest.mark.asyncio
    async def test_get_habits_async(self, client, mock_async_response):
        """Test the get_habits_async method."""
        # Mock the response
        mock_resp = mock_async_response("get_habits.yaml")

        # Patch the client's request method
        with patch.object(client.async_client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habits = await client.get_habits_async()

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits")

            # Check the returned data
            assert isinstance(habits, list)
            assert all(isinstance(habit, Habit) for habit in habits)
            assert len(habits) > 0

    def test_get_habit(self, client, mock_response):
        """Test the get_habit method."""
        # Mock the response
        mock_resp = mock_response("get_habit_by_id.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habit = client.get_habit("-Lo9NTLRX3aCxg-PjN25")

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits/-Lo9NTLRX3aCxg-PjN25")

            # Check the returned data
            assert isinstance(habit, Habit)
            assert habit.id == "-Lo9NTLRX3aCxg-PjN25"
            assert not habit.is_archived

    def test_get_habit_not_found(self, client, mock_response):
        """Test the get_habit method with an invalid habit ID."""
        # Mock the error response
        mock_resp = mock_response("get_habit_invalid_id.yaml", status_code=500)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=mock_resp
        )

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method and check for an exception
            with pytest.raises(HabitifyError) as excinfo:
                client.get_habit("invalid-id-that-does-not-exist")

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/habits/invalid-id-that-does-not-exist")

            # Check the error message
            assert "habit does not exist" in str(excinfo.value).lower()

    def test_get_areas(self, client, mock_response):
        """Test the get_areas method."""
        # Mock the response
        mock_resp = mock_response("get_areas.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            areas = client.get_areas()

            # Check that the correct URL was called
            mock_get.assert_called_once_with("/areas")

            # Check the returned data
            assert isinstance(areas, list)
            assert all(isinstance(area, Area) for area in areas)
            assert len(areas) > 0

            # Check a specific area attribute
            assert areas[0].id == "-LrYlUBnzjyceYei_k5Z"
            assert areas[0].name == "H****h"

    def test_get_journal(self, client, mock_response):
        """Test the get_journal method."""
        # Create a test date
        today = datetime.date.today().isoformat()

        # Mock the response
        mock_resp = mock_response("get_journal.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            habits = client.get_journal(date=today)

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

    def test_get_journal_filtered(self, client, mock_response):
        """Test the get_journal method with filters."""
        # Create a test date
        today = datetime.date.today().isoformat()

        # Mock the response
        mock_resp = mock_response("get_journal_filtered.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method with filters
            habits = client.get_journal(date=today, status="none", time_of_day="morning,evening")

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

    def test_check_habit_status(self, client, mock_response):
        """Test the check_habit_status method."""
        # Mock the response
        mock_resp = mock_response("get_habit_status.yaml")

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method
            status = client.check_habit_status("-Lo9NTLRX3aCxg-PjN25", date="2025-05-09")

            # Check that the correct URL was called with parameters
            mock_get.assert_called_once()
            url = mock_get.call_args[0][0]
            params = mock_get.call_args[1]["params"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert "target_date" in params

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "completed"

    def test_check_habit_status_invalid_date(self, client, mock_response):
        """Test the check_habit_status method with an invalid date format."""
        # Mock the error response
        mock_resp = mock_response("get_habit_status_(invalid_date_format).yaml", status_code=500)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=mock_resp
        )

        # Patch the client's request method
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method and check for an exception
            with pytest.raises(HabitifyError) as excinfo:
                client.check_habit_status("-Lo9NTLRX3aCxg-PjN25", date="2020-01-01")

            # Check that the correct URL was called
            mock_get.assert_called_once()

            # Check the error message
            assert "date format" in str(excinfo.value).lower()

    def test_check_habit_status_range(self, client, mock_response):
        """Test the check_habit_status_range method."""
        # Mock the response for status checks
        mock_resp = mock_response("get_habit_status.yaml")

        # Patch the client's get method to always return this response
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method with a date range
            statuses = client.check_habit_status_range(
                "-Lo9NTLRX3aCxg-PjN25", start_date="2025-05-01", end_date="2025-05-03"
            )

            # Should have made 3 calls (for the 3 days in range)
            assert mock_get.call_count == 3

            # Check the returned data
            assert isinstance(statuses, list)
            assert len(statuses) == 3
            assert all(isinstance(status, HabitStatus) for status in statuses)

            # Check that statuses have dates
            assert all(hasattr(status, "date") for status in statuses)
            assert "2025-05-01" in [status.date for status in statuses]
            assert "2025-05-02" in [status.date for status in statuses]
            assert "2025-05-03" in [status.date for status in statuses]

    def test_check_habit_status_range_days(self, client, mock_response):
        """Test the check_habit_status_range method with days parameter."""
        # Mock the response for status checks
        mock_resp = mock_response("get_habit_status.yaml")

        # Patch the client's get method to always return this response
        with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
            # Call the method with days parameter
            statuses = client.check_habit_status_range(
                "-Lo9NTLRX3aCxg-PjN25", start_date="2025-05-01", days=5
            )

            # Should have made 5 calls (for the 5 days in range)
            assert mock_get.call_count == 5

            # Check the returned data
            assert isinstance(statuses, list)
            assert len(statuses) == 5

    def test_check_habit_status_range_error_handling(self, client, mock_response):
        """Test error handling in check_habit_status_range method."""
        # Mock a success response and an error response
        success_resp = mock_response("get_habit_status.yaml")
        error_resp = mock_response("get_habit_status_(invalid_date_format).yaml", status_code=500)
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=error_resp
        )

        # Set up the get method to return success then error
        with patch.object(
            client.client, "get", side_effect=[success_resp, error_resp, success_resp]
        ) as mock_get:
            # Should handle the error and continue with other dates
            statuses = client.check_habit_status_range(
                "-Lo9NTLRX3aCxg-PjN25", start_date="2025-05-01", end_date="2025-05-03"
            )

            # Check call count
            assert mock_get.call_count == 3

            # Check that we got statuses for all dates, with the error day having "none" status
            assert len(statuses) == 3

            # At least one status should be "none" (from the error handling)
            none_statuses = [s for s in statuses if s.status == "none"]
            assert len(none_statuses) > 0

    def test_set_habit_status_completed(self, client, mock_response):
        """Test the set_habit_status method with completed status."""
        # Mock the response
        mock_resp = mock_response("set_habit_status_(completed).yaml")

        # Patch the client's request method
        with patch.object(client.client, "put", return_value=mock_resp) as mock_put:
            # Call the method
            status = client.set_habit_status(
                "-Lo9NTLRX3aCxg-PjN25",
                status="completed",
                date="2025-05-09",
                note="Test completed via unit test",
                value=1.0,
            )

            # Check that the correct URL was called with the right body
            mock_put.assert_called_once()
            url = mock_put.call_args[0][0]
            body = mock_put.call_args[1]["json"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert body["status"] == "completed"
            assert "target_date" in body
            assert body["note"] == "Test completed via unit test"
            assert body["value"] == 1.0

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "completed"
            assert status.note == "Test completed via unit test"
            assert status.value == 1.0

    def test_set_habit_status_skipped(self, client, mock_response):
        """Test the set_habit_status method with skipped status."""
        # Mock the response
        mock_resp = mock_response("set_habit_status_(skipped).yaml")

        # Patch the client's request method
        with patch.object(client.client, "put", return_value=mock_resp) as mock_put:
            # Call the method
            status = client.set_habit_status(
                "-Lo9NTLRX3aCxg-PjN25",
                status="skipped",
                date="2025-05-09",
                note="Test skipped via unit test",
            )

            # Check that the correct URL was called with the right body
            mock_put.assert_called_once()
            url = mock_put.call_args[0][0]
            body = mock_put.call_args[1]["json"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert body["status"] == "skipped"
            assert "target_date" in body
            assert body["note"] == "Test skipped via unit test"
            assert "value" not in body

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "skipped"
            assert status.note == "Test skipped via unit test"
            assert status.value is None

    def test_set_habit_status_no_value(self, client, mock_response):
        """Test the set_habit_status method without a value for habit goals."""
        # Mock the response
        mock_resp = mock_response("set_habit_status_(no_value).yaml")

        # Patch the client's request method
        with patch.object(client.client, "put", return_value=mock_resp) as mock_put:
            # Call the method
            status = client.set_habit_status(
                "-Lo9NTLRX3aCxg-PjN25",
                status="completed",
                date="2025-05-09",
                note="Test completed (no value) via unit test",
            )

            # Check that the correct URL was called with the right body
            mock_put.assert_called_once()
            url = mock_put.call_args[0][0]
            body = mock_put.call_args[1]["json"]

            assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
            assert body["status"] == "completed"
            assert "target_date" in body
            assert body["note"] == "Test completed (no value) via unit test"
            assert "value" not in body

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "completed"
            assert status.note == "Test completed (no value) via unit test"
            assert status.value is None

    @pytest.mark.asyncio
    async def test_set_habit_status_async(self, client, mock_async_response):
        """Test the set_habit_status_async method."""
        # Mock the response
        mock_resp = mock_async_response("set_habit_status_(completed).yaml")

        # Patch the client's request method
        with patch.object(client.async_client, "put", return_value=mock_resp) as mock_put:
            # Call the method
            status = await client.set_habit_status_async(
                "-Lo9NTLRX3aCxg-PjN25",
                status="completed",
                date="2025-05-09",
                note="Test completed via async unit test",
                value=1.0,
            )

            # Check that the correct URL was called
            mock_put.assert_called_once()

            # Check the returned data
            assert isinstance(status, HabitStatus)
            assert status.status == "completed"

    @pytest.mark.asyncio
    async def test_check_habit_status_range_async(self, client, mock_async_response):
        """Test the check_habit_status_range_async method."""
        # Mock the response for all date checks
        mock_resp = mock_async_response("get_habit_status.yaml")

        # Create a custom side_effect function to track which dates were requested
        requested_dates = []
        original_get = client.async_client.get

        async def mock_get_with_date_tracking(url, **kwargs):
            # Record the requested date
            if "target_date" in kwargs.get("params", {}):
                target_date = kwargs["params"]["target_date"]
                requested_dates.append(target_date)
            return mock_resp

        # Patch the client's request method
        with patch.object(
            client.async_client, "get", side_effect=mock_get_with_date_tracking
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
    async def test_check_habit_status_range_async_error_handling(self, client, mock_async_response):
        """Test error handling in check_habit_status_range_async method."""
        # Create success and error responses
        success_resp = mock_async_response("get_habit_status.yaml")
        error_resp = mock_async_response("get_status_invalid_id.yaml", status_code=500)

        # Make the error response raise an exception when raise_for_status is called
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error", request=AsyncMock(), response=error_resp
        )

        # Setup responses for different days - we need to make multiple test date formats
        # since there seems to be variation in how the dates are being processed
        responses = {}
        for day in range(1, 4):
            date_str = f"2025-05-0{day}"
            responses[f"{date_str}T00:00:00+00:00"] = success_resp

        # Explicitly mark the date we want to error
        responses["2025-05-02T00:00:00+00:00"] = error_resp

        # Create a mock implementation that returns different responses
        async def mock_get_implementation(url, **kwargs):
            target_date = kwargs.get("params", {}).get("target_date")
            if target_date in responses:
                return responses[target_date]
            return success_resp  # default

        # Patch the client's request method
        with patch.object(
            client.async_client, "get", side_effect=mock_get_implementation
        ) as mock_get:
            # Call the method with a date range
            statuses = await client.check_habit_status_range_async(
                "-Lo9NTLRX3aCxg-PjN25", start_date="2025-05-01", end_date="2025-05-03"
            )

            # Check that we have 3 status records
            assert len(statuses) == 3

            # At least one status should be "none" from error handling
            none_statuses = [s for s in statuses if s.status == "none"]
            assert len(none_statuses) >= 1

            # Verify that we have statuses for each date
            dates = [s.date for s in statuses]
            assert "2025-05-01" in dates
            assert "2025-05-02" in dates
            assert "2025-05-03" in dates
