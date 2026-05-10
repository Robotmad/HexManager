import asyncio
from types import SimpleNamespace

import pytest


class FakeButtons:
    def __init__(self, button_types):
        self._button_types = button_types
        self._pressed = set()

    def press(self, *names: str):
        self._pressed = {self._button_types[name] for name in names}

    def get(self, button):
        return button in self._pressed

    def clear(self):
        self._pressed.clear()


class FakeProbeI2C:
    def __init__(self, total_size: int, page_size: int, addr_len: int, base_addr: int = 0x50):
        self.total_size = total_size
        self.page_size = page_size
        self.addr_len = addr_len
        self.base_addr = base_addr
        self.memory = bytearray([0xFF] * total_size)

    def _device_count(self) -> int:
        if self.addr_len == 1:
            return max(1, self.total_size // 256)
        return 1

    def _valid_addr(self, addr: int) -> bool:
        if self.addr_len == 1:
            return self.base_addr <= addr < self.base_addr + self._device_count()
        return addr == self.base_addr

    def _absolute_addr(self, addr: int, mem_addr: int) -> int:
        if not self._valid_addr(addr):
            raise OSError("no EEPROM")
        if self.addr_len == 1:
            return ((addr - self.base_addr) << 8) | mem_addr
        return mem_addr % self.total_size

    def scan(self):
        return list(range(self.base_addr, self.base_addr + self._device_count()))

    def writeto(self, addr, data):
        if not self._valid_addr(addr):
            raise OSError("no EEPROM")
        return len(data)

    def writeto_mem(self, addr, mem_addr, data, addrsize=16):     # pylint: disable=unused-argument
        absolute_addr = self._absolute_addr(addr, mem_addr)
        page_base = absolute_addr - (absolute_addr % self.page_size)
        page_offset = absolute_addr % self.page_size
        for index, value in enumerate(data):
            target = page_base + ((page_offset + index) % self.page_size)
            if target < self.total_size:
                self.memory[target] = value
        return len(data)

    def readfrom_mem(self, addr, mem_addr, length, addrsize=16):      # pylint: disable=unused-argument
        absolute_addr = self._absolute_addr(addr, mem_addr)
        return bytes(self.memory[(absolute_addr + index) % self.total_size] for index in range(length))


@pytest.fixture
def serialise_app(hexmanager_app):
    from events.input import BUTTON_TYPES
    from sim.apps.HexManager.app import STATE_SERIALISE

    app = hexmanager_app
    app.button_states = FakeButtons(BUTTON_TYPES)
    assert app._serialise_mgr.start()
    app.current_state = STATE_SERIALISE

    yield app

    app._serialise_mgr.unregister_events()
    app.serialise_active = False


def test_serialise_programmes_blank_board_and_increments_id(serialise_app, monkeypatch):
    from sim.apps.HexManager import serialise_mgr as serialise_module
    from sim.apps.HexManager.serialise_mgr import _SUB_DONE, _SUB_PROGRAMMING, _SUB_SUMMARY, _SUB_WAITING

    app = serialise_app
    mgr = app._serialise_mgr
    helper = app._hexpansion_mgr
    start_id = app.settings['unique_id'].v
    calls = {}
    save_calls = []
    emitted_events = []

    def fake_prepare(port, type_index, unique_id):
        calls['prepare'] = (port, type_index, unique_id)
        return True

    def fake_program(port, type_index):
        calls['program'] = (port, type_index)
        return 1

    monkeypatch.setattr(helper, 'probe_eeprom', lambda port: (helper.HEXPANSION_STATE_BLANK, None))
    monkeypatch.setattr(helper, 'prepare_eeprom_for_type', fake_prepare)
    monkeypatch.setattr(helper, 'program_app_for_type', fake_program)
    monkeypatch.setattr(serialise_module.settings, 'save', lambda: save_calls.append(True))
    monkeypatch.setattr(serialise_module.eventbus, 'emit', lambda event: emitted_events.append(event))

    app.button_states.press('CONFIRM')
    app.update(100)
    assert mgr._sub_state == _SUB_WAITING

    mgr._pending_port = 2
    app.update(100)
    assert mgr._sub_state == _SUB_SUMMARY
    assert mgr._active_port == 2

    app.button_states.press('CONFIRM')
    app.update(100)
    assert mgr._sub_state == _SUB_PROGRAMMING

    app.update(100)
    assert mgr._sub_state == _SUB_PROGRAMMING

    app.update(100)
    assert mgr._sub_state == _SUB_DONE
    assert calls['prepare'] == (2, mgr._selected_type_index, start_id)
    assert calls['program'] == (2, mgr._selected_type_index)
    assert app.settings['unique_id'].v == start_id + 1
    assert len(save_calls) == 1
    assert len(emitted_events) == 1
    assert emitted_events[0].port == 2
    assert emitted_events[0].__class__.__name__ == 'HexpansionInsertionEvent'

    mgr._removed_port = 2
    app.update(100)
    assert mgr._sub_state == _SUB_WAITING


def test_serialise_requires_erase_for_written_eeprom(serialise_app, monkeypatch):
    from sim.apps.HexManager.serialise_mgr import _SUB_ERASE, _SUB_ERASE_CONFIRM, _SUB_SUMMARY

    app = serialise_app
    mgr = app._serialise_mgr
    helper = app._hexpansion_mgr
    erase_calls = []

    monkeypatch.setattr(helper, 'probe_eeprom', lambda port: (helper.HEXPANSION_STATE_UNRECOGNISED, object()))
    monkeypatch.setattr(helper, 'erase_eeprom_for_type', lambda port, type_index: erase_calls.append((port, type_index)) or True)

    app.button_states.press('CONFIRM')
    app.update(100)

    mgr._pending_port = 3
    app.update(100)
    assert mgr._sub_state == _SUB_ERASE_CONFIRM
    assert mgr._active_port == 3

    app.button_states.press('CONFIRM')
    app.update(100)
    assert mgr._sub_state == _SUB_ERASE

    app.update(100)
    assert mgr._sub_state == _SUB_ERASE

    app.update(100)
    assert mgr._sub_state == _SUB_SUMMARY
    assert erase_calls == [(3, mgr._selected_type_index)]


def test_serialise_failure_returns_via_serialise_message(serialise_app, monkeypatch):
    from sim.apps.HexManager.app import STATE_MESSAGE, STATE_SERIALISE
    from sim.apps.HexManager.serialise_mgr import _SUB_WAITING

    app = serialise_app
    mgr = app._serialise_mgr
    helper = app._hexpansion_mgr

    monkeypatch.setattr(helper, 'probe_eeprom', lambda port: (helper.HEXPANSION_STATE_BLANK, None))
    monkeypatch.setattr(helper, 'prepare_eeprom_for_type', lambda port, type_index, unique_id: True)
    monkeypatch.setattr(helper, 'program_app_for_type', lambda port, type_index: -1)

    app.button_states.press('CONFIRM')
    app.update(100)

    mgr._pending_port = 4
    app.update(100)

    app.button_states.press('CONFIRM')
    app.update(100)
    app.update(100)
    app.update(100)

    assert app.current_state == STATE_MESSAGE
    assert app.message_type == 'serialise'
    assert mgr._sub_state == _SUB_WAITING

    app.button_states.press('CONFIRM')
    app.update(100)
    assert app.current_state == STATE_SERIALISE

    app.update(100)
    assert mgr._sub_state == _SUB_WAITING


def test_serialise_exit_refreshes_hexpansion_records(serialise_app, monkeypatch):
    from sim.apps.HexManager.app import STATE_MENU
    from sim.apps.HexManager.serialise_mgr import _SUB_DONE

    app = serialise_app
    mgr = app._serialise_mgr
    helper = app._hexpansion_mgr
    refresh_calls = []

    monkeypatch.setattr(helper, 'refresh_slot_records', lambda: refresh_calls.append(True))

    mgr._sub_state = _SUB_DONE
    mgr._active_port = 2

    app.button_states.press('CANCEL')
    app.update(100)

    assert refresh_calls == [True]
    assert app.serialise_active is False
    assert app.hexpansion_update_required is False
    assert app.current_state == STATE_MENU


def test_refresh_slot_records_rescans_all_slots(hexmanager_app, monkeypatch):
    from sim.apps.HexManager.hexpansion_mgr import HexpansionMgr, _NUM_HEXPANSION_SLOTS

    app = hexmanager_app
    helper = app._hexpansion_mgr
    checked_ports = []
    header_ports = []

    helper._ports_to_initialise.update({1, 2})
    helper._ports_to_check_app.update({3})
    helper._detected_port = 1
    helper._waiting_app_port = 2
    helper._erase_port = 3
    helper._upgrade_port = 4
    helper._port_selected = 5
    helper._hexpansion_type_by_slot = [0] * _NUM_HEXPANSION_SLOTS
    helper._hexpansion_state_by_slot = [1] * _NUM_HEXPANSION_SLOTS
    helper._hexpansion_eeprom_addr_len = [1] * _NUM_HEXPANSION_SLOTS
    helper._hexpansion_eeprom_addr = [0x50] * _NUM_HEXPANSION_SLOTS
    helper._hexpansion_eeprom_total_size = [2048] * _NUM_HEXPANSION_SLOTS
    helper._hexpansion_eeprom_page_size = [16] * _NUM_HEXPANSION_SLOTS

    monkeypatch.setattr(helper, '_check_port_for_known_hexpansions', lambda port: checked_ports.append(port) or False)
    monkeypatch.setattr(helper, '_read_port_header', lambda port: header_ports.append(port))

    helper.refresh_slot_records()

    assert checked_ports == list(range(1, _NUM_HEXPANSION_SLOTS + 1))
    assert header_ports == [5]
    assert helper._ports_to_initialise == set()
    assert helper._ports_to_check_app == set()
    assert helper._detected_port is None
    assert helper._waiting_app_port is None
    assert helper._erase_port is None
    assert helper._upgrade_port is None
    assert helper._hexpansion_type_by_slot == [None] * _NUM_HEXPANSION_SLOTS
    assert helper._hexpansion_state_by_slot == [HexpansionMgr.HEXPANSION_STATE_UNKNOWN] * _NUM_HEXPANSION_SLOTS
    assert helper._hexpansion_eeprom_addr_len == [None] * _NUM_HEXPANSION_SLOTS
    assert helper._hexpansion_eeprom_addr == [None] * _NUM_HEXPANSION_SLOTS
    assert helper._hexpansion_eeprom_total_size == [None] * _NUM_HEXPANSION_SLOTS
    assert helper._hexpansion_eeprom_page_size == [None] * _NUM_HEXPANSION_SLOTS


@pytest.mark.parametrize(("total_size", "page_size", "addr_len"), [(2048, 16, 1), (32768, 64, 2)])
def test_detect_eeprom_geometry_restores_blank_chip(hexmanager_app, monkeypatch, total_size, page_size, addr_len):
    from sim.apps.HexManager import hexpansion_mgr as hexpansion_module

    helper = hexmanager_app._hexpansion_mgr
    fake_i2c = FakeProbeI2C(total_size=total_size, page_size=page_size, addr_len=addr_len)
    helper._hexpansion_eeprom_addr_len[0] = addr_len
    helper._hexpansion_eeprom_addr[0] = 0x50

    monkeypatch.setattr(hexpansion_module, 'I2C', lambda port: fake_i2c)

    assert helper._detect_eeprom_geometry(1) == (total_size, page_size)
    assert helper._hexpansion_eeprom_total_size[0] == total_size
    assert helper._hexpansion_eeprom_page_size[0] == page_size
    assert fake_i2c.memory == bytearray([0xFF] * total_size)


def test_prepare_eeprom_uses_detected_geometry_for_header(hexmanager_app, monkeypatch):
    from types import SimpleNamespace

    from sim.apps.HexManager import hexpansion_mgr as hexpansion_module

    helper = hexmanager_app._hexpansion_mgr
    helper._hexpansion_eeprom_addr_len[0] = 2
    helper._hexpansion_eeprom_addr[0] = 0x50
    captured = {}

    monkeypatch.setattr(hexpansion_module, 'I2C', lambda port: object())
    monkeypatch.setattr(helper, '_detect_eeprom_geometry', lambda port, force=False: (32768, 64))
    monkeypatch.setattr(hexpansion_module, 'write_header', lambda port, header, addr=None, addr_len=None, page_size=None: captured.update({'header': header, 'addr': addr, 'addr_len': addr_len, 'page_size': page_size}))
    monkeypatch.setattr(helper, '_read_header', lambda port, i2c=None: captured['header'])
    monkeypatch.setattr(hexpansion_module, 'get_hexpansion_block_devices', lambda i2c, header, addr, addr_len=None: (None, object()))
    monkeypatch.setattr(hexpansion_module.vfs, 'VfsLfs2', SimpleNamespace(mkfs=lambda partition: None), raising=False)
    monkeypatch.setattr(hexpansion_module.vfs, 'mount', lambda partition, mountpoint, readonly=False: None, raising=False)

    assert helper._prepare_eeprom(1, type_index=0, unique_id=123)
    assert captured['header'].eeprom_total_size == 32768
    assert captured['header'].eeprom_page_size == 64
    assert captured['header'].fs_offset == 64
    assert captured['page_size'] == 64


def test_blank_port_scan_button_and_geometry_details(hexmanager_app, monkeypatch):
    from events.input import BUTTON_TYPES
    from sim.apps.HexManager import hexpansion_mgr as hexpansion_module
    from sim.apps.HexManager.hexpansion_mgr import _SUB_PORT_SELECT, _SUB_SCANNING

    app = hexmanager_app
    helper = app._hexpansion_mgr
    app.button_states = FakeButtons(BUTTON_TYPES)
    helper._sub_state = _SUB_PORT_SELECT
    helper._port_selected = 1
    helper._hexpansion_state_by_slot[0] = helper.HEXPANSION_STATE_BLANK
    helper._update_detail_page_count()

    rendered = {}
    labels = {}

    monkeypatch.setattr(app, 'draw_message', lambda ctx, lines, colours, font: rendered.update({'lines': list(lines)}))
    monkeypatch.setattr(hexpansion_module, 'button_labels', lambda ctx, **kwargs: labels.update(kwargs))

    helper._draw_port_select(None)
    assert 'Size: Unknown' in rendered['lines']
    assert 'Page: Unknown' in rendered['lines']
    assert labels['down_label'] == 'Scan'
    assert labels['right_label'] == 'Slot>'

    scan_calls = []

    def fake_detect(port, force=False):
        scan_calls.append((port, force))
        helper._hexpansion_eeprom_total_size[port - 1] = 8192
        helper._hexpansion_eeprom_page_size[port - 1] = 32
        return 8192, 32

    monkeypatch.setattr(helper, '_detect_eeprom_geometry', fake_detect)
    monkeypatch.setattr(helper, '_read_port_header', lambda port: None)

    app.button_states.press('DOWN')
    helper._update_state_port_select(0)

    assert helper._sub_state == _SUB_SCANNING
    assert helper._scan_port == 1
    assert helper._port_selected == 1

    rendered.clear()
    helper.draw(None)
    assert 'Scanning...' in rendered['lines']

    helper._update_state_scanning(0)

    assert scan_calls == [(1, False)]
    assert helper._sub_state == _SUB_PORT_SELECT
    assert helper._scan_port is None
    assert helper._port_selected == 1

    rendered.clear()
    labels.clear()
    helper._draw_port_select(None)
    assert 'Size: 8192 Bytes' in rendered['lines']
    assert 'Page: 32 Bytes' in rendered['lines']
    assert labels['right_label'] == 'Slot>'


def test_right_button_keeps_slot_navigation_when_blank_port_can_scan(hexmanager_app):
    from events.input import BUTTON_TYPES
    from sim.apps.HexManager.hexpansion_mgr import _SUB_PORT_SELECT

    app = hexmanager_app
    helper = app._hexpansion_mgr
    app.button_states = FakeButtons(BUTTON_TYPES)
    helper._sub_state = _SUB_PORT_SELECT
    helper._port_selected = 1
    helper._hexpansion_state_by_slot[0] = helper.HEXPANSION_STATE_BLANK
    helper._update_detail_page_count()

    app.button_states.press('RIGHT')
    helper._update_state_port_select(0)

    assert helper._port_selected == 2
    assert helper._sub_state == _SUB_PORT_SELECT


def test_declined_initialise_is_not_reprompted_during_init_rescan(hexmanager_app, monkeypatch):
    from events.input import BUTTON_TYPES
    from sim.apps.HexManager.hexpansion_mgr import _MODE_INIT, _SUB_DETECTED, _SUB_PORT_SELECT

    app = hexmanager_app
    helper = app._hexpansion_mgr
    app.button_states = FakeButtons(BUTTON_TYPES)
    helper._mode = _MODE_INIT
    helper._sub_state = _SUB_DETECTED
    helper._detected_port = 3
    helper._hexpansion_state_by_slot[2] = helper.HEXPANSION_STATE_BLANK

    app.button_states.press('CANCEL')
    helper._update_state_detected(0)

    assert helper._detected_port is None
    assert 3 in helper._ports_initialise_declined

    def raise_blank(port, i2c=None):
        raise RuntimeError('blank eeprom')

    monkeypatch.setattr(helper, '_read_header', raise_blank)
    helper._ports_to_initialise.clear()
    helper._check_port_for_known_hexpansions(3)

    assert 3 not in helper._ports_to_initialise

    helper._mode = 3
    helper._sub_state = _SUB_PORT_SELECT
    helper._port_selected = 3
    app.button_states.press('CONFIRM')
    helper._update_state_port_select(0)

    assert helper._detected_port == 3
    assert helper._sub_state == _SUB_DETECTED


def test_hexpansion_events_are_suppressed_while_serialise_active(hexmanager_app, monkeypatch):
    app = hexmanager_app
    helper = app._hexpansion_mgr
    called = {'check': False}

    def fail_if_called(port):
        called['check'] = True
        raise AssertionError(f'_check_port_for_known_hexpansions should not run for port {port}')

    app.serialise_active = True
    app.hexpansion_update_required = False
    monkeypatch.setattr(helper, '_check_port_for_known_hexpansions', fail_if_called)

    asyncio.run(helper._handle_insertion(SimpleNamespace(port=1)))

    assert called['check'] is False
    assert app.hexpansion_update_required is False
