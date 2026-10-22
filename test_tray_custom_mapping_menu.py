import pytest
from unittest.mock import MagicMock
from simkl_mps.tray_base import TrayAppBase

class DummyTray(TrayAppBase):
    def update_icon(self): pass
    def show_notification(self, title, msg): pass
    def _ask_custom_threshold_dialog(self, cur): return None
    def _ask_custom_min_watch_time_dialog(self, cur): return None
    def _ask_directory_filter_dialog(self, t, cur, h): return None
    def exit_app(self, _=None): pass
    def run(self): pass
    def show_about(self, _=None): pass
    def show_help(self, _=None): pass

def test_tray_menu_actions_exist():
    tray = DummyTray()
    assert hasattr(tray, "correct_current_media")
    assert hasattr(tray, "open_custom_mappings")

def test_correct_current_media_dispatches_dialog(monkeypatch):
    tray = DummyTray()
    mock_scrobbler = MagicMock()
    mock_scrobbler.current_filepath = "test.mkv"
    tray.scrobbler = MagicMock()
    tray.scrobbler.monitor.scrobbler = mock_scrobbler

    dialog_called = []
    def fake_show_dialog(*args, **kwargs):
        dialog_called.append(True)
    tray._show_correction_dialog = fake_show_dialog

    tray.correct_current_media()
    assert len(dialog_called) == 1

def test_correct_current_media_no_media_notifies():
    tray = DummyTray()
    notifications = []
    tray.show_notification = lambda title, msg: notifications.append((title, msg))
    mock_scrobbler = MagicMock()
    mock_scrobbler.current_filepath = None
    mock_scrobbler.currently_tracking = None
    mock_scrobbler.movie_name = None
    tray.scrobbler = MagicMock()
    tray.scrobbler.monitor.scrobbler = mock_scrobbler

    dialog_called = []
    tray._show_correction_dialog = lambda *a: dialog_called.append(True)

    tray.correct_current_media()
    assert len(dialog_called) == 0
    assert len(notifications) == 1
    assert "No active media playback found" in notifications[0][1]

