#
# Handles programming of production series EEPROMs, including serialisation of the unique_id
#
# Public interface (called by the main app):
#   __init__(app)       – wire up to the main HexManagerApp instance
#   update(delta)       – per-tick hexpansion state-machine update
#   draw(ctx)           – render hexpansion-related UI states

import settings

from app_components.notification import Notification
from app_components.tokens import button_labels, label_font_size
from events.input import BUTTON_TYPES
from system.eventbus import eventbus
from system.hexpansion.events import HexpansionInsertionEvent, HexpansionRemovalEvent

# Local sub-states (internal to Serialise Mgr)
_SUB_INIT            = 0           # Initial state on app startup
_SUB_SETUP           = 1           # State for setting up serialisation parameters
_SUB_WAITING         = 2           # Waiting for a hexpansion board to be inserted
_SUB_ERASE_CONFIRM   = 3           # Non-blank EEPROM detected and awaiting erase confirmation
_SUB_ERASE           = 4           # EEPROM erase in progress
_SUB_SUMMARY         = 5           # Summary and unique ID confirmation before programming
_SUB_PROGRAMMING     = 6           # Programming in progress
_SUB_DONE            = 7           # Programming complete, waiting for board removal
_SUB_EXIT            = 9           # State for exiting from interactive mode back to menu)

_COLOUR_TITLE = (1, 1, 0)
_COLOUR_TYPE = (1, 0, 1)
_COLOUR_DATA = (0, 1, 1)
_COLOUR_ERROR = (1, 0, 0)
_COLOUR_SUCCESS = (0, 1, 0)


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
        self._selected_type_index: int = 0
        self._hexpansion_serial_number: int | None = None
        self._active_port: int | None = None
        self._pending_port: int | None = None
        self._removed_port: int | None = None
        self._message_being_shown: bool = False
        self._programming_pending: bool = False
        self._erase_pending: bool = False
        self._events_registered: bool = False

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


    def register_events(self):
        """Register insertion and removal handlers for the serialise flow."""
        if self._events_registered:
            return
        eventbus.on_async(HexpansionInsertionEvent, self._handle_insertion, self._app)
        eventbus.on_async(HexpansionRemovalEvent, self._handle_removal, self._app)
        self._events_registered = True


    def unregister_events(self):
        """Unregister insertion and removal handlers for the serialise flow."""
        if not self._events_registered:
            return
        eventbus.remove(HexpansionInsertionEvent, self._handle_insertion, self._app)
        eventbus.remove(HexpansionRemovalEvent, self._handle_removal, self._app)
        self._events_registered = False


    async def _handle_insertion(self, event):
        if not self._app.serialise_active:
            return
        if self._sub_state == _SUB_WAITING and self._active_port is None and self._pending_port is None:
            self._pending_port = event.port
            self._app.refresh = True
            if self._logging:
                print(f"H:Serialise pending insert on port {event.port}")


    async def _handle_removal(self, event):
        if not self._app.serialise_active:
            return
        if self._pending_port == event.port:
            self._pending_port = None
        if self._active_port == event.port:
            self._removed_port = event.port
            self._app.refresh = True
            if self._logging:
                print(f"H:Serialise removal on port {event.port}")


    # ------------------------------------------------------------------
    # Entry point from menu
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Enter serialise management from the main menu."""
        app = self._app
        if getattr(app, "_hexpansion_mgr", None) is None or not app.HEXPANSION_TYPES:
            return False
        app.set_menu(None)
        app.button_states.clear()
        app.refresh = True
        app.auto_repeat_clear()
        app.serialise_active = True
        app.hexpansion_update_required = False
        self.register_events()
        self._prev_state = _SUB_INIT
        self._active_port = None
        self._pending_port = None
        self._removed_port = None
        self._message_being_shown = False
        self._programming_pending = False
        self._erase_pending = False
        if self._selected_type_index >= len(app.HEXPANSION_TYPES):
            self._selected_type_index = 0
        self._enter_setup()
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

        if self._message_being_shown:
            self._message_being_shown = False
            app.refresh = True

        if self._removed_port is not None:
            removed_port = self._removed_port
            self._removed_port = None
            self._process_removed_port(removed_port)
            return True

        if self._sub_state == _SUB_WAITING and self._pending_port is not None:
            pending_port = self._pending_port
            self._pending_port = None
            self._process_pending_port(pending_port)
            return True

        if self._sub_state == _SUB_SETUP:
            self._update_state_setup(delta)
        elif self._sub_state == _SUB_WAITING:
            self._update_state_waiting(delta)
        elif self._sub_state == _SUB_ERASE_CONFIRM:
            self._update_state_erase_confirm(delta)
        elif self._sub_state == _SUB_ERASE:
            self._update_state_erase(delta)
        elif self._sub_state == _SUB_SUMMARY:
            self._update_state_summary(delta)
        elif self._sub_state == _SUB_PROGRAMMING:
            self._update_state_programming(delta)
        elif self._sub_state == _SUB_DONE:
            self._update_state_done(delta)

        if self._sub_state != self._prev_state:
            if self._logging:
                print(f"H:SerialiseMgr State: {self._prev_state} -> {self._sub_state}")
            self._prev_state = self._sub_state

        if self._sub_state == _SUB_EXIT:
            self._exit_serialise()

        return True


    # ------------------------------------------------------------------
    # Individual state handlers
    # ------------------------------------------------------------------


    def _hexpansion_mgr(self):
        return getattr(self._app, "_hexpansion_mgr", None)


    def _selected_type(self):
        return self._app.HEXPANSION_TYPES[self._selected_type_index]


    def _app_storage_text(self) -> str:
        if self._selected_type().app_mpy_name is None:
            return "EEPROM Only"
        return "With app"


    def _type_detail_lines(self, include_storage: bool = True, include_pid: bool = False, include_id: bool = False) -> tuple[list[str], list[tuple[int, int, int]]]:
        hexpansion_type = self._selected_type()
        lines = [hexpansion_type.name]
        colours = [_COLOUR_TYPE]
        if hexpansion_type.sub_type:
            lines.append(hexpansion_type.sub_type)
            colours.append(_COLOUR_TYPE)
        if include_storage:
            lines.append(self._app_storage_text())
            colours.append(_COLOUR_DATA)
        if include_pid:
            lines.append(f"PID {hexpansion_type.pid:04X}")
            colours.append(_COLOUR_DATA)
        if include_id:
            lines.append(f"ID {self._hexpansion_serial_number}")
            colours.append(_COLOUR_DATA)
        return lines, colours


    @staticmethod
    def _pad_message_rows(lines: list[str], colours: list[tuple[int, int, int]], row_count: int) -> tuple[list[str], list[tuple[int, int, int]]]:
        while len(lines) < row_count:
            lines.append("")
            colours.append((1, 1, 1))
        return lines, colours


    def _detail_text(self, port: int | None = None) -> str:
        hexpansion_type = self._selected_type()
        if hexpansion_type.sub_type:
            return hexpansion_type.sub_type
        if port is not None:
            return f"Slot {port}"
        if hexpansion_type.app_mpy_name is None:
            return "EEPROM only"
        return "With app"


    def _enter_setup(self):
        app = self._app
        if 'unique_id' in app.settings:
            self._hexpansion_serial_number = app.settings['unique_id'].v
        else:
            self._hexpansion_serial_number = _DEFAULT_UNIQUE_ID
        self._active_port = None
        self._pending_port = None
        self._removed_port = None
        self._programming_pending = False
        self._erase_pending = False
        self._sub_state = _SUB_SETUP
        app.auto_repeat_clear()
        app.refresh = True


    def _enter_waiting(self):
        app = self._app
        self._active_port = None
        self._pending_port = None
        self._removed_port = None
        self._programming_pending = False
        self._erase_pending = False
        self._sub_state = _SUB_WAITING
        app.auto_repeat_clear()
        app.refresh = True


    def _show_serialise_message(self, lines, colours, resume_state: int = _SUB_WAITING):
        app = self._app
        app.button_states.clear()
        self._sub_state = resume_state
        self._message_being_shown = True
        app.show_message(lines, colours, "serialise")


    def _persist_unique_id(self):
        app = self._app
        if 'unique_id' not in app.settings or self._hexpansion_serial_number is None:
            return
        app.settings['unique_id'].v = self._hexpansion_serial_number
        app.settings['unique_id'].persist()
        settings.save()


    def _process_pending_port(self, port: int):
        app = self._app
        hex_mgr = self._hexpansion_mgr()
        if hex_mgr is None:
            self._show_serialise_message(["No helper", "available"], [_COLOUR_ERROR, _COLOUR_ERROR], _SUB_SETUP)
            return
        status, _ = hex_mgr.probe_eeprom(port)
        if status == hex_mgr.HEXPANSION_STATE_BLANK:
            self._active_port = port
            app.notification = Notification("Ready", port=port)
            self._sub_state = _SUB_SUMMARY
            app.refresh = True
            return
        if status >= hex_mgr.HEXPANSION_STATE_UNRECOGNISED:
            self._active_port = port
            app.notification = Notification("Erase?", port=port)
            self._sub_state = _SUB_ERASE_CONFIRM
            app.refresh = True
            return
        self._active_port = None
        if status == hex_mgr.HEXPANSION_STATE_EMPTY:
            self._show_serialise_message(["No EEPROM", f"Slot {port}"], [_COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)
            return
        self._show_serialise_message(["Read fail", f"Slot {port}"], [_COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)


    def _process_removed_port(self, port: int):
        if self._sub_state == _SUB_DONE:
            self._active_port = None
            self._enter_waiting()
            return
        if self._sub_state in (_SUB_ERASE_CONFIRM, _SUB_ERASE, _SUB_SUMMARY, _SUB_PROGRAMMING):
            self._active_port = None
            self._programming_pending = False
            self._erase_pending = False
            self._show_serialise_message(["Board", "removed", f"Slot {port}"], [_COLOUR_ERROR, _COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)


    def _exit_serialise(self):
        app = self._app
        hexpansion_mgr = self._hexpansion_mgr()
        if self._logging:
            print("H:EXIT")
        self.unregister_events()
        app.serialise_active = False
        if hexpansion_mgr is not None:
            hexpansion_mgr.refresh_slot_records()
        app.hexpansion_update_required = False
        self._active_port = None
        self._pending_port = None
        self._removed_port = None
        self._programming_pending = False
        self._erase_pending = False
        self._message_being_shown = False
        self._sub_state = _SUB_INIT
        app.return_to_menu()


    def _update_state_setup(self, delta) -> bool:     # pylint: disable=unused-argument
        app = self._app
        if app.button_states.get(BUTTON_TYPES["CONFIRM"]):
            app.button_states.clear()
            self._enter_waiting()
        elif app.button_states.get(BUTTON_TYPES["CANCEL"]):
            app.button_states.clear()
            self._sub_state = _SUB_EXIT
        elif app.button_states.get(BUTTON_TYPES["UP"]):
            app.button_states.clear()
            self._selected_type_index = (self._selected_type_index + 1) % len(app.HEXPANSION_TYPES)
            app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["DOWN"]):
            app.button_states.clear()
            self._selected_type_index = (self._selected_type_index - 1) % len(app.HEXPANSION_TYPES)
            app.refresh = True
        return True


    def _update_state_waiting(self, delta) -> bool:   # pylint: disable=unused-argument
        app = self._app
        unique_id_setting = app.settings.get('unique_id')
        if app.button_states.get(BUTTON_TYPES["UP"]):
            if app.auto_repeat_check(delta, False) and unique_id_setting is not None:
                self._hexpansion_serial_number = unique_id_setting.inc(self._hexpansion_serial_number, app.auto_repeat_level)
                app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["DOWN"]):
            if app.auto_repeat_check(delta, False) and unique_id_setting is not None:
                self._hexpansion_serial_number = unique_id_setting.dec(self._hexpansion_serial_number, app.auto_repeat_level)
                app.refresh = True
        else:
            app.auto_repeat_clear()
            if app.button_states.get(BUTTON_TYPES["CANCEL"]):
                app.button_states.clear()
                self._enter_setup()
        return True


    def _update_state_erase_confirm(self, delta) -> bool:      # pylint: disable=unused-argument
        app = self._app
        if self._active_port is None:
            self._enter_waiting()
            return True
        if app.button_states.get(BUTTON_TYPES["CONFIRM"]):
            app.button_states.clear()
            app.notification = Notification("Erasing", port=self._active_port)
            self._erase_pending = True
            self._sub_state = _SUB_ERASE
            app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["CANCEL"]):
            app.button_states.clear()
            self._enter_waiting()
        return True


    def _update_state_erase(self, delta) -> bool:      # pylint: disable=unused-argument
        app = self._app
        hexpansion_mgr = self._hexpansion_mgr()
        if self._active_port is None or hexpansion_mgr is None:
            self._enter_waiting()
            return True
        if self._erase_pending:
            self._erase_pending = False
            app.refresh = True
            return True
        if hexpansion_mgr.erase_eeprom_for_type(self._active_port, self._selected_type_index):
            app.notification = Notification("Ready", port=self._active_port)
            self._sub_state = _SUB_SUMMARY
            app.refresh = True
        else:
            failed_port = self._active_port
            self._active_port = None
            app.notification = Notification("Failed", port=failed_port)
            self._show_serialise_message(["Erase fail", "Protected?", f"Slot {failed_port}"], [_COLOUR_ERROR, _COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)
        return True


    def _update_state_summary(self, delta) -> bool:
        app = self._app
        unique_id_setting = app.settings.get('unique_id')
        if self._active_port is None:
            self._enter_waiting()
            return True
        if app.button_states.get(BUTTON_TYPES["UP"]):
            if app.auto_repeat_check(delta, False) and unique_id_setting is not None:
                self._hexpansion_serial_number = unique_id_setting.inc(self._hexpansion_serial_number, app.auto_repeat_level)
                app.refresh = True
        elif app.button_states.get(BUTTON_TYPES["DOWN"]):
            if app.auto_repeat_check(delta, False) and unique_id_setting is not None:
                self._hexpansion_serial_number = unique_id_setting.dec(self._hexpansion_serial_number, app.auto_repeat_level)
                app.refresh = True
        else:
            app.auto_repeat_clear()
            if app.button_states.get(BUTTON_TYPES["CONFIRM"]):
                app.button_states.clear()
                app.notification = Notification("Program", port=self._active_port)
                self._programming_pending = True
                self._sub_state = _SUB_PROGRAMMING
                app.refresh = True
            elif app.button_states.get(BUTTON_TYPES["CANCEL"]):
                app.button_states.clear()
                self._enter_waiting()
        return True


    def _update_state_programming(self, delta) -> bool:      # pylint: disable=unused-argument
        app = self._app
        hexpansion_mgr = self._hexpansion_mgr()
        port = self._active_port
        if port is None or hexpansion_mgr is None:
            self._enter_waiting()
            return True
        if self._programming_pending:
            self._programming_pending = False
            app.refresh = True
            return True
        if not hexpansion_mgr.prepare_eeprom_for_type(port, self._selected_type_index, self._hexpansion_serial_number):
            self._active_port = None
            app.notification = Notification("Failed", port=port)
            self._show_serialise_message(["Init fail", "Protected?", f"Slot {port}"], [_COLOUR_ERROR, _COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)
            return True

        app_name = self._selected_type().app_mpy_name
        if app_name is not None:
            result = hexpansion_mgr.program_app_for_type(port, self._selected_type_index)
            if result == -1:
                self._active_port = None
                app.notification = Notification("App Miss", port=port)
                self._show_serialise_message(["App file", "missing", app_name], [_COLOUR_ERROR, _COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)
                return True
            if result <= 0:
                self._active_port = None
                app.notification = Notification("Failed", port=port)
                self._show_serialise_message(["Program", "failed", f"Slot {port}"], [_COLOUR_ERROR, _COLOUR_ERROR, _COLOUR_DATA], _SUB_WAITING)
                return True

        if 'unique_id' in app.settings:
            self._hexpansion_serial_number = app.settings['unique_id'].inc(self._hexpansion_serial_number, 0)
        elif self._hexpansion_serial_number is not None:
            self._hexpansion_serial_number += 1
        self._persist_unique_id()
        eventbus.emit(HexpansionInsertionEvent(port))
        app.notification = Notification("Programmed", port=port)
        self._sub_state = _SUB_DONE
        app.refresh = True
        return True


    def _update_state_done(self, delta) -> bool:      # pylint: disable=unused-argument
        app = self._app
        if app.button_states.get(BUTTON_TYPES["CANCEL"]):
            app.button_states.clear()
            self._sub_state = _SUB_EXIT
        return True


    # ------------------------------------------------------------------
    # Draw serialisation-related states
    # ------------------------------------------------------------------

    def draw(self, ctx) -> bool:
        """Render UI for hexpansion-related states.  Returns True if handled."""
        app = self._app
        hexpansion_type = self._selected_type()
        if self._sub_state == _SUB_SETUP:
            type_lines, type_colours = self._type_detail_lines(include_pid=True)
            setup_lines, setup_colours = self._pad_message_rows(["Select Type"] + type_lines,
                                                                [_COLOUR_TITLE] + type_colours,
                                                                5)
            app.draw_message(ctx,
                             setup_lines,
                             setup_colours,
                             label_font_size)
            button_labels(ctx, confirm_label="Select", up_label=app.special_chars['up'], down_label="\u25BC", cancel_label="Back")
            return True
        if self._sub_state == _SUB_WAITING:
            type_lines, type_colours = self._type_detail_lines(include_storage=False, include_id=True)
            waiting_lines, waiting_colours = self._pad_message_rows(["Insert Board"] + type_lines,
                                                                [_COLOUR_TITLE] + type_colours,
                                                                5)
            app.draw_message(ctx,
                             waiting_lines,
                             waiting_colours,
                             label_font_size)
            button_labels(ctx, up_label="ID+", down_label="ID-", cancel_label="Back")
            return True
        if self._sub_state == _SUB_ERASE_CONFIRM and self._active_port is not None:
            app.draw_message(ctx,
                             [f"Slot {self._active_port}", hexpansion_type.name, "Erase", "EEPROM?"],
                             [_COLOUR_TITLE, _COLOUR_TYPE, _COLOUR_TITLE, _COLOUR_TITLE],
                             label_font_size)
            button_labels(ctx, confirm_label="Yes", cancel_label="No")
            return True
        if self._sub_state == _SUB_ERASE and self._active_port is not None:
            app.draw_message(ctx,
                             [f"Slot {self._active_port}", hexpansion_type.name, "Erasing", "Please wait"],
                             [_COLOUR_TITLE, _COLOUR_TYPE, _COLOUR_TITLE, _COLOUR_TITLE],
                             label_font_size)
            button_labels(ctx)
            return True
        if self._sub_state == _SUB_SUMMARY and self._active_port is not None:
            type_lines, type_colours = self._type_detail_lines(include_storage=False)
            app.draw_message(ctx,
                             [f"Slot {self._active_port}"] + type_lines + [f"ID {self._hexpansion_serial_number}"],
                             [_COLOUR_TITLE] + type_colours + [_COLOUR_DATA],
                             label_font_size)
            button_labels(ctx, confirm_label="Prog", up_label="ID+", down_label="ID-", cancel_label="Back")
            return True
        if self._sub_state == _SUB_PROGRAMMING and self._active_port is not None:
            app.draw_message(ctx,
                             [f"Slot {self._active_port}", hexpansion_type.name, "Programming", "Please wait..."],
                             [_COLOUR_TITLE, _COLOUR_TYPE, _COLOUR_TITLE, _COLOUR_TITLE],
                             label_font_size)
            button_labels(ctx)
            return True
        if self._sub_state == _SUB_DONE:
            app.draw_message(ctx,
                             ["Programmed", "Please", "Remove"],
                             [_COLOUR_SUCCESS, _COLOUR_TITLE, _COLOUR_TITLE],
                             label_font_size)
            button_labels(ctx, cancel_label="Exit")
            return True
        return False
