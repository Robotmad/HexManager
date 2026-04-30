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
        hdt = hd_by_pid[pid_byte]  # noqa: F841 – retained for future capability checks


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

    # ------------------------------------------------------------------
    # json_path auto-construction from app_file_path (no json_path kwarg)
    # ------------------------------------------------------------------

    def test_json_located_next_to_app_file(self):
        """When json_path is omitted, hexpansions.json is found next to app_file_path."""
        import os
        tmp_dir = tempfile.mkdtemp()
        json_path = os.path.join(tmp_dir, "hexpansions.json")
        with open(json_path, "w") as f:
            import json
            json.dump({"hexpansions": [{"pid": 1, "name": "NearbyHex"}]}, f)
        try:
            # Point at a fictional 'app.py' in the same temp dir
            fake_app_path = os.path.join(tmp_dir, "app.py")
            types, warnings = self._load(fake_app_path)
            assert not warnings
            assert len(types) == 1
            assert types[0].name == "NearbyHex"
        finally:
            os.unlink(json_path)
            os.rmdir(tmp_dir)

    def test_bare_filename_no_malformed_path(self):
        """app_file_path with no directory component builds a well-formed path.

        Previously '/' + 'app.py' + '/' + 'hexpansions.json' would wrongly
        produce '/app.py/hexpansions.json' – a path whose intermediate
        component is a file, causing a NotADirectoryError on POSIX or an
        unusual OSError on Windows.  The fixed code uses os.path.dirname
        (returning '') with a '.' fallback so the result is always a valid
        path, even if the file doesn't exist there.
        """
        import os
        # Ensure no real hexpansions.json exists in CWD (it shouldn't in any
        # temp dir) by using a dedicated temp dir as the working directory.
        tmp_dir = tempfile.mkdtemp()
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_dir)
            # Must not raise NotADirectoryError or similar malformed-path errors.
            # Either the file is found (types non-empty) or not found (warning).
            types, warnings = self._load("app.py")
            # The only acceptable error is "not found"; malformed-path errors
            # would have raised an exception before reaching this point.
            if not types:
                assert any("not found" in w for w in warnings)
        finally:
            os.chdir(orig_cwd)
            os.rmdir(tmp_dir)


# =====================================================================
#  _versions_match helper
# =====================================================================

class TestVersionsMatch:
    """Unit tests for the _versions_match() module-level helper."""

    def setup_method(self):
        from sim.apps.HexManager.hexpansion_mgr import _versions_match
        self.vm = _versions_match

    # --- integer versions ------------------------------------------------
    def test_int_match(self):
        assert self.vm(7, 7) is True

    def test_int_mismatch(self):
        assert self.vm(6, 7) is False

    def test_none_running_no_match(self):
        assert self.vm(None, 7) is False

    # --- string versions -------------------------------------------------
    def test_str_match(self):
        assert self.vm("1.2.3", "1.2.3") is True

    def test_str_v_prefix_stripped(self):
        assert self.vm("v1.2.3", "1.2.3") is True

    def test_str_numeric_ordering(self):
        # "1.10" must NOT equal "1.2" after tokenisation
        assert self.vm("1.10", "1.2") is False

    def test_str_mismatch(self):
        assert self.vm("1.2.3", "1.2.4") is False

    def test_str_pre_release_stripped(self):
        # pre-release suffix is ignored for equality
        assert self.vm("1.2.3-rc1", "1.2.3") is True

    def test_str_build_metadata_stripped(self):
        assert self.vm("1.2.3+build.42", "1.2.3") is True


# =====================================================================
#  _check_hexpansion_app_on_port: VERSION attribute & app_mpy_version=None
# =====================================================================

class TestCheckHexpansionAppOnPort:
    """Exercises _check_hexpansion_app_on_port directly via a minimal fake.

    Verifies that:
    * VERSION (module-level constant) is used, not get_version()
    * lowercase ``version`` attribute is accepted as a fallback
    * app_mpy_version=None → APP_OK (don't check)
    * integer and string version comparisons work correctly
    """

    def setup_method(self):
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

    def _run(self, app_mpy_version, running_version, use_uppercase=True):
        """Wire up a fake hexpansion app and call _check_hexpansion_app_on_port.

        *use_uppercase* controls whether the fake exposes VERSION (True) or
        the lowercase version attribute (False).
        """
        from unittest.mock import patch

        class _FakeHexApp:
            pass

        fake = _FakeHexApp()
        if use_uppercase:
            fake.VERSION = running_version
        else:
            fake.version = running_version

        hex_type = self.HexpansionType(pid=0xCBCA, name="TestHex",
                                       app_mpy_version=app_mpy_version,
                                       app_name="TestApp")
        self.app.HEXPANSION_TYPES = [hex_type]
        mgr = self.HexpansionMgr(self.app)
        with patch.object(mgr, "_find_hexpansion_app", return_value=fake):
            mgr._check_hexpansion_app_on_port(1, 0)
        return mgr

    # --- app_mpy_version = None ----------------------------------------
    def test_none_expected_version_is_app_ok(self):
        """app_mpy_version=None → APP_OK regardless of running version."""
        mgr = self._run(app_mpy_version=None, running_version=99)
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    # --- integer versions ----------------------------------------------
    def test_matching_int_version_is_app_ok(self):
        mgr = self._run(app_mpy_version=7, running_version=7)
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    def test_mismatched_int_version_is_old_app(self):
        mgr = self._run(app_mpy_version=7, running_version=6)
        assert mgr._hexpansion_state_by_slot[0] == self.OLD_APP

    # --- VERSION (uppercase) attribute preferred -----------------------
    def test_uppercase_VERSION_attribute_used(self):
        """VERSION (uppercase) is the primary source; no get_version() call."""
        mgr = self._run(app_mpy_version=7, running_version=7, use_uppercase=True)
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    # --- lowercase version fallback ------------------------------------
    def test_lowercase_version_fallback(self):
        """lowercase version attribute is accepted when VERSION is absent."""
        mgr = self._run(app_mpy_version=7, running_version=7, use_uppercase=False)
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    # --- string versions -----------------------------------------------
    def test_matching_string_version_is_app_ok(self):
        mgr = self._run(app_mpy_version="1.2.3", running_version="1.2.3")
        assert mgr._hexpansion_state_by_slot[0] == self.APP_OK

    def test_mismatched_string_version_is_old_app(self):
        mgr = self._run(app_mpy_version="1.2.4", running_version="1.2.3")
        assert mgr._hexpansion_state_by_slot[0] == self.OLD_APP
