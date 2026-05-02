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
