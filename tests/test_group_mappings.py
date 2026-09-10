"""Unit tests for jml.group_mappings — role-to-group resolution."""

import pytest
from jml.group_mappings import RoleKey, ROLE_TO_GROUPS, resolve_groups


class TestRoleKey:
    """RoleKey is a frozen dataclass used as a dictionary key."""

    def test_frozen_equality(self):
        """Frozen dataclasses with same values must be equal and hashable."""
        a = RoleKey("Engineering", "Software Engineer", "Any")
        b = RoleKey("Engineering", "Software Engineer", "Any")
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality(self):
        """Different roles must not collide."""
        a = RoleKey("Engineering", "Software Engineer", "Any")
        b = RoleKey("Engineering", "Engineering Manager", "Any")
        assert a != b


class TestResolveGroups:
    """resolve_groups must return the correct set of group names."""

    def test_engineering_swe(self):
        """A standard SWE should get the core engineering groups."""
        groups = resolve_groups("Engineering", "Software Engineer")
        assert "All-Employees" in groups
        assert "Engineering" in groups
        assert "GitHub-Users" in groups
        assert "AWS-Dev-Access" in groups
        assert "Manager-Tools" not in groups

    def test_engineering_manager(self):
        """A manager should get Manager-Tools but not IC-specific groups."""
        groups = resolve_groups("Engineering", "Engineering Manager")
        assert "Manager-Tools" in groups
        assert "Engineering-Managers" in groups
        assert "Bonusly-Admins" in groups

    def test_intern(self):
        """An intern should get the Interns-2026 group but not prod access."""
        groups = resolve_groups("Engineering", "Intern")
        assert "Interns-2026" in groups
        assert "AWS-Prod-Access" not in groups

    def test_unknown_role_returns_empty(self):
        """An undefined role should return an empty set, not crash."""
        groups = resolve_groups("Unknown", "Wizard")
        assert groups == set()

    def test_location_fallback(self):
        """A specific location not in the map should fall back to 'Any'."""
        groups_specific = resolve_groups("Engineering", "Software Engineer", "Remote")
        groups_any = resolve_groups("Engineering", "Software Engineer", "Any")
        assert groups_specific == groups_any

    def test_return_type_is_set(self):
        """The return must be a set for downstream set arithmetic."""
        groups = resolve_groups("Sales", "Account Executive")
        assert isinstance(groups, set)