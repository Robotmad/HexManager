"""Tests for fake-hexpansion infrastructure and hardware-dependent behaviour.

These tests exercise the HexManagerApp with various fake hexpansion
configurations to verify that settings and menu items are correctly
gated by the detected hardware capabilities.
"""
import pytest


# =====================================================================
#  Baseline: NO hexpansion
# =====================================================================

class TestNoHexpansion:
    """Tests with no fake hexpansion – only base settings should exist."""

    def test_base_settings_present(self, badgebot_app):
        """Base settings are always registered in __init__."""
        for key in ('logging', 'unique_id'):
            assert key in badgebot_app.settings, f"Missing base setting: {key}"

    def test_menu_includes_common_items(self, hexmanager_app_with_hexpansion):
        app = hexmanager_app_with_hexpansion
        app.set_menu("main")
        items = [item for item in app.menu.menu_items]
        for expected in ("Hexpansions", "Serialise", "Settings", "About", "Exit"):
            assert expected in items, f"Missing common menu item: {expected}"

# =====================================================================
#  2-Motor HexDrive (PID 0xCBCA)
# =====================================================================

class TestTwoMotorHexDrive:
    """Tests with a fake 2-Motor HexDrive."""

    @pytest.fixture
    def hexdrive_pid(self):
        return 0xCBCA

    def test_reaches_menu(self, hexmanager_app_with_hexpansion):
        from sim.apps.HexManager.app import STATE_MENU
        assert hexmanager_app_with_hexpansion.current_state == STATE_MENU

    def test_menu_includes_common_items(self, hexmanager_app_with_hexpansion):
        app = hexmanager_app_with_hexpansion
        app.set_menu("main")
        items = [item for item in app.menu.menu_items]
        for expected in ("Hexpansions", "Serialise", "Settings", "About", "Exit"):
            assert expected in items, f"Missing common menu item: {expected}"
