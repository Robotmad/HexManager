""" Main Application File for HexManager."""
import asyncio
import sys
import time
from math import cos, pi

import ota
import settings
from app_components.notification import Notification
from app_components.tokens import button_labels, label_font_size, twentyfour_pt, clear_background
from app_components import Menu
from events.input import BUTTON_TYPES, Button, Buttons, ButtonUpEvent
from frontboards.twentyfour import BUTTONS
from system.eventbus import eventbus
from system.hexpansion.config import HexpansionConfig
from system.patterndisplay.events import PatternDisable, PatternEnable
from system.scheduler.events import (RequestForegroundPopEvent,
                                     RequestForegroundPushEvent,
                                     RequestStopAppEvent)
from tildagonos import tildagonos
from machine import Pin
import app

from .EEPROM.hexdrive import VERSION as HEXDRIVE_APP_VERSION


_SETTINGS_NAME_PREFIX = "hexmanager."  # Prefix for settings keys in EEPROM
APP_VERSION = "0.1" # HexManager App Version Number

# Screen positioning constant for scroll mode display
H_START = -63

# Timings
_AUTO_REPEAT_MS = 200       # Time between auto-repeats, in ms
_AUTO_REPEAT_COUNT_THRES = 10 # Number of auto-repeats before increasing level
_AUTO_REPEAT_SPEED_LEVEL_MAX = 4  # Maximum level of auto-repeat speed increases
_AUTO_REPEAT_LEVEL_MAX = 3  # Maximum level of auto-repeat digit increases

# App states
STATE_MENU = 0
STATE_MESSAGE = 1         # Message display
STATE_SETTINGS = 2        # Edit Settings
STATE_HEXPANSION = 3      # Hexpansion Management (sub-states managed by HexpansionMgr)
STATE_SERIALISE = 4       # Serialise Hexpansion Initialisation (sub-states managed by SerialiseMgr)

# App states where user can minimise app (Menu, Message)
MINIMISE_VALID_STATES = [STATE_MENU, STATE_MESSAGE]

#Misceallaneous Settings
_LOGGING = False
_IS_SIMULATOR = sys.platform != "esp32"  # True when running in the simulator, not on real badge hardware


# Main Menu Items
MAIN_MENU_ITEMS = ["Hexpansions", "Serialise", "Settings", "About","Exit"]
MENU_ITEM_HEXPANSION = 0
MENU_ITEM_SERIALISE = 1
MENU_ITEM_SETTINGS = 2
MENU_ITEM_ABOUT = 3
MENU_ITEM_EXIT = 4

# Import sub-modules after constants are defined so they can safely
# `from .app import STATE_*` without circular-import timing issues.
# Each module registers its own settings via init_settings()
# This is just a very robust way of doing from .module import XYZ which does
# not crash if anything in the module fails to import, and allows us to import
# individual classes from the modules without importing the whole module.
def _try_import(module_name, *attr_names):
    """Try importing named attributes from a sibling submodule.
    Returns a tuple of the requested attributes (or None for each on failure)."""
    nones = (None,) * len(attr_names)
    pkg_name = __name__.rsplit('.', 1)[0]
    full_name = pkg_name + '.' + module_name
    try:
        __import__(full_name)
        mod = sys.modules[full_name]
        return tuple(getattr(mod, n) for n in attr_names)
    except ImportError as e:
        print(f"Warning: {module_name} module not found ({e})")
    except Exception as e:                          # pylint: disable=broad-except
        print(f"Error importing {module_name} module ({e})")
    return nones

HexpansionMgr, HexpansionType, _hexpansion_init_settings = _try_import('hexpansion_mgr', 'HexpansionMgr', 'HexpansionType', 'init_settings')
SerialiseMgr,                  _serialise_init_settings  = _try_import('serialise_mgr',  'SerialiseMgr',                    'init_settings')
SettingsMgr, MySetting                                   = _try_import('settings_mgr',   'SettingsMgr', 'MySetting')


class HexManagerApp(app.App):         # pylint: disable=no-member
    """Main application class for HexManager.  Manages overall state, user input, and delegates to functional area managers for specific features."""
    def __init__(self):
        super().__init__()

        # UI Button Controls
        self.button_states = Buttons(self)
        self.last_press: Button = BUTTON_TYPES["CANCEL"]
        self._auto_repeat_intervals = [ _AUTO_REPEAT_MS, _AUTO_REPEAT_MS//2, _AUTO_REPEAT_MS//4, _AUTO_REPEAT_MS//8, _AUTO_REPEAT_MS//16] # at the top end the loop is unlikley to cycle this fast
        self._auto_repeat: int = 0
        self._auto_repeat_count: int = 0
        self.auto_repeat_level: int = 0

        # UI Feature Controls
        self.refresh: bool = True            # True so that we draw initial screen on first loop, then set to True whenever we want to trigger a screen update
        self.app_version: str = APP_VERSION
        self.notification: Notification | None = None
        self.message: list = []
        self.message_colours: list = []
        self.message_type: str | None = None
        self.current_menu: str | None = None
        self.menu: Menu | None = None
        self.scroll_mode_enabled: bool = False  # Whether pressing the "C" button can toggle scroll mode on/off, which allows the user to scroll through lines on the display.
        self.scroll_ignore_next_c_button: bool = False # Used to ignore the "C" button event that triggers scroll mode on, otherwise it would immediately toggle scroll mode off again
        self.is_scroll: bool = False        # Whether we are in scroll mode - this is displayed by a green border around the screen
        self.scroll_offset: int = 0

         # Settings - common settings first, then each module registers its own later
        self.settings: dict = {}
        if MySetting is not None:
            # General settings
            self.settings['logging']       = MySetting(self.settings, _LOGGING, False, True)

            # Module-specific settings:
            if _hexpansion_init_settings is not None:
                _hexpansion_init_settings(self.settings, MySetting)
            if _serialise_init_settings is not None:
                _serialise_init_settings(self.settings, MySetting)

            self.update_settings()

        # Check what version of the Badge s/w we are running on
        ver: list[int | str] | None = None
        try:
            ver = parse_version(ota.get_version())
            if ver is not None:
                if self.logging:
                    print(f"BadgeSW V{ver}")
                # Potential to do things differently based on badge s/w version
                # e.g. if ver < [1, 9, 0]:
        except Exception: # pylint: disable=broad-exception-caught
            pass

        # make use of special characters if running on compatible badge s/w version
        version_triplet = tuple(part if isinstance(part, int) else 0 for part in (ver[:3] if ver is not None else []))
        if len(version_triplet) == 3 and version_triplet > (2, 0, 0):
            self.special_chars = { 'up': "\u25B2",        # up arrow
                                # 'down': "\u25BC",     # down arrow - has always existed
                                  'left': "\u25C0",     # left arrow
                                  'right': "\u25B6" }   # right arrow
        else:
            self.special_chars = {'up': "^", 'left': "<", 'right': ">"}


        # If vid is not specified then default is the UHB-IF uncontrolled VID 0xCAFE
        #                                       pid      name         vid          eeprom total size        eeprom page size      app mpy name                 app mpy version                       app name                motors    servos    sensors    sub_type
        assert HexpansionType is not None
        self.HEXPANSION_TYPES = [HexpansionType(0xCBCB, "HexDrive",                                                               app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp", motors=2, servos=4, sub_type="Uncommitted" ),
                                 HexpansionType(0xCBCA, "HexDrive",                                                               app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp", motors=2,           sub_type="2 Motor" ),
                                 HexpansionType(0xCBCC, "HexDrive",                                                               app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp",           servos=4, sub_type="4 Servo" ),
                                 HexpansionType(0xCBCD, "HexDrive",                                                               app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp", motors=1, servos=2, sub_type="1 Mot 2 Srvo" ),
                                 HexpansionType(0x0100, "HexSense",    vid=0xCBCB, eeprom_total_size=65536, eeprom_page_size=128,                                                                                                    sensors=2,  sub_type="2 Line Sensors"),
                                 HexpansionType(0x0200, "HexDriveV2",  vid=0xCBCB, eeprom_total_size=32768, eeprom_page_size= 64, app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp", motors=2, servos=2, sub_type="Uncommitted" ),
                                 HexpansionType(0x0201, "HexDriveV2",  vid=0xCBCB, eeprom_total_size=32768, eeprom_page_size= 64, app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp", motors=2,           sub_type="2 Motor" ),
                                 HexpansionType(0x0202, "HexDriveV2",  vid=0xCBCB, eeprom_total_size=32768, eeprom_page_size= 64, app_mpy_name="hexdrive.mpy", app_mpy_version=HEXDRIVE_APP_VERSION, app_name="HexDriveApp",           servos=2, sub_type="2 Servo" ),
                                 HexpansionType(0x0300, "HexTest",     vid=0xCBCB, eeprom_total_size=65536, eeprom_page_size=128),
                                 HexpansionType(0x0400, "HexDiag",     vid=0xCBCB, eeprom_total_size=65536, eeprom_page_size=128),
                                 HexpansionType(0x1295, "GPS",                     eeprom_total_size= 2048, eeprom_page_size= 16, app_mpy_name="gps.mpy", app_mpy_version=1, app_name="GPSApp"),
                                 HexpansionType(0xD15C, "Flopagon",                eeprom_total_size= 2048, eeprom_page_size= 16), # EEPROM too small for the app
                                 HexpansionType(0xCAFF, "Club Mate",               eeprom_total_size= 8192, eeprom_page_size= 32, app_mpy_name="caffeine.mpy", app_name="CaffeineJitter"),

                                 HexpansionType(0x0000, "Unknown",   sub_type=""),       # Virtual type to represent unrecognised hexpansions
                                 HexpansionType(0xFFFF, "Blank",     sub_type="")]       # Virtual type to represent blank EEPROMs

        self.UNRECOGNISED_HEXPANSION_INDEX = len(self.HEXPANSION_TYPES) - 2 # Index in the HEXPANSION_TYPES list which corresponds to unrecognised hexpansion types MUST BE LAST NON-BLANK ENTRY IN THE LIST
        self.BLANK_HEXPANSION_INDEX = len(self.HEXPANSION_TYPES) - 1        # Index in the HEXPANSION_TYPES list which corresponds to blank EEPROMs
        self.hexpansion_update_required: bool = False # flag from async to main loop

        # Functional area managers
        self._hexpansion_mgr   = HexpansionMgr(self, logging=self.logging)  if HexpansionMgr is not None else None
        self._settings_mgr     = SettingsMgr(self, logging=self.logging)    if SettingsMgr is not None else None
        self._serialise_mgr    = SerialiseMgr(self, logging=self.logging)   if SerialiseMgr is not None else None
 
        # State -> manager dispatch tables (only include managers that exist)
        self._state_update_dispatch = {}
        self._state_draw_dispatch = {}

        self._register_state_functions(STATE_HEXPANSION, self._hexpansion_mgr)
        self._register_state_functions(STATE_SERIALISE, self._serialise_mgr)
        self._register_state_functions(STATE_SETTINGS, self._settings_mgr)

        # Overall app state (controls what is displayed and what user inputs are accepted)
        self.current_state = STATE_HEXPANSION
        self.previous_state = self.current_state

        # Hexpansion event handlers registered directly by hexpansion_mgr
        if self._hexpansion_mgr is not None:
            self._hexpansion_mgr.register_events()

        # Event handlers for gaining and losing focus
        eventbus.on_async(RequestForegroundPushEvent, self._gain_focus, self)
        eventbus.on_async(RequestForegroundPopEvent, self._lose_focus, self)

        # We start with focus on launch, without an event emmited
        # This version is compatible with the simulator
        asyncio.get_event_loop().create_task(self._gain_focus(RequestForegroundPushEvent(self)))

        if self.logging:
            print(f"HexManager App V{self.app_version} Initialised")


    def _register_state_functions(self, state: int, manager: object | None):
        """Register the update, draw, and background update functions for each state in the dispatch tables."""
        if manager is None:
            return
        update_fn = getattr(manager, "update", None)
        draw_fn = getattr(manager, "draw", None)
        if callable(update_fn):
            self._state_update_dispatch[state] = update_fn
        if callable(draw_fn):
            self._state_draw_dispatch[state] = draw_fn


    @property
    def logging(self):
        """Convenience property to access logging setting."""
        if 'logging' in self.settings:
            return self.settings['logging'].v
        return True


    ### ASYNC EVENT HANDLERS ###

    async def _gain_focus(self, event: RequestForegroundPushEvent):
        if event.app is self:
            if self.logging:
                print(f"HexManager gained focus in state {self.current_state}")
            if self.scroll_mode_enabled:
                eventbus.on_async(ButtonUpEvent, self._handle_button_up, self)


    async def _lose_focus(self, event: RequestForegroundPopEvent):
        if event.app is self:
            if self.logging:
                print(f"HexManager lost focus from state {self.current_state}")
            if self.scroll_mode_enabled:
                eventbus.remove(ButtonUpEvent, self._handle_button_up, self)


    async def _handle_button_up(self, event: ButtonUpEvent):
        if self.scroll_mode_enabled and event.button == BUTTONS["C"]:
            if self.scroll_ignore_next_c_button:
                self.scroll_ignore_next_c_button = False
                return
            # Toggle scroll mode on/off when "C" button is released
            self.scroll(not self.is_scroll)

 
    @property
    def enable_hexpansion_mgr(self):
        """Whether the Hexpansion Manager is enabled, based on whether the manager is available.  Note that this does not necessarily mean that you have hexpansion hardware, as the manager can be enabled and used for managing settings related to hexpansions even if no hexpansion hardware is detected."""
        return self._hexpansion_mgr is not None

    @property
    def enable_serialise_mgr(self):
        """Whether the Serialise Manager is enabled, based on whether the manager is available."""
        return self._serialise_mgr is not None


    def update_settings(self):
        """Update settings from EEPROM."""
        if self.logging:
            print("Updating settings from EEPROM")
        for s in self.settings:
            self.settings[s].v = settings.get(f"{_SETTINGS_NAME_PREFIX}{s}", self.settings[s].d)
            if self.logging:
                print(f"Setting {s} = {self.settings[s].v}")


    ### MAIN APP CONTROL FUNCTIONS ###

    def update(self, delta: int):
        """Main update function called from the main loop. Handles state transitions, user input, and delegates to functional area managers."""

        if self.notification:
            self.notification.update(delta)
            try:
                # in case access to protected member _is_closed() is not allowed, we catch the exception and
                # to prevent crashes - this means that in this case we won't be able to automatically clear
                # notifications when they are closed, but at least the app won't crash.
                if self.notification._is_closed():  # pylint: disable=protected-access
                    self.notification = None
            except Exception as e:  # pylint: disable=broad-exception-caught
                if self.logging:
                    print(f"Error: checking notification status: {e}")

        # Unfortunately, even though we can track if there is an active notification that we have triggered,
        # we don't have a way to track if there are any other notifications active that we
        # didn't trigger, so we need to perform extra display refresh cycles in case.
        # If a way to know about other notifications becomes available in the future, we can remove the need for these extra refreshes.
        self.refresh = True

        # Update Hexpansion management if something 'hexpansion' related has changed
        if self.hexpansion_update_required:
            if self.current_state != STATE_HEXPANSION and self._hexpansion_mgr is not None:
                # Trigger an update cycle for hexpansion_mgr even though it is not currently active
                self._hexpansion_mgr.update(delta)

        # Update the main application state (menus, countdowns, and delegating to functional area managers)
        self._update_main_application(delta)

        if self.current_state != self.previous_state:
            if self.logging:
                print(f"State: {self.previous_state} -> {self.current_state}")
            self.previous_state = self.current_state
            # something has changed - so worth redrawing
            self.refresh = True



    def _update_main_application(self, delta: int):
        if self.current_state == STATE_MENU:
            if self.current_menu is None:
                self.set_menu()
                self.refresh = True
            else:
                menu = self.menu
                if menu is None:
                    self.set_menu()
                    self.refresh = True
                    return
                menu.update(delta)
                if menu.is_animating != "none":
                    if self.logging:
                        print("Menu is animating")
                    self.refresh = True
        elif self.button_states.get(BUTTON_TYPES["CANCEL"]) and self.current_state in MINIMISE_VALID_STATES:
            self.button_states.clear()
            self.minimise()

        ## Shared Warning and Message Display (for Hexpansion issues and general messages) ###
        elif self.current_state in [STATE_MESSAGE]:
            self._update_state_message(delta)

        ### Delegate to functional area managers via dispatch table ###
        else:
            # Handle scroll mode input for any state where it is enabled, before delegating to the state-specific update function
            if self.scroll_mode_enabled and self.is_scroll:
                if self.button_states.get(BUTTON_TYPES["DOWN"]):
                    self.button_states.clear()
                    self.scroll_offset -= 1
                    self.refresh = True
                elif self.button_states.get(BUTTON_TYPES["UP"]):
                    self.button_states.clear()
                    self.scroll_offset += 1
                    self.refresh = True
            if self.current_state in self._state_update_dispatch:
                update_fn = self._state_update_dispatch.get(self.current_state)
                if update_fn is not None:
                    update_fn(delta)
        ### End of Update ###


    def _update_state_message(self, delta: int):      # pylint: disable=unused-argument
        if self.button_states.get(BUTTON_TYPES["CONFIRM"]):
            if self.message_type == "reboop":
                self.button_states.clear()
                # Reboot has been acknowledged by the user - unfortunately we can't actually reboot the badge from Python.
                return # leave the message on screen.
            elif self.message_type == "error" or self.message_type == "warning" or self.message_type == "hexpansion":
                # Message has been acknowledged by the user
                self.button_states.clear()
                # Recheck Hexpansions - in case the issue is resolved
                self.current_state = STATE_HEXPANSION
            else:
                # Message has been acknowledged by the user - allow access to the menu
                self.button_states.clear()
                # refresh the menu in case available options have changed
                self.set_menu()
                self.refresh = True
                self.current_state = STATE_MENU
            self.message = []
            self.message_colours = []
            self.message_type = None
   

    def scroll_mode_enable(self, enable: bool):
        """Enable the potential for scroll mode to be toggled on and off by pressing the "C" button"""
        if enable:
            self.scroll_mode_enabled = True
            self.scroll_ignore_next_c_button = True # we want to ignore the "C" button event that triggered this, otherwise it would immediately toggle scroll mode on
            eventbus.on_async(ButtonUpEvent, self._handle_button_up, self)
        else:
            self.scroll_mode_enabled = False
            eventbus.remove(ButtonUpEvent, self._handle_button_up, self)


    def scroll(self, enable: bool):
        """Enable or disable scroll mode, which allows the user to scroll the display up and downto see hidden content. This is indicated by a green border around the screen."""
        self.is_scroll = enable
        self.scroll_offset = 0
        if self.scroll_mode_enabled:
            # only show notification about scroll mode if the feature is enabled, otherwise it would be confusing to show a notification about a feature that can't be used
            state = "enabled" if enable else "disabled"
            self.notification = Notification(f"    Scroll    {state}")


    def draw(self, ctx):
        """Main draw function called from the main loop. Handles drawing the current state, including any notifications."""

        if self.current_state == STATE_MENU and self.menu is not None:
            # These need to be drawn every frame as they contain animations
            clear_background(ctx)
            self.menu.draw(ctx)
        elif self.refresh or self.notification:
            #if self.logging:
            #    print(f"Refreshing display {'for Notification' if self.notification else 'for state change'}")
            self.refresh = False
            clear_background(ctx)
            #ctx.save()
            #if in a mode where rotated display is desirable:
            #    ctx.rotate(self.front_face * 2.0 * pi / _FRONT_FACE_NUM_ORIENTATIONS)  # Rotate the entire display based on the front_face setting, so that "forward" is always at the top of the display regardless of how the badge is oriented
            ctx.font_size = label_font_size
            if ctx.text_align != ctx.LEFT:
                # See https://github.com/emfcamp/badge-2024-software/issues/181
                ctx.text_align = ctx.LEFT
            ctx.text_baseline = ctx.BOTTOM

            if self.scroll_mode_enabled and self.is_scroll:
                # Scroll mode indicator border
                ctx.rgb(0,0.2,0).rectangle(     -120,-120, 115+H_START,240).fill()
                ctx.rgb(0,0  ,0).rectangle(H_START-5,-120,10-2*H_START,240).fill()
                ctx.rgb(0,0.2,0).rectangle(5-H_START,-120, 115+H_START,240).fill()
            #else:
            #    ctx.rgb(0,0,0).rectangle(-120,-120,240,240).fill()

            # Common states for messages and errors, which can be triggered by any functional area manager and are displayed in a consistent way
            if self.current_state == STATE_MESSAGE:
                if self.message_colours == []:
                    self.message_colours = [(1,0,0)]*len(self.message)
                self.draw_message(ctx, self.message, self.message_colours, label_font_size)
                if self.message_type is None or self.message_type == "warning" or self.message_type == "hexpansion":
                    button_labels(ctx, confirm_label="OK", cancel_label="Exit")
            else:
                # Delegate to functional area managers via dispatch table
                if self.current_state in self._state_draw_dispatch:
                    draw_fn = self._state_draw_dispatch.get(self.current_state)
                    if draw_fn is not None:
                        draw_fn(ctx)
            #ctx.restore()

        # Notifications are drawn on top of everything else, so that they are visible regardless of the current state.
        # They also contain animations, so need to be drawn every frame when active.
        # As they 'withdraw' they reveal whatever is underneath them so this must be redrawn every frame while they are active to avoid leaving visual glitches on the screen.
        if self.notification:
            self.notification.draw(ctx)


    @staticmethod
    def draw_message(ctx, message, colours, size=label_font_size):
        """Utility function to draw a multi-line message on the screen, with optional colour for each line. The message is centred on the screen, and the y-position of each line is adjusted based on the total number of lines to ensure it is visually balanced."""
        ctx.font_size = size
        num_lines = len(message)
        for i_num, instr in enumerate(message):
            text_line = str(instr)
            width = ctx.text_width(text_line)
            try:
                colour = colours[i_num]
            except IndexError:
                colour = None
            if colour is None:
                colour = (1,1,1)
            # Font is not central in the height allocated to it due to space for descenders etc...
            # this is most obvious when there is only one line of text
            # # position fine tuned to fit around button labels when showing 5 lines of text
            y_position = int(0.35 * ctx.font_size) if num_lines == 1 else int((i_num-((num_lines-2)/2)) * ctx.font_size - 2)
            ctx.rgb(*colour).move_to(-width//2, y_position).text(text_line)


    def return_to_menu(self, menu_name: str | None = None):
        """Utility function to return to the main menu from any state. This is used when the user cancels out of a submenu or after acknowledging a warning message."""
        if self.logging:
            print("Returning to menu")
        if menu_name is not None:
            self.set_menu(menu_name)
        self.current_state = STATE_MENU
        self.refresh = True


    def show_message(self, msg_content, msg_colours, msg_type = None):
        """Utility function to set the current state to the message display, and populate the message content and colours. The message_type can be used to indicate whether this is an 'error' (red) or 'warning' (green) message, which can affect both the display and the behaviour when the user acknowledges the message."""
        if self.logging:
            print(f"Showing message: '{msg_content}' with type {msg_type}")
        self.animation_counter = 0
        self.message = msg_content
        self.message_colours = msg_colours
        self.message_type = msg_type
        self.current_state = STATE_MESSAGE
        self.refresh = True


    # multi level auto repeat
    def auto_repeat_check(self, delta: int, speed_up: bool = True) -> bool:
        """Check if the auto-repeat threshold has been reached for a button hold, and update the auto-repeat level accordingly.
           If speed_up is True, the auto-repeat interval decreases as the level increases, allowing for faster repeats the
           longer the button is held. If speed_up is False, the interval remains constant, but the level can still increase
           to allow for larger increments/decrements in settings adjustments.
           Returns True if the auto-repeat action should be triggered, False otherwise.
        """
        self._auto_repeat += delta
        # multi stage auto repeat - the repeat gets faster the longer the button is held
        if self._auto_repeat > self._auto_repeat_intervals[self.auto_repeat_level if speed_up else 0]:
            self._auto_repeat = 0
            self._auto_repeat_count += 1
            # variable threshold to count to increase level so that it is not too easy to get to the highest level as the auto repeat period is reduced
            if self._auto_repeat_count > ((_AUTO_REPEAT_COUNT_THRES*_AUTO_REPEAT_MS) // self._auto_repeat_intervals[self.auto_repeat_level if speed_up else 0]):
                self._auto_repeat_count = 0
                if self.auto_repeat_level < (_AUTO_REPEAT_SPEED_LEVEL_MAX if speed_up else _AUTO_REPEAT_LEVEL_MAX):
                    self.auto_repeat_level += 1
                    if self.logging:
                        print(f"Auto Repeat Level: {self.auto_repeat_level}")

            return True
        return False


    def auto_repeat_clear(self):
        """Reset the auto-repeat counters and level. This should be called when a button is released to ensure that the next button press starts with the initial auto-repeat interval and level."""
        self._auto_repeat = 1+ self._auto_repeat_intervals[0] # so that we trigger immediately on next press

        self._auto_repeat_count = 0
        self.auto_repeat_level = 0



### MENU FUNCTIONALITY ###


    def set_menu(self, menu_name: str | None = "main"):  #: Literal["main"]): does it work without the type hint?
        """Set the current menu to the specified menu name, and construct the menu if necessary.
           If menu_name is None, it will clear the current menu and return to the previous state
           (e.g. from a submenu back to the main menu)."""
        if self.logging:
            print(f"B:Set Menu {menu_name}")
        if self.menu is not None:
            try:
                self.menu._cleanup()        # pylint: disable=protected-access
            except Exception:               # pylint: disable=broad-except
                # See badge-2024-software PR#168
                # in case badge s/w changes and this is done within the menu s/w
                # and then access to this function is removed
                pass
        self.current_menu = menu_name
        if menu_name == "main":
            # construct the main menu based on template
            menu_items = MAIN_MENU_ITEMS.copy()
            if not self.enable_hexpansion_mgr and MAIN_MENU_ITEMS[MENU_ITEM_HEXPANSION] in menu_items:
                menu_items.remove(MAIN_MENU_ITEMS[MENU_ITEM_HEXPANSION])
            if self._settings_mgr is None and MAIN_MENU_ITEMS[MENU_ITEM_SETTINGS] in menu_items:
                menu_items.remove(MAIN_MENU_ITEMS[MENU_ITEM_SETTINGS])
            if not self.enable_serialise_mgr and MAIN_MENU_ITEMS[MENU_ITEM_SERIALISE] in menu_items:
                menu_items.remove(MAIN_MENU_ITEMS[MENU_ITEM_SERIALISE])
            self.menu = Menu(
                    self,
                    menu_items,
                    select_handler=self._main_menu_select_handler,
                    back_handler=self._menu_back_handler,
                )
        elif menu_name == MAIN_MENU_ITEMS[MENU_ITEM_SETTINGS] and self._settings_mgr is not None: # "Settings"
            # construct the settings menu
            _settings_menu_items = ["SAVE ALL", "DEFAULT ALL"]
            for _, setting in enumerate(self.settings):
                _settings_menu_items.append(f"{setting}")
            self.menu = Menu(
                self,
                _settings_menu_items,
                select_handler=self._settings_menu_select_handler,
                back_handler=self._menu_back_handler,
                )


    # this appears to be able to be called at any time
    def _main_menu_select_handler(self, item: str, idx: int):
        if self.logging:
            print(f"H:Main Menu {item} at index {idx}")
        if item == MAIN_MENU_ITEMS[MENU_ITEM_HEXPANSION]: # Hexpansion Management
            if self._hexpansion_mgr is not None:
                self._hexpansion_mgr.logging = self.logging # update logging setting in hexpansion manager based on current app setting, in case it was changed
                if self._hexpansion_mgr.start():
                    self.current_state = STATE_HEXPANSION
        elif item == MAIN_MENU_ITEMS[MENU_ITEM_SERIALISE]:  # Serialise
            if self._serialise_mgr is not None:
                self._serialise_mgr.logging = self.logging # update logging setting in serialise manager based on current app setting, in case it was changed
                if self._serialise_mgr.start():
                    self.current_state = STATE_SERIALISE
        elif item == MAIN_MENU_ITEMS[MENU_ITEM_SETTINGS]:   # Settings
            self.set_menu(MAIN_MENU_ITEMS[MENU_ITEM_SETTINGS])
        elif item == MAIN_MENU_ITEMS[MENU_ITEM_ABOUT]:      # About
            self.set_menu(None)
            self.button_states.clear()
            # Show a message to the user about the current version of the app, and some basic instructions on how to use it, with a confirm button to acknowledge and return to the menu, and a cancel button to exit the app.
            self.show_message(["HexManager App",f"V{self.app_version}","By RobotMad"], msg_colours=[(1,1,1),(1,1,0),(0,1,1)], msg_type="info")
        elif item == MAIN_MENU_ITEMS[MENU_ITEM_EXIT]:       # Exit
            if self._hexpansion_mgr is not None:
                self._hexpansion_mgr.unregister_events()
            eventbus.remove(RequestForegroundPushEvent, self._gain_focus, self)
            eventbus.remove(RequestForegroundPopEvent, self._lose_focus, self)
            eventbus.emit(RequestStopAppEvent(self))


    def _settings_menu_select_handler(self, item: str, idx: int):
        if self.logging:
            print(f"B:Setting {item} @ {idx}")
        if idx == 0: #Save
            if self.logging:
                print("B:Settings Save All")
            settings.save()
            self.notification = Notification("  Settings  Saved")
            self.set_menu()
        elif idx == 1: #Default
            if self.logging:
                print("B:Settings Default All")
            for s in self.settings:
                self.settings[s].v = self.settings[s].d
                self.settings[s].persist()
            self.notification = Notification("  Settings Defaulted")
            self.set_menu()
        elif self._settings_mgr is not None and self._settings_mgr.start(item):
            self.current_state = STATE_SETTINGS


    def _menu_back_handler(self):
        if self.current_menu == "main":
            self.minimise()
        # for submenus, just return to the main menu
        self.set_menu()



def parse_version(version):
    """Parse a version string into a list of components for comparison.  Components are converted to integers where possible, to allow correct ordering (e.g. 1.10 > 1.2).  Pre-release and build metadata are ignored for simplicity, as they are not currently used."""
    #pre_components = ["final"]
    #build_components = ["0", "000000z"]
    #build = ""
    components = []
    if "+" in version:
        version, build = version.split("+", 1)          # pylint: disable=unused-variable
        #build_components = build.split(".")
    if "-" in version:
        version, pre_release = version.split("-", 1)    # pylint: disable=unused-variable
        #if pre_release.startswith("rc"):
        #    # Re-write rc as c, to support a1, b1, rc1, final ordering
        #    pre_release = pre_release[1:]
        #pre_components = pre_release.split(".")
    version = version.strip("v").split(".")
    components = [int(item) if item.isdigit() else item for item in version]
    #components.append([int(item) if item.isdigit() else item for item in pre_components])
    #components.append([int(item) if item.isdigit() else item for item in build_components])
    return components


__app_export__ = HexManagerApp
