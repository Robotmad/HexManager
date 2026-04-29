import json
import sys
import tempfile

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
    """Verify that the HexDrive app_mpy_version recorded in hexpansions.json matches
    the VERSION constant in EEPROM/hexdrive.py.

    hexpansions.json is the authoritative record of which .mpy version should be
    programmed onto the EEPROM.  If someone bumps hexdrive.py VERSION without
    updating hexpansions.json (or vice-versa) this test will catch the mismatch.
    """
    import json
    import os
    from sim.apps.HexManager.EEPROM.hexdrive import VERSION as HEXDRIVE_VERSION

    json_path = os.path.join(os.path.dirname(__file__), "..", "hexpansions.json")
    with open(json_path) as f:
        data = json.load(f)

    hexdrive_entries = [h for h in data["hexpansions"]
                        if h.get("app_name") == "HexDriveApp" and h.get("app_mpy_version") is not None]
    assert hexdrive_entries, "No HexDriveApp entries with app_mpy_version found in hexpansions.json"
    for entry in hexdrive_entries:
        assert entry["app_mpy_version"] == HEXDRIVE_VERSION, (
            f"hexpansions.json entry pid={entry['pid']} has app_mpy_version="
            f"{entry['app_mpy_version']} but EEPROM/hexdrive.py VERSION={HEXDRIVE_VERSION}"
        )

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


# =====================================================================
#  HexpansionType hex-string constructor acceptance
# =====================================================================

class TestHexpansionTypeHexStrings:
    """Verify that HexpansionType accepts hex strings as well as plain ints
    for pid, vid, eeprom_total_size and eeprom_page_size.

    JSON has no hex-literal syntax, so callers sourcing configuration from
    JSON files must be able to pass quoted strings such as ``"0xCAFE"``.
    """

    def setup_method(self):
        from tests.conftest import _ensure_sim_initialized
        _ensure_sim_initialized()
        from sim.apps.HexManager.hexpansion_mgr import HexpansionType
        self.HexpansionType = HexpansionType

    def test_int_args_unchanged(self):
        """Sanity-check: plain int arguments still work."""
        ht = self.HexpansionType(0xCBCA, "HexDrive")
        assert ht.pid == 0xCBCA
        assert ht.vid == 0xCAFE  # default

    def test_hex_string_pid(self):
        ht = self.HexpansionType("0xCBCA", "HexDrive")
        assert ht.pid == 0xCBCA

    def test_hex_string_vid(self):
        ht = self.HexpansionType(0xCBCA, "HexDrive", vid="0xCAFE")
        assert ht.vid == 0xCAFE

    def test_hex_string_eeprom_total_size(self):
        ht = self.HexpansionType(0xCBCA, "HexDrive", eeprom_total_size="0x10000")
        assert ht.eeprom_total_size == 65536

    def test_hex_string_eeprom_page_size(self):
        ht = self.HexpansionType(0xCBCA, "HexDrive", eeprom_page_size="0x80")
        assert ht.eeprom_page_size == 128

    def test_decimal_string_pid(self):
        ht = self.HexpansionType("52170", "HexDrive")
        assert ht.pid == 0xCBCA

    def test_all_hex_strings(self):
        """All four numeric fields supplied as hex strings."""
        ht = self.HexpansionType("0xCBCA", "HexDrive", vid="0xCAFE",
                                 eeprom_total_size="0x2000", eeprom_page_size="0x20")
        assert ht.pid == 0xCBCA
        assert ht.vid == 0xCAFE
        assert ht.eeprom_total_size == 0x2000
        assert ht.eeprom_page_size == 0x20

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            self.HexpansionType("not_a_number", "HexDrive")


# =====================================================================
#  hexpansions.json loading with quoted hex PID / VID
# =====================================================================

def _write_temp_json(data: dict) -> str:
    """Write *data* as JSON to a named temp file and return its path.

    The caller is responsible for deleting the file after use.
    """
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


class TestLoadHexpansionTypesFromJson:
    """Tests for ``_load_hexpansion_types`` using a stable, injected JSON path.

    The production ``hexpansions.json`` evolves over time and is not suitable
    as a test fixture.  These tests write minimal temporary JSON files and pass
    their paths via the ``json_path`` override added to
    ``_load_hexpansion_types``, keeping the tests hermetic.
    """

    def setup_method(self):
        from tests.conftest import _ensure_sim_initialized
        _ensure_sim_initialized()
        from sim.apps.HexManager.app import _load_hexpansion_types
        self._load = _load_hexpansion_types

    def _load_from(self, hexpansions: list) -> list:
        """Helper: write a minimal JSON file and return the parsed types list."""
        path = _write_temp_json({"hexpansions": hexpansions})
        try:
            types, warnings = self._load("dummy/app.py", json_path=path)
        finally:
            import os
            os.unlink(path)
        return types, warnings

    # ------------------------------------------------------------------
    # Baseline: decimal integers (existing behaviour must still work)
    # ------------------------------------------------------------------

    def test_decimal_pid_and_vid(self):
        """Plain decimal integers are parsed correctly."""
        types, warnings = self._load_from([
            {"pid": 51966, "name": "TestHex", "vid": 51966}
        ])
        assert not warnings
        assert len(types) == 1
        assert types[0].pid == 0xCAFE
        assert types[0].vid == 0xCAFE

    def test_default_vid_used_when_omitted(self):
        """VID defaults to 0xCAFE when not specified."""
        types, warnings = self._load_from([{"pid": 1, "name": "NoVid"}])
        assert not warnings
        assert types[0].vid == 0xCAFE

    # ------------------------------------------------------------------
    # Quoted hex strings for PID
    # ------------------------------------------------------------------

    def test_quoted_hex_pid(self):
        """Quoted hex string PID is converted to the correct integer."""
        types, warnings = self._load_from([
            {"pid": "0xCBCA", "name": "HexDrive"}
        ])
        assert not warnings
        assert len(types) == 1
        assert types[0].pid == 0xCBCA

    def test_quoted_hex_pid_uppercase(self):
        """Uppercase quoted hex string PID is accepted."""
        types, warnings = self._load_from([
            {"pid": "0XCBCA", "name": "HexDrive"}
        ])
        assert not warnings
        assert types[0].pid == 0xCBCA

    # ------------------------------------------------------------------
    # Quoted hex strings for VID
    # ------------------------------------------------------------------

    def test_quoted_hex_vid(self):
        """Quoted hex string VID is converted to the correct integer."""
        types, warnings = self._load_from([
            {"pid": 1, "name": "TestHex", "vid": "0xCAFE"}
        ])
        assert not warnings
        assert types[0].vid == 0xCAFE

    def test_quoted_hex_vid_teamrobotmad(self):
        """TeamRobotmad VID as quoted hex string."""
        types, warnings = self._load_from([
            {"pid": "0xCBCB", "name": "HexDrive", "vid": "0xCBCB"}
        ])
        assert not warnings
        assert types[0].vid == 0xCBCB
        assert types[0].pid == 0xCBCB

    # ------------------------------------------------------------------
    # Quoted hex strings for EEPROM sizes
    # ------------------------------------------------------------------

    def test_quoted_hex_eeprom_sizes(self):
        """eeprom_total_size and eeprom_page_size accept quoted hex strings."""
        types, warnings = self._load_from([
            {"pid": 1, "name": "BigEEPROM",
             "eeprom_total_size": "0x10000", "eeprom_page_size": "0x80"}
        ])
        assert not warnings
        assert types[0].eeprom_total_size == 65536
        assert types[0].eeprom_page_size == 128

    # ------------------------------------------------------------------
    # Mixed: some fields hex strings, others plain ints
    # ------------------------------------------------------------------

    def test_mixed_hex_string_and_int(self):
        """A mix of quoted hex pid and plain int vid works correctly."""
        types, warnings = self._load_from([
            {"pid": "0xCBCA", "name": "HexDrive", "vid": 52171}
        ])
        assert not warnings
        assert types[0].pid == 0xCBCA
        assert types[0].vid == 52171

    # ------------------------------------------------------------------
    # Multiple entries, all with hex strings
    # ------------------------------------------------------------------

    def test_multiple_entries_all_hex_strings(self):
        """Multiple entries with quoted hex strings are all parsed correctly."""
        types, warnings = self._load_from([
            {"pid": "0xCBCA", "name": "HexDrive", "vid": "0xCAFE", "sub_type": "2 Motor"},
            {"pid": "0xCBCC", "name": "HexDrive", "vid": "0xCAFE", "sub_type": "4 Servo"},
        ])
        assert not warnings
        assert len(types) == 2
        assert types[0].pid == 0xCBCA
        assert types[1].pid == 0xCBCC

    # ------------------------------------------------------------------
    # Error handling: invalid string is skipped with a warning
    # ------------------------------------------------------------------

    def test_invalid_hex_string_entry_skipped(self):
        """An entry with an unparseable pid string is skipped; valid entries remain."""
        types, warnings = self._load_from([
            {"pid": "not_a_number", "name": "Bad"},
            {"pid": "0xCBCA", "name": "Good"},
        ])
        # The bad entry should be skipped; the good one should be present
        assert len(types) == 1
        assert types[0].pid == 0xCBCA

    # ------------------------------------------------------------------
    # Error handling: missing file
    # ------------------------------------------------------------------

    def test_missing_file_returns_warning(self):
        types, warnings = self._load("dummy/app.py",
                                     json_path="/nonexistent/path/hexpansions.json")
        assert types == []
        assert any("not found" in w for w in warnings)

    # ------------------------------------------------------------------
    # Error handling: malformed JSON
    # ------------------------------------------------------------------

    def test_malformed_json_returns_warning(self):
        import os
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        f.write("{this is not valid json}")
        f.close()
        try:
            types, warnings = self._load("dummy/app.py", json_path=f.name)
        finally:
            os.unlink(f.name)
        assert types == []
        assert any("parse error" in w for w in warnings)


# =====================================================================
#  app_mpy_version=None means "don't check version"
# =====================================================================

class TestAppMpyVersionNone:
    """When app_mpy_version is None, _check_hexpansion_app_on_port must treat
    any running app as current (APP_OK) rather than always flagging it as old.

    The test exercises the method directly, wiring up a minimal fake app
    instance and a HexpansionType whose app_mpy_version is None.
    """

    def setup_method(self):
        from tests.conftest import _ensure_sim_initialized
        _ensure_sim_initialized()
        from sim.apps.HexManager.hexpansion_mgr import (
            HexpansionMgr, HexpansionType,
            _HEXPANSION_STATE_RECOGNISED_APP_OK,
            _HEXPANSION_STATE_RECOGNISED_OLD_APP,
        )
        from sim.apps.HexManager import HexManagerApp
        self.HexpansionMgr = HexpansionMgr
        self.HexpansionType = HexpansionType
        self.APP_OK = _HEXPANSION_STATE_RECOGNISED_APP_OK
        self.OLD_APP = _HEXPANSION_STATE_RECOGNISED_OLD_APP
        self.app = HexManagerApp()

    def _make_mgr_with_fake_hexpansion_app(self, app_mpy_version, running_version):
        """Return a HexpansionMgr whose _find_hexpansion_app returns a stub
        reporting *running_version*, pointed at a HexpansionType with
        *app_mpy_version*.  Port 1 is used throughout.
        """
        from unittest.mock import patch

        class _FakeHexApp:
            def get_version(self):
                return running_version

        fake_app_instance = _FakeHexApp()
        hex_type = self.HexpansionType(pid=0xCBCA, name="TestHex",
                                       app_mpy_version=app_mpy_version,
                                       app_name="TestApp")
        self.app.HEXPANSION_TYPES = [hex_type]

        mgr = self.HexpansionMgr(self.app)
        # Patch _find_hexpansion_app so it returns our stub without needing
        # the scheduler or real hardware.
        with patch.object(mgr, "_find_hexpansion_app", return_value=fake_app_instance):
            mgr._check_hexpansion_app_on_port(1, 0)

        return mgr

    def test_none_version_not_checked_app_ok(self):
        """app_mpy_version=None → APP_OK regardless of running version."""
        mgr = self._make_mgr_with_fake_hexpansion_app(
            app_mpy_version=None, running_version=99)
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    def test_matching_version_is_app_ok(self):
        """When versions match, state must be APP_OK."""
        mgr = self._make_mgr_with_fake_hexpansion_app(
            app_mpy_version=7, running_version=7)
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    def test_mismatched_version_is_old_app(self):
        """When versions differ, state must be RECOGNISED_OLD_APP."""
        mgr = self._make_mgr_with_fake_hexpansion_app(
            app_mpy_version=7, running_version=6)
        assert mgr._hexpansion_state_by_slot[0] == self.OLD_APP
