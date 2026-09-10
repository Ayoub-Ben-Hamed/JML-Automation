"""Unit tests for jml.group_manager — mocked Okta API calls."""

import pytest
from unittest.mock import MagicMock, patch
from jml.group_manager import GroupManager


@pytest.fixture
def mock_session():
    with patch("jml.group_manager.requests.Session") as mock_cls:
        session = MagicMock()
        mock_cls.return_value = session
        yield session


@pytest.fixture
def manager(mock_session):
    return GroupManager(domain="dev-123456.okta.com", api_token="fake-token")


class TestFindGroupByName:

    def test_find_existing_group(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": "00gFOUND",
                "profile": {"name": "Engineering", "description": "Eng team"},
                "type": "OKTA_GROUP",
            }
        ]
        mock_session.get.return_value = mock_resp

        group = manager.find_group_by_name("Engineering")
        assert group["id"] == "00gFOUND"
        assert group["profile"]["name"] == "Engineering"

    def test_find_no_match(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "00gOTHER", "profile": {"name": "Engineering-Managers"}}
        ]
        mock_session.get.return_value = mock_resp

        group = manager.find_group_by_name("Engineering")
        assert group is None

    def test_find_api_error(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = Exception("Internal Server Error")
        mock_session.get.return_value = mock_resp

        with pytest.raises(Exception, match="Internal Server Error"):
            manager.find_group_by_name("Engineering")


class TestCreateGroup:

    def test_create_success(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "00gNEWGROUP",
            "profile": {"name": "Test-Group", "description": "A test group"},
        }
        mock_session.post.return_value = mock_resp

        group = manager.create_group("Test-Group", "A test group")
        assert group["id"] == "00gNEWGROUP"

        call_args = mock_session.post.call_args
        payload = call_args[1]["json"]
        assert payload["profile"]["name"] == "Test-Group"


class TestGetOrCreateGroup:

    def test_returns_existing(self, manager, mock_session):
        existing = {
            "id": "00gEXIST",
            "profile": {"name": "Already-There"},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [existing]
        mock_session.get.return_value = mock_resp

        group = manager.get_or_create_group("Already-There")
        assert group["id"] == "00gEXIST"
        assert mock_session.get.call_count == 1
        assert mock_session.post.call_count == 0

    def test_creates_when_missing(self, manager, mock_session):
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = []

        create_resp = MagicMock()
        create_resp.status_code = 200
        create_resp.json.return_value = {
            "id": "00gCREATED",
            "profile": {"name": "New-Group"},
        }

        mock_session.get.return_value = search_resp
        mock_session.post.return_value = create_resp

        group = manager.get_or_create_group("New-Group")
        assert group["id"] == "00gCREATED"
        assert mock_session.get.call_count == 1
        assert mock_session.post.call_count == 1


class TestAddUserToGroup:

    def test_add_success_204(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_session.put.return_value = mock_resp

        manager.add_user_to_group("00uUSER", "00gGROUP")
        mock_session.put.assert_called_once()

    def test_add_success_200(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_session.put.return_value = mock_resp

        manager.add_user_to_group("00uUSER", "00gGROUP")  # should not raise

    def test_add_failure_404(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = Exception("Not Found")
        mock_session.put.return_value = mock_resp

        with pytest.raises(Exception):
            manager.add_user_to_group("00uUSER", "00gBADGROUP")


class TestRemoveUserFromGroup:

    def test_remove_success(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_session.delete.return_value = mock_resp

        # Use the real method name that exists in your class
        manager.delete_user_from_group("00uUSER", "00gGROUP")
        mock_session.delete.assert_called_once()

    def test_remove_failure_raises(self, manager, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = Exception("Forbidden")
        mock_session.delete.return_value = mock_resp

        with pytest.raises(Exception):
            manager.delete_user_from_group("00uUSER", "00gGROUP")