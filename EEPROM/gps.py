"""
GPS Hexpansion firmware (minimal) for the Tildagon badge.

Kept deliberately small to fit the tiny (2 KB) M24C16 EEPROM: it parses RMC for
position/speed/bearing (and emits the unchanged GPSEvent, so the emf-speedometer
app keeps working), and buffers the recent raw NMEA sentences so apps can parse
whatever else they need (GGA/GSV/GSA for altitude, satellite counts, sky maps)
themselves, on the badge where there is plenty of space.

D1 (Green/White) lit when valid fix obtained.

Based on the GPS firmware from https://github.com/mbooth101/emf-speedometer
License: MIT
"""
import app
import asyncio
import time

from events import Event
from system.eventbus import eventbus
from machine import UART, Pin


class GPSApp(app.App):
    """Provides a GPS API for apps to use directly and GPS Events to subscribe to."""

    # Increment when the firmware changes in a way that needs a re-flash.
    VERSION = 3

    class GPSEvent(Event):
        def __init__(self, position, speed, bearing):
            self.position = position
            self.speed = speed
            self.bearing = bearing

        def __str__(self):
            return f"GPS fix {self.position}, speed {self.speed} knots, bearing {self.bearing}"

    def __init__(self, config=None):
        super().__init__()
        if config is None:
            raise TypeError
        self.config = config

        self._position = None
        self._bearing = 0.0
        self._speed = 0.0

        # Ring buffer of recent raw NMEA sentences (checksum stripped)
        self._lines = []

        self.to = 10
        self.uart = UART(1, baudrate=9600, tx=config.pin[0], rx=config.pin[1], timeout=self.to)

        self.r = config.pin[2]
        self.r.init(mode=Pin.OUT)
        self.r.value(1)

        self.l = config.ls_pin[2]
        self.l.init(mode=Pin.OUT)
        self.l.value(0) # D1 LED off

        self.z = 0

    # Special function called by the BadgeOS to allow the app to clean up resources before it is removed from memory.
    # See https://github.com/emfcamp/badge-2024-software/pull/328
    def deinit(self):
        """release the UART."""
        self.uart.deinit()

    @property
    def position(self):
        return self._position

    @property
    def bearing(self):
        return self._bearing

    @property
    def speed(self):
        return round(self._speed, 2)

    @property
    def sentences(self):
        """Recent raw NMEA sentences (checksum stripped) for apps to parse."""
        return list(self._lines)

    async def background_task(self):
        last = time.ticks_ms()
        while True:
            start = time.ticks_ms()
            delta = time.ticks_diff(start, last)
            result = self.background_update(delta)
            await asyncio.sleep_ms(25 if result else 250 - self.to)
            last = start

    def background_update(self, delta):
        self.z += delta

        if self.r.value():
            if self.z > 99:
                self.r.value(0)

        if self._position and self.z > 9999:
            self._position = None
            self._speed = 0
            self.l.value(0) # D1 LED off

        l = self.uart.readline()
        if not l:
            return False
        try:
            line = l.decode().strip().split('*')[0]
            self._lines.append(line)
            if len(self._lines) > 40:
                self._lines = self._lines[-40:]

            p = line.split(',')
            if p[0][3:] == "RMC":
                if p[2] == "A":
                    lat = float(p[3][:2]) + float(p[3][2:]) / 60
                    lon = float(p[5][:3]) + float(p[5][3:]) / 60
                    if p[4] == "S":
                        lat = -lat
                    if p[6] == "W":
                        lon = -lon
                    self._position = (round(lat, 5), round(lon, 5))
                    self._speed = float(p[7]) if p[7] else 0.0
                    if p[8]:
                        self._bearing = float(p[8])
                    if self._speed < 1:
                        self._speed = 0
                    self.z = 0
                    self.l.value(1) # D1 LED on
                eventbus.emit(self.GPSEvent(self._position, self._speed, self._bearing))
        except: # removed to save code space (UnicodeError, ValueError, AttributeError, IndexError):
            pass
        return True

__app_export__ = GPSApp # pylint: disable=invalid-name
