#
# Handles programming of production series EEPROMs, including serialisation of the unique_id
#
# Public interface (called by the main app):
#   __init__(app)       – wire up to the main HexManagerApp instance
#   update(delta)       – per-tick hexpansion state-machine update
#   draw(ctx)           – render hexpansion-related UI states

import os
import sys
import app
import time

import vfs
from app_components.notification import Notification
from app_components.tokens import label_font_size, button_labels
from events.input import BUTTON_TYPES
from machine import I2C
from system.eventbus import eventbus
from system.hexpansion.events import HexpansionInsertionEvent
from system.hexpansion.header import HexpansionHeader, write_header
from system.hexpansion.util import get_hexpansion_block_devices, detect_eeprom_addr
from system.scheduler import scheduler

_IS_SIMULATOR = sys.platform != "esp32"

# Local sub-states (internal to Serialise Mgr)
_SUB_INIT            = 0           # Initial state on app startup
_SUB_SETUP           = 1           # State for setting up serialisation parameters
_SUB_EXIT            = 9           # State for exiting from interactive mode back to menu)


# Defaults for settings:
_DEFAULT_UNIQUE_ID = 0x0001     # Starting Unique ID for EEPROM Serialisation


# ---- Settings initialisation -----------------------------------------------

def init_settings(s, MySetting):        # pylint: disable=unused-argument, invalid-name
    """Register hexpansion-management-specific settings in the shared settings dict."""
    s['unique_id']    = MySetting(s, _DEFAULT_UNIQUE_ID, 0, 65535)
    return


# ---- Serialisation Manager Class ------------------------------------------------ 
class SerialiseMgr:
    """Manages hexpansion serialisation.

    Parameters
    ----------
    app : HexManagerApp
        Reference to the main application instance so that shared state
        (settings, current_state …) can be
        read and written.
    """

    # Sub-states are defined at module level (_SUB_*); app-level state
    # routing is handled by the dispatch tables in app.py.

    def __init__(self, app, logging: bool = False):
        self._app = app
        self._logging: bool = logging
        self._sub_state: int = _SUB_INIT
        self._prev_state: int = _SUB_INIT
        self._hexpansion_serial_number: int | None = None

        if self._logging:
            print("SerialiseMgr initialised")


    # ------------------------------------------------------------------


    @property
    def logging(self) -> bool:
        """Get the current logging state."""
        return self._logging

    @logging.setter
    def logging(self, value: bool):
        """Set the logging state."""
        self._logging = value


    # ------------------------------------------------------------------
    # Entry point from menu
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Enter serialise management from the main menu."""
        app = self._app
        app.set_menu(None)
        app.button_states.clear()
        app.refresh = True
        app.auto_repeat_clear()
        self._sub_state = _SUB_SETUP
        if self._logging:
            print("Entered Serialise Management mode")
        return True


    # ------------------------------------------------------------------
    # Per-tick update  (state machine for hexpansion management)
    # ------------------------------------------------------------------

    def update(self, delta) -> bool:
        """Per-tick update for hexpansion management state machine."""
        app = self._app

        if self._sub_state == _SUB_INIT:
            # Idle state – should never actually be in this state when update is called, but just in case…
            return False
        elif self._sub_state == _SUB_SETUP:
            self._update_state_setup(delta)

        if self._sub_state != self._prev_state:
            if self._logging:
                print(f"H:SerialiseMgr State: {self._prev_state} -> {self._sub_state}")
            self._prev_state = self._sub_state

        if self._sub_state == _SUB_EXIT:
            print("H:EXIT")
            app.return_to_menu()
            self._sub_state = _SUB_INIT

        return True


    # ------------------------------------------------------------------
    # Individual state handlers
    # ------------------------------------------------------------------


    def _update_state_setup(self, delta) -> bool:
        app = self._app
        if app.button_states.get(BUTTON_TYPES["CONFIRM"]):
            app.button_states.clear()
            self._sub_state = _SUB_EXIT
        elif app.button_states.get(BUTTON_TYPES["CANCEL"]):
            app.button_states.clear()
            self._sub_state = _SUB_EXIT
        elif app.button_states.get(BUTTON_TYPES["UP"]):
            app.button_states.clear()
            app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["DOWN"]):
            app.button_states.clear()
            app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["LEFT"]):
            app.button_states.clear()
            app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["RIGHT"]):
            app.button_states.clear()
            app.refresh = True
        return True
    

    # ------------------------------------------------------------------
    # Draw serialisation-related states
    # ------------------------------------------------------------------

    def draw(self, ctx) -> bool:
        """Render UI for hexpansion-related states.  Returns True if handled."""
        app = self._app
        if self._sub_state == _SUB_SETUP:
            app.draw_message(ctx, ["Serialisation"], \
                              [(1, 1, 0)], label_font_size)
            return True
        return False


