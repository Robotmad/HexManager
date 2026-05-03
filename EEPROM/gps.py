# Minimal length method names to make the mpy file as small as possible so it will fit in the 2k hexpansion EEPROM.
# Minimal functionality to get a GPS fix and display it
#
import app
from app_components.tokens import button_labels
from events.input import Buttons, BUTTON_TYPES
from system.eventbus import eventbus
from system.scheduler.events import RequestForegroundPushEvent, RequestStopAppEvent
from machine import UART, Pin

class GPSApp(app.App):         # pylint: disable=no-member
    """ App to get GPS data from a GPS module connected to the hexpansion and display it on the badge. """
    VERSION = 1             # Increment this when making changes to the app that require the hexpansion app to be re-flashed with the new code.
    def __init__(self, config=None):
        super().__init__()
        if config is None:
            raise TypeError     # The app should not be run without a config as it won't work (shouldn't happen anyway if run from the hexpansion EEPROM)
        self.config = config    # Enables HexManager to check which port app is associated with
        self.t = config.pin[0]
        self.x = config.pin[1]
        self.r = config.pin[2]
        self.b = Buttons(self)
        self.l = None           # Last GPS fix as a string in the format "lat,lon" or None if no fix yet. Latitude and longitude are rounded to 5 decimal places which gives a precision of about 1 meter, more than enough for badgebot's purposes.
        self.u = UART(1, baudrate=9600, tx=self.t, rx=self.x)
        self.r.init(mode=Pin.OUT)
        self.r.value(1)
        self.z = -1             # Ticks timer - time since GPS reset, used to control when to release the GPS from reset after resetting it
                                # and then used to time how long since last valid GPS fix.
                                # also used as a flag (-1) to indicate that ForegroundPushEvent has not yet been emitted
        eventbus.on_async(RequestStopAppEvent, self.s, self)

    async def s(self, _e: RequestStopAppEvent):
        """ handle app stop """
        if _e.app == self:
            self.r.value(1)
            self.u.deinit()

    def update(self, _d):
        """ Update the app state - expire last_fix if it is too old """
        if self.b.get(BUTTON_TYPES["CANCEL"]):
            self.b.clear()
            self.minimise()

        if self.z < 0:
            eventbus.emit(RequestForegroundPushEvent(self))

        self.z +=_d

        if self.r.value():
            if self.z > 99:
                self.r.value(0)

        if self.l:
            if self.z > 9999:
                self.l = None

    def background_update(self, _d):
        """ Update the app state in the background - read GPS data """
        l = self.u.readline()
        if l:
            #print(l)
            try:
                p = l.decode().strip().split(',')
                if (p[0] != "$GPRMC" and p[0] != "$GNRMC") or p[2] != "A" or not p[3] or not p[5]:
                    return None
                t = float(p[3][:2]) + float(p[3][2:]) / 60
                n = float(p[5][:3]) + float(p[5][3:]) / 60
                if p[4] == "S":
                    t = -t
                if p[6] == "W":
                    n = -n
                self.l = str(round(t, 5))
                self.n = str(round(n, 5))
                self.z = 0
            except (UnicodeError, ValueError, AttributeError):
                pass

    def draw(self, _c):
        _c.font_size = 40   # not using defined sizes to save bytes in the mpy file
        _c.rgb(0, 0.2, 0).rectangle(-120, -120, 240, 240).fill()
        _c.rgb(0, 1, 0).move_to(-35, -50).text("GPS")
        if self.l:
            _c.move_to(-110,  0).text("Lat:" + self.l)
            _c.move_to(-110, 40).text("Lon:" + self.n)
        else:
            _c.move_to(-110,  0).text("Searching...")
        button_labels(_c, cancel_label="Back")

__app_export__ = GPSApp     #pylint: disable=invalid-name
