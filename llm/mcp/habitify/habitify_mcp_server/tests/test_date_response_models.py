"""
Test the separation between API response models and client response models.

This test ensures that the HabitifyClient returns client response models (HabitStatusResponse)
with Python date objects, while keeping API response models (HabitStatus) with string dates.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ..habitify_client import HabitifyClient
from ..types import HabitStatus, HabitStatusResponse


@pytest.fixture
def client():
    """Create a Habitify client with a mock API key."""
    with patch.dict("os.environ", {"HABITIFY_API_KEY": "test_api_key"}):
        client = HabitifyClient()
        yield client


@pytest.mark.asyncio
async def test_check_habit_status_returns_client_response_with_date_object(client):
    """Test that check_habit_status returns HabitStatusResponse with a date object."""
    # Create a mock response
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": {
            "status": "completed"
        }
    }

    # Patch the client's request method
    with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
        # Call the method with a string date
        status = await client.check_habit_status("test-habit-id", "2025-01-15")

        # Verify we get a HabitStatusResponse (not a HabitStatus)
        assert isinstance(status, HabitStatusResponse)
        assert not isinstance(status, HabitStatus)
        
        # Verify the date is a Python date object, not a string
        assert isinstance(status.date, datetime.date)
        assert status.date.year == 2025
        assert status.date.month == 1
        assert status.date.day == 15


@pytest.mark.asyncio
async def test_set_habit_status_returns_client_response_with_date_object(client):
    """Test that set_habit_status returns HabitStatusResponse with a date object."""
    # Create a mock response
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "status": True
    }

    # Patch the client's request method
    with patch.object(client.client, "put", return_value=mock_resp) as mock_put:
        # Call the method with a string date
        status = await client.set_habit_status(
            "test-habit-id", 
            "completed", 
            "2025-02-15",
            "Test note"
        )

        # Verify we get a HabitStatusResponse (not a HabitStatus)
        assert isinstance(status, HabitStatusResponse)
        assert not isinstance(status, HabitStatus)
        
        # Verify the date is a Python date object, not a string
        assert isinstance(status.date, datetime.date)
        assert status.date.year == 2025
        assert status.date.month == 2
        assert status.date.day == 15


@pytest.mark.asyncio
async def test_check_habit_status_range_returns_client_responses(client):
    """Test that check_habit_status_range returns list of HabitStatusResponse with date objects."""
    # Create a mock response for all date checks
    mock_resp = AsyncMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": {
            "status": "completed"
        }
    }

    # Patch the client's request method to return our mock response
    with patch.object(client.client, "get", return_value=mock_resp) as mock_get:
        # Call the method with a date range (3 days)
        statuses = await client.check_habit_status_range(
            "test-habit-id",
            start_date="2025-03-15",
            days=3
        )

        # Should have made 3 calls for 3 days
        assert mock_get.call_count == 3
        
        # Should return 3 status objects
        assert len(statuses) == 3
        
        # All should be HabitStatusResponse with date objects
        for status in statuses:
            assert isinstance(status, HabitStatusResponse)
            assert not isinstance(status, HabitStatus)
            assert isinstance(status.date, datetime.date)
            assert status.date.year == 2025
            assert status.date.month == 3
            assert status.date.day >= 15
            assert status.date.day < 18  # 15, 16, 17