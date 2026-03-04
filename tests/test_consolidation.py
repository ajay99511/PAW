"""
Tests for the memory consolidation module.
"""

import pytest
from packages.memory.consolidation import (
    increment_turn,
    get_turn_count,
    reset_turn_count,
    should_consolidate,
)


class TestTurnCounter:
    """Tests for in-memory turn tracking."""

    def setup_method(self):
        """Reset counter before each test."""
        reset_turn_count("test_user")

    def test_increment_starts_at_one(self):
        assert increment_turn("test_user") == 1

    def test_increment_accumulates(self):
        for _ in range(5):
            increment_turn("test_user")
        assert get_turn_count("test_user") == 5

    def test_reset_clears_count(self):
        for _ in range(10):
            increment_turn("test_user")
        reset_turn_count("test_user")
        assert get_turn_count("test_user") == 0

    def test_separate_users_tracked_independently(self):
        for _ in range(3):
            increment_turn("alice")
        for _ in range(7):
            increment_turn("bob")
        assert get_turn_count("alice") == 3
        assert get_turn_count("bob") == 7
        # Cleanup
        reset_turn_count("alice")
        reset_turn_count("bob")


class TestShouldConsolidate:
    """Tests for the consolidation trigger logic."""

    def setup_method(self):
        reset_turn_count("test_user")

    def test_does_not_trigger_at_zero(self):
        assert should_consolidate("test_user", threshold=5) is False

    def test_triggers_at_threshold(self):
        for _ in range(5):
            increment_turn("test_user")
        assert should_consolidate("test_user", threshold=5) is True

    def test_does_not_trigger_before_threshold(self):
        for _ in range(4):
            increment_turn("test_user")
        assert should_consolidate("test_user", threshold=5) is False

    def test_triggers_at_multiples_of_threshold(self):
        for _ in range(10):
            increment_turn("test_user")
        assert should_consolidate("test_user", threshold=5) is True

    def test_does_not_trigger_between_multiples(self):
        for _ in range(7):
            increment_turn("test_user")
        assert should_consolidate("test_user", threshold=5) is False
