# Discord Rich Presence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize real-time media playback state ("Now Watching") from local media players (MPV, VLC, PotPlayer, MPC-HC) to Discord Rich Presence using Simkl metadata.

**Architecture:** A lightweight, decoupled `DiscordRPCManager` communicates over local OS IPC pipes using `pypresence`. `MediaScrobbler` triggers state updates on play, pause, seek, and stop without extra network calls, formatting metadata into a streamlined Discord activity card with a single "View on Simkl" button.

**Tech Stack:** Python 3.10+, `pypresence`, `MediaScrobbler`, `config_manager`, `tray_base`, `pytest`.

**Spec:** [2026-10-05-discord-rich-presence-design.md](file:///c:/Users/Barba/Documents/Git/Media-Player-Scrobbler-for-Simkl/docs/superpowers/specs/2026-10-05-discord-rich-presence-design.md)

## Global Constraints
- Discord Application ID default: `"1556713709462880316"`.
- Configuration keys: `enable_discord_rpc` (boolean, default `True`), `discord_client_id` (string, default `"1556713709462880316"`).
- Zero polling timers against Simkl API.
- All code and comments in English.
- Tests located at root matching pattern `test_*.py`.

## Review Focus
1. **Discord Not Installed / Not Running**: `connect()` must fail silently without raising uncaught exceptions, spamming log warnings, or blocking media scrobbling.
2. **Discord Terminated Mid-Playback**: Pipe breaks during `update_presence()` must be caught gracefully and mark internal status disconnected for retry on next media state change.
3. **Missing Metadata Fields**: Missing duration, year, episode title, or poster URL must fall back cleanly without causing `KeyError` or malformed Discord activity payloads.
4. **Debounced Rapid State Changes**: Frequent pause/play toggles or rapid track switching must not violate Discord IPC rate limits (~1 update per 1-2 seconds).
5. **Clean Shutdown**: Quitting the application or stopping media playback must promptly clear the presence from the Discord profile.

---

### Task 1: Add `pypresence` Dependency and Implement `DiscordRPCManager`

**Files:**
- Modify: `pyproject.toml`
- Create: `simkl_mps/discord_rpc.py`
- Test: `test_discord_rpc.py`

**Interfaces:**
- Produces:
  - `class DiscordRPCManager(client_id: str = "1556713709462880316")`
  - `DiscordRPCManager.connect() -> bool`
  - `DiscordRPCManager.update_presence(title: str, year: int | None, media_type: str, season: int | None, episode: int | None, episode_title: str | None, current_position: float | None, total_duration: float | None, poster_url: str | None, simkl_id: int | str | None, is_paused: bool = False) -> bool`
  - `DiscordRPCManager.clear_presence() -> bool`
  - `DiscordRPCManager.close() -> None`

- [ ] **Step 1: Write failing unit tests in `test_discord_rpc.py`**

```python
import pytest
from unittest.mock import MagicMock, patch
from simkl_mps.discord_rpc import DiscordRPCManager

def test_format_payload_movie_playing():
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    payload = mgr._build_payload(
        title="Inception",
        year=2010,
        media_type="movie",
        season=None,
        episode=None,
        episode_title=None,
        current_position=60.0,
        total_duration=1200.0,
        poster_url="https://simkl.net/posters/test_m.jpg",
        simkl_id=472214,
        is_paused=False
    )
    assert payload["details"] == "Inception (2010)"
    assert payload["state"] == "Watching"
    assert "end" in payload["timestamps"]
    assert payload["large_image"] == "https://simkl.net/posters/test_m.jpg"
    assert payload["buttons"][0]["label"] == "View on Simkl"
    assert payload["buttons"][0]["url"] == "https://simkl.com/movies/472214"

def test_format_payload_tv_paused():
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    payload = mgr._build_payload(
        title="Succession",
        year=2018,
        media_type="show",
        season=2,
        episode=2,
        episode_title="Vaulter",
        current_position=500.0,
        total_duration=3600.0,
        poster_url=None,
        simkl_id=12345,
        is_paused=True
    )
    assert payload["details"] == "Succession (2018)"
    assert payload["state"] == "Paused · S02E02"
    assert "timestamps" not in payload or payload["timestamps"] is None
    assert payload["buttons"][0]["url"] == "https://simkl.com/tv/12345"

def test_connect_handles_discord_not_running():
    with patch("pypresence.Presence.connect", side_effect=Exception("Discord not found")):
        mgr = DiscordRPCManager(client_id="1556713709462880316")
        assert mgr.connect() is False
        assert mgr.is_connected is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test_discord_rpc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simkl_mps.discord_rpc'`.

- [ ] **Step 3: Add `pypresence` dependency and implement `simkl_mps/discord_rpc.py`**

- Add `pypresence = "^4.3.0"` to `pyproject.toml` dependencies.
- Run `poetry lock --no-update` and `poetry install`.
- Implement `DiscordRPCManager`:
  - Handle connection lifecycle with `pypresence.Presence`.
  - Implement `_build_payload()` handling movie vs show vs anime, playing vs paused, and timestamp calculation.
  - Implement `update_presence()`, `clear_presence()`, `close()`.
  - Include debounce (min 1.5s between `Presence.update` calls) and error trapping.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest test_discord_rpc.py -v`
Expected: PASS.

- [ ] **Step 5: Verify Review Focus failure modes**

Add test cases in `test_discord_rpc.py` for:
- Pipe break during `update_presence()` resetting connection state.
- Missing year, missing duration, and missing episode title fallbacks.

Run: `poetry run pytest test_discord_rpc.py -v`
Expected: PASS.

---

### Task 2: Add Configuration Settings for Discord RPC

**Files:**
- Modify: `simkl_mps/config_manager.py:20-60`
- Test: `test_config_scrobble_settings.py`

**Interfaces:**
- Consumes: `config_manager.get_setting`, `config_manager.save_setting`
- Produces:
  - Default `enable_discord_rpc = True`
  - Default `discord_client_id = "1556713709462880316"`

- [ ] **Step 1: Write failing test in `test_config_scrobble_settings.py`**

```python
def test_discord_rpc_settings_defaults():
    from simkl_mps.config_manager import get_setting
    assert get_setting("enable_discord_rpc", True) is True
    assert get_setting("discord_client_id", "1556713709462880316") == "1556713709462880316"
```

- [ ] **Step 2: Run test to verify**

Run: `poetry run pytest test_config_scrobble_settings.py -k test_discord_rpc -v`

- [ ] **Step 3: Update `simkl_mps/config_manager.py` with Discord settings defaults**

Add `"enable_discord_rpc": True` and `"discord_client_id": "1556713709462880316"` to default settings dictionary in `config_manager.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test_config_scrobble_settings.py -k test_discord_rpc -v`
Expected: PASS.

---

### Task 3: Integrate Discord RPC into `MediaScrobbler`

**Files:**
- Modify: `simkl_mps/media_scrobbler.py`
- Test: `test_media_scrobbler_discord.py`

**Interfaces:**
- Consumes: `DiscordRPCManager` from Task 1, `get_setting` from Task 2
- Produces:
  - `MediaScrobbler._sync_discord_presence()`
  - Hooks on state change: `PLAYING` → `update_presence`, `PAUSED` → `update_presence(is_paused=True)`, `STOPPED`/reset/shutdown → `clear_presence`.

- [ ] **Step 1: Write failing test in `test_media_scrobbler_discord.py`**

```python
import pytest
from unittest.mock import MagicMock, patch
from simkl_mps.media_scrobbler import MediaScrobbler
from simkl_mps.utils.constants import PLAYING, PAUSED, STOPPED

@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_syncs_discord_on_playing(mock_rpc_cls, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.movie_name = "Succession"
    scrobbler.media_type = "show"
    scrobbler.season = 2
    scrobbler.episode = 2
    scrobbler.simkl_id = 12345
    scrobbler.state = PLAYING
    scrobbler.current_position_seconds = 100
    scrobbler.total_duration_seconds = 3600

    scrobbler._sync_discord_presence()
    assert mock_rpc.update_presence.called
    kwargs = mock_rpc.update_presence.call_args[1]
    assert kwargs["title"] == "Succession"
    assert kwargs["is_paused"] is False

@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_clears_discord_on_stop(mock_rpc_cls, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.state = STOPPED
    scrobbler._sync_discord_presence()
    assert mock_rpc.clear_presence.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test_media_scrobbler_discord.py -v`
Expected: FAIL with `AttributeError: 'MediaScrobbler' object has no attribute '_sync_discord_presence'`.

- [ ] **Step 3: Implement `MediaScrobbler` Discord RPC integration**

- In `MediaScrobbler.__init__`:
  - Initialize `self.discord_rpc = DiscordRPCManager(client_id=get_setting("discord_client_id", "1556713709462880316"))`.
  - Initialize `self._discord_reported_state = None`.
- In `MediaScrobbler._sync_discord_presence()`:
  - Check `get_setting("enable_discord_rpc", True)`. If `False`, call `self.discord_rpc.clear_presence()` and return.
  - On `PLAYING`: resolve poster URL from `self.media_cache` (format `https://simkl.net/posters/{poster}_m.jpg` if only key present), call `self.discord_rpc.update_presence(...)`.
  - On `PAUSED`: call `self.discord_rpc.update_presence(..., is_paused=True)`.
  - On `STOPPED` or clear: call `self.discord_rpc.clear_presence()`.
- Hook `_sync_discord_presence()` in:
  - `_sync_scrobble_state()` / state loop
  - `reset_state()` / stop playback handler
  - `close()` / shutdown

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest test_media_scrobbler_discord.py -v`
Expected: PASS.

---

### Task 4: Add System Tray Toggle for Discord Rich Presence

**Files:**
- Modify: `simkl_mps/tray_base.py:1200-1350`
- Test: `test_tray_discord_rpc.py`

**Interfaces:**
- Consumes: `get_setting("enable_discord_rpc")`, `save_setting("enable_discord_rpc", val)`
- Produces:
  - Menu item: `"Discord Rich Presence"` with checkbox state.
  - Toggle handler: toggles setting, writes config, updates `media_scrobbler.discord_rpc`.

- [ ] **Step 1: Write failing test in `test_tray_discord_rpc.py`**

```python
import pytest
from unittest.mock import MagicMock, patch
from simkl_mps.config_manager import save_setting, get_setting

def test_toggle_discord_rpc_menu_action(tmp_path):
    # Test setting toggle behavior
    save_setting("enable_discord_rpc", True)
    assert get_setting("enable_discord_rpc", True) is True

    # Simulate toggle
    new_val = not get_setting("enable_discord_rpc", True)
    save_setting("enable_discord_rpc", new_val)
    assert get_setting("enable_discord_rpc", True) is False
```

- [ ] **Step 2: Add tray menu item in `simkl_mps/tray_base.py`**

- In `tray_base.py`:
  - Add `toggle_discord_rpc()` callback that flips `enable_discord_rpc`, updates config, and if disabled calls `scrobbler.discord_rpc.clear_presence()`.
  - Add `"Discord Rich Presence"` menu item with `checked=lambda item: get_setting('enable_discord_rpc', True)`.
  - Place it in settings / scrobble options section next to "Realtime Scrobbling (Watching Now)".

- [ ] **Step 3: Run tray tests to verify**

Run: `poetry run pytest test_tray_discord_rpc.py -v`
Expected: PASS.

---

### Task 5: Build Spec & PyInstaller Packaging Verification

**Files:**
- Modify: `simkl-mps.spec`
- Modify: `docs/todo.md` (check off Discord Rich Presence)

**Steps:**
- [ ] **Step 1: Verify `pypresence` in PyInstaller spec file**
  - Check `simkl-mps.spec` hiddenimports; add `'pypresence'` to `hiddenimports` if needed so PyInstaller packages it correctly on Windows/macOS/Linux.
- [ ] **Step 2: Run all existing tests to ensure zero regressions**
  - Run: `poetry run pytest`
  - Expected: ALL tests pass.
- [ ] **Step 3: Update `docs/todo.md`**
  - Mark Discord Rich Presence as completed in `docs/todo.md`.
