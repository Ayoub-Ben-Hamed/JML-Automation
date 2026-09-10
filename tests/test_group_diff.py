"""Unit tests for jml.group_diff — set arithmetic for MOVE events."""

from jml.group_diff import diff_groups


class TestDiffGroups:
    """diff_groups must produce correct add/remove/preserve sets."""

    def test_promotion_adds_and_preserves(self):
        """Moving SWE → Senior SWE should add Senior-IC-Perks and keep shared groups."""
        old = {"All-Employees", "Engineering", "GitHub-Users", "AWS-Dev-Access"}
        new = {"All-Employees", "Engineering", "GitHub-Users", "AWS-Dev-Access", "Senior-IC-Perks"}

        to_remove, to_add, preserved = diff_groups(old, new)

        assert to_remove == set()
        assert to_add == {"Senior-IC-Perks"}
        assert preserved == {"All-Employees", "Engineering", "GitHub-Users", "AWS-Dev-Access"}

    def test_transfer_adds_and_removes(self):
        """Moving Engineering → Product should remove eng groups and add product groups."""
        old = {"All-Employees", "Engineering", "GitHub-Users", "AWS-Dev-Access"}
        new = {"All-Employees", "Product", "Figma-Users", "Amplitude-Users"}

        to_remove, to_add, preserved = diff_groups(old, new)

        assert to_remove == {"Engineering", "GitHub-Users", "AWS-Dev-Access"}
        assert to_add == {"Product", "Figma-Users", "Amplitude-Users"}
        assert preserved == {"All-Employees"}

    def test_no_change(self):
        """A MOVE with identical groups should produce empty add/remove."""
        old = {"All-Employees", "Engineering"}
        new = {"All-Employees", "Engineering"}

        to_remove, to_add, preserved = diff_groups(old, new)

        assert to_remove == set()
        assert to_add == set()
        assert preserved == {"All-Employees", "Engineering"}

    def test_complete_removal(self):
        """Moving to a role with zero groups should remove everything."""
        old = {"All-Employees", "Engineering", "GitHub-Users"}
        new = set()

        to_remove, to_add, preserved = diff_groups(old, new)

        assert to_remove == {"All-Employees", "Engineering", "GitHub-Users"}
        assert to_add == set()
        assert preserved == set()

    def test_complete_addition(self):
        """A new hire (empty old set) should add everything."""
        old = set()
        new = {"All-Employees", "Engineering", "GitHub-Users"}

        to_remove, to_add, preserved = diff_groups(old, new)

        assert to_remove == set()
        assert to_add == {"All-Employees", "Engineering", "GitHub-Users"}
        assert preserved == set()