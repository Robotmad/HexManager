import sys

import pytest

# Add badge software to pythonpath
sys.path.append("../../../") 

import sim.run
from system.hexpansion.config import HexpansionConfig


def test_import_hexmanager_app_and_app_export():
    import sim.apps.HexManager.app as HexManager
    from sim.apps.HexManager import HexManagerApp
    assert HexManager.__app_export__ == HexManagerApp

def test_import_hexdrive_app_and_app_export():
    import sim.apps.HexManager.EEPROM.hexdrive as HexDrive
    from sim.apps.HexManager.EEPROM.hexdrive import HexDriveApp
    assert HexDrive.__app_export__ == HexDriveApp

def test_hexmanager_app_init():
    from sim.apps.HexManager import HexManagerApp
    HexManagerApp()

def test_hexdrive_app_init(port):
    from sim.apps.HexManager.EEPROM.hexdrive import HexDriveApp
    config = HexpansionConfig(port)
    HexDriveApp(config)

def test_app_versions_match():
    import sim.apps.HexManager.app as HexManager
    import sim.apps.HexManager.EEPROM.hexdrive as HexDrive
    assert HexManager.HEXDRIVE_APP_VERSION == HexDrive.VERSION
    # above test should always pass since HexManager.HEXDRIVE_APP_VERSION is imported from HexDrive.VERSION, but this test will at least catch if someone accidentally changes one without the other. 

def test_hexdrive_type_pids_consistent():
    """Verify HexDriveType PIDs in hexdrive.py are consistent with HexpansionType PIDs in app.py.

    HexDriveType stores a single PID byte (low byte), while HexpansionType
    stores the full 16-bit PID.  For every HexDrive-flavour HexpansionType
    the low byte of its PID must match exactly one HexDriveType entry, and
    the motor/servo capability counts must agree.
    """
    from sim.apps.HexManager import HexManagerApp
    from sim.apps.HexManager.EEPROM.hexdrive import _HEXDRIVE_TYPES

    app_instance = HexManagerApp()
    hexdrive_hexpansion_types = [
        ht for ht in app_instance.HEXPANSION_TYPES if ht.name == "HexDrive"
    ]

    # Build a lookup from PID byte -> HexDriveType
    # Also verify that PID bytes are unique within _HEXDRIVE_TYPES
    hd_by_pid = {}
    for hdt in _HEXDRIVE_TYPES:
        assert hdt.pid not in hd_by_pid, (
            f"Duplicate HexDriveType PID byte 0x{hdt.pid:02X}: "
            f"'{hd_by_pid[hdt.pid].name}' and '{hdt.name}'"
        )
        hd_by_pid[hdt.pid] = hdt

    for ht in hexdrive_hexpansion_types:
        pid_byte = ht.pid & 0xFF
        assert pid_byte in hd_by_pid, (
            f"HexpansionType PID 0x{ht.pid:04X} low byte 0x{pid_byte:02X} "
            f"has no matching HexDriveType"
        )
        hdt = hd_by_pid[pid_byte]
        assert ht.motors == hdt.motors, (
            f"Motor count mismatch for PID 0x{pid_byte:02X}: "
            f"HexpansionType={ht.motors}, HexDriveType={hdt.motors}"
        )
        assert ht.servos == hdt.servos, (
            f"Servo count mismatch for PID 0x{pid_byte:02X}: "
            f"HexpansionType={ht.servos}, HexDriveType={hdt.servos}"
        )

