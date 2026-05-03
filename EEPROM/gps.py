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
            raise ValueError("GPSApp config")

        self.config = config    # Enables HexManager to check which port app is associated with
        self.t = config.pin[1]
        self.x = config.pin[0]
        self.r = config.pin[2]
        self.f = False          # Whether the app is in the foreground or not, used to control when to read from the GPS and when to reset it.
        self.b = Buttons(self)
        self.l = None           # Last GPS fix as a string in the format "lat,lon" or None if no fix yet. Latitude and longitude are rounded to 5 decimal places which gives a precision of about 1 meter, more than enough for badgebot's purposes.
        self.u = UART(1, baudrate=9600, tx=self.t, rx=self.x)
        self.r.init(mode=Pin.OUT)
        self.r.value(1)
        self.z = 0              # Ticks since GPS reset, used to control when to release the GPS from reset after resetting it when the app is in the foreground and to prevent reading from the GPS for a short time after resetting it.
        self.y = 0              # Ticks since last GPS fix, used to control when to discard the last GPS fix after not getting a new one for a while.

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
        elif self.b.get(BUTTON_TYPES["CONFIRM"]):
            self.b.clear()
            eventbus.emit(RequestStopAppEvent(self))

        if self.r.value():
            self.z +=_d
            if self.z > 100:
                self.r.value(0)

        if not self.f:
            eventbus.emit(RequestForegroundPushEvent(self))
            self.f = True

        if self.l:
            self.y += _d
            if self.y > 10000:
                self.l = None


    def background_update(self, _d):
        """ Update the app state in the background - read GPS data """
        l = self.u.readline()
        if l:
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
                self.l = str(round(t, 5)) + "," + str(round(n, 5))#
                self.y = 0
            except (UnicodeError, ValueError, AttributeError):
                pass


    def draw(self, _c):
        _c.rgb(0, 0.2, 0).rectangle(-120, -120, 240, 240).fill()
        _c.rgb(0, 1, 0).move_to(-100, -10).text(self.l if self.l else "Search")
        button_labels(_c, confirm_label="Quit", cancel_label="Back")


__app_export__ = GPSApp     #pylint: disable=invalid-name
