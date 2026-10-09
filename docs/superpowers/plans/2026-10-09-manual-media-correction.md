# Manual Media Correction & Persistent Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a user-facing manual media correction mechanism with persistent two-tier mapping (`custom_mappings.json`) and runtime live swap when automatic identification fails or misidentifies media.

**Architecture:** A standalone `CustomMappingManager` handles persistent exact-file and show-level rules; `MediaScrobbler` checks this manager with top priority and supports live-swapping active playback sessions; a pure Tkinter `CorrectionDialog` provides URL parsing, ID resolution, and keyword search candidates without third-party GUI dependencies, integrated into the system tray menu.

**Tech Stack:** Python 3.10+, Tkinter, requests, pystray, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-manual-media-correction-design.md`

## Global Constraints

- Use English for code, identifiers, and comments.
- Zero external UI dependencies; all dialogs must use standard library `tkinter`.
- Strict isolation of `custom_mappings.json` from `media_cache.json` (clearing cache must never delete custom rules).
- Live swap must prevent Simkl watch history corruption by deleting mismatched pending playbacks (`DELETE /sync/playback`).
- All background API queries in Tkinter dialog must run on daemon threads and dispatch updates via `root.after()`.

## Review Focus

1. **Malformatted or missing `custom_mappings.json`**: App must handle syntax errors by backing up to `.corrupted` and initializing safely without crashing.
2. **Offline correction saving**: User must be able to input a known numerical Simkl ID and save rules even without internet connectivity.
3. **Movie vs TV/Anime mode switching**: Selecting a movie must hide or disable Season/Episode controls to prevent invalid payloads.
4. **Active scrobble live swap race condition**: When a correction is applied while playback is active, old scrobble timers and reported states must reset before starting the new session.
5. **Exact file match priority**: An exact file mapping must always take precedence over a generalized series directory rule.

---

### Task 1: Core CustomMappingManager (`simkl_mps/custom_mapping_manager.py`)

**Files:**
- Create: `simkl_mps/custom_mapping_manager.py`
- Create: `tests/test_custom_mapping_manager.py`

**Interfaces:**
- Produces:
  ```python
  class CustomMappingManager:
      def __init__(self, app_data_dir: Path, filename: str = "custom_mappings.json"): ...
      def resolve(self, filepath: str | None, raw_title: str | None = None, guessit_info: dict | None = None) -> dict | None: ...
      def add_exact_mapping(self, filename_or_path: str, simkl_id: int, media_type: str, title: str, season: int | None = None, episode: int | None = None, poster_url: str | None = None, year: int | None = None) -> dict: ...
      def add_show_rule(self, match_key: str, simkl_id: int, media_type: str, title: str, default_season: int = 1, folder_keyword: str | None = None, poster_url: str | None = None) -> dict: ...
      def remove_exact_mapping(self, filename_or_path: str) -> bool: ...
      def remove_show_rule(self, match_key: str) -> bool: ...
      def get_all(self) -> dict: ...
      def clear(self) -> None: ...
  ```

- [ ] **Step 1: Write the failing tests for CustomMappingManager**

In `tests/test_custom_mapping_manager.py`:
```python
import pytest
from pathlib import Path
from simkl_mps.custom_mapping_manager import CustomMappingManager

def test_exact_mapping_add_and_resolve(tmp_path: Path):
    manager = CustomMappingManager(tmp_path)
    manager.add_exact_mapping(
        filename_or_path="dune.part.two.2024.1080p.mkv",
        simkl_id=1690042,
        media_type="movie",
        title="Dune: Part Two",
        year=2024
    )
    result = manager.resolve("D:/Movies/dune.part.two.2024.1080p.mkv")
    assert result is not None
    assert result["simkl_id"] == 1690042
    assert result["type"] == "movie"
    assert result["title"] == "Dune: Part Two"

def test_show_rule_resolution_and_episode_extraction(tmp_path: Path):
    manager = CustomMappingManager(tmp_path)
    manager.add_show_rule(
        match_key="frieren",
        simkl_id=2095944,
        media_type="anime",
        title="Frieren: Beyond Journey's End",
        default_season=1
    )
    # Match via folder or guessit
    result = manager.resolve(
        filepath="D:/Anime/Frieren/Frieren - 05 [1080p].mkv",
        raw_title="Frieren - 05",
        guessit_info={"title": "Frieren", "episode": 5, "season": 1}
    )
    assert result is not None
    assert result["simkl_id"] == 2095944
    assert result["type"] == "anime"
    assert result["season"] == 1
    assert result["episode"] == 5

def test_exact_mapping_overrides_show_rule(tmp_path: Path):
    manager = CustomMappingManager(tmp_path)
    manager.add_show_rule(
        match_key="frieren",
        simkl_id=2095944,
        media_type="anime",
        title="Frieren: Beyond Journey's End",
        default_season=1
    )
    manager.add_exact_mapping(
        filename_or_path="frieren_special.mkv",
        simkl_id=999999,
        media_type="movie",
        title="Frieren Special"
    )
    result = manager.resolve("D:/Anime/Frieren/frieren_special.mkv", guessit_info={"title": "Frieren"})
    assert result["simkl_id"] == 999999
    assert result["title"] == "Frieren Special"

def test_corrupt_file_recovery(tmp_path: Path):
    corrupt_file = tmp_path / "custom_mappings.json"
    corrupt_file.write_text("{invalid_json: true", encoding="utf-8")
    manager = CustomMappingManager(tmp_path)
    assert manager.get_all() == {"version": 1, "exact_files": {}, "show_rules": {}}
    assert (tmp_path / "custom_mappings.json.corrupted").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_custom_mapping_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simkl_mps.custom_mapping_manager'`

- [ ] **Step 3: Implement `CustomMappingManager` in `simkl_mps/custom_mapping_manager.py`**

Implement load/save with atomic file replacement, thread lock, corrupted file recovery, exact match normalization, and show rule matching against parent folder and `guessit_info` title.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_custom_mapping_manager.py -v`
Expected: PASS

- [ ] **Step 5: Verify commit message**

Message: `feat(mapping): implement CustomMappingManager for persistent media rules`

---

### Task 2: Simkl API URL & Multi-Search Utilities (`simkl_mps/simkl_api.py`)

**Files:**
- Modify: `simkl_mps/simkl_api.py`
- Create: `tests/test_simkl_api_search_url.py`

**Interfaces:**
- Produces:
  ```python
  def parse_simkl_url(url: str) -> tuple[str, int] | None: ...
  def search_simkl_multi(query: str, client_id: str, access_token: str | None = None, limit_per_category: int = 5) -> list[dict]: ...
  ```

- [ ] **Step 1: Write the failing tests for URL parsing and multi-search**

In `tests/test_simkl_api_search_url.py`:
```python
import pytest
from simkl_mps.simkl_api import parse_simkl_url, search_simkl_multi

def test_parse_simkl_url_valid_formats():
    assert parse_simkl_url("https://simkl.com/anime/2095944/sousou-no-frieren") == ("anime", 2095944)
    assert parse_simkl_url("https://simkl.com/tv/1690042/shogun") == ("show", 1690042)
    assert parse_simkl_url("https://simkl.com/movies/12345/dune") == ("movie", 12345)
    assert parse_simkl_url("simkl.com/anime/2095944") == ("anime", 2095944)

def test_parse_simkl_url_invalid():
    assert parse_simkl_url("https://www.imdb.com/title/tt1234567/") is None
    assert parse_simkl_url("not a url") is None
    assert parse_simkl_url("") is None

def test_search_simkl_multi(monkeypatch):
    # Mock network responses for /search/tv, /search/anime, /search/movie
    def fake_get(url, *args, **kwargs):
        class FakeResponse:
            status_code = 200
            def json(self):
                if "/search/anime" in url:
                    return [{"ids": {"simkl": 2095944}, "title": "Frieren", "year": 2023, "type": "anime"}]
                return []
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    results = search_simkl_multi("frieren", client_id="fake_client_id")
    assert len(results) == 1
    assert results[0]["simkl_id"] == 2095944
    assert results[0]["type"] == "anime"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_simkl_api_search_url.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_simkl_url'`

- [ ] **Step 3: Implement `parse_simkl_url` and `search_simkl_multi` in `simkl_mps/simkl_api.py`**

Implement regex matching for Simkl URLs (`https?://(?:www\.)?simkl\.com/(anime|tv|movies|movie)/(\d+)`) and multi-category query dispatching across anime, tv, and movie endpoints.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_simkl_api_search_url.py -v`
Expected: PASS

- [ ] **Step 5: Verify commit message**

Message: `feat(api): add Simkl URL parser and unified multi-type search helper`

---

### Task 3: MediaScrobbler Integration & Live Correction Swap (`simkl_mps/media_scrobbler.py`)

**Files:**
- Modify: `simkl_mps/media_scrobbler.py`
- Create: `tests/test_media_scrobbler_custom_mapping.py`

**Interfaces:**
- Consumes: `CustomMappingManager`, `parse_simkl_url`, `get_show_details`, `get_movie_details`, `delete_playback`
- Produces:
  ```python
  class MediaScrobbler:
      def apply_manual_correction(
          self,
          simkl_id: int,
          media_type: str,
          title: str,
          season: int | None = None,
          episode: int | None = None,
          apply_to_series: bool = False,
          year: int | None = None,
          poster_url: str | None = None
      ) -> bool: ...
  ```

- [ ] **Step 1: Write the failing tests for MediaScrobbler custom mapping integration**

In `tests/test_media_scrobbler_custom_mapping.py`:
```python
import pytest
from pathlib import Path
from simkl_mps.media_scrobbler import MediaScrobbler

def test_identify_uses_custom_mapping_first(tmp_path: Path, monkeypatch):
    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id")
    scrobbler.custom_mappings.add_exact_mapping(
        filename_or_path="test_video.mkv",
        simkl_id=88888,
        media_type="anime",
        title="Custom Title",
        season=1,
        episode=2
    )

    scrobbler.current_filepath = "D:/Videos/test_video.mkv"
    scrobbler.currently_tracking = "test_video.mkv"
    scrobbler._identify_media_from_filepath(scrobbler.current_filepath)

    assert scrobbler.simkl_id == 88888
    assert scrobbler.movie_name == "Custom Title"
    assert scrobbler.season == 1
    assert scrobbler.episode == 2

def test_apply_manual_correction_live_swap(tmp_path: Path, monkeypatch):
    deleted_playbacks = []
    def fake_delete(playback_id, *args, **kwargs):
        deleted_playbacks.append(playback_id)
        return True

    from simkl_mps import simkl_api
    monkeypatch.setattr(simkl_api, "delete_playback", fake_delete)

    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id", access_token="token")
    scrobbler.current_filepath = "D:/Videos/frieren_01.mkv"
    scrobbler.currently_tracking = "frieren_01.mkv"
    scrobbler.simkl_id = 11111  # Wrong previous ID
    scrobbler._scrobble_playback_id = 999  # Active session

    success = scrobbler.apply_manual_correction(
        simkl_id=2095944,
        media_type="anime",
        title="Frieren: Beyond Journey's End",
        season=1,
        episode=1,
        apply_to_series=True
    )

    assert success is True
    assert scrobbler.simkl_id == 2095944
    assert scrobbler.movie_name == "Frieren: Beyond Journey's End"
    assert 999 in deleted_playbacks
    # Check that rule was persisted
    saved_rule = scrobbler.custom_mappings.resolve("D:/Videos/frieren_01.mkv")
    assert saved_rule["simkl_id"] == 2095944
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_media_scrobbler_custom_mapping.py -v`
Expected: FAIL with `AttributeError: 'MediaScrobbler' object has no attribute 'apply_manual_correction'`

- [ ] **Step 3: Implement custom mapping checks and `apply_manual_correction` in `simkl_mps/media_scrobbler.py`**

1. Instantiate `self.custom_mappings = CustomMappingManager(self.app_data_dir)` in `MediaScrobbler.__init__`.
2. Add custom mapping checks at top of `_identify_media_from_filepath` and `_identify_movie`.
3. Implement `apply_manual_correction(...)`:
   - Persists rules via `self.custom_mappings`.
   - Cleans up active playback sessions via `delete_playback`.
   - Mutates tracking attributes and resets scrobble machine timers.
   - Updates `self.media_cache`.
   - Updates Discord RPC and dispatches desktop notification.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_media_scrobbler_custom_mapping.py -v`
Expected: PASS

- [ ] **Step 5: Verify commit message**

Message: `feat(scrobbler): integrate custom mapping resolution and live correction swap`

---

### Task 4: Tkinter Correction Dialog (`simkl_mps/correction_dialog.py`)

**Files:**
- Create: `simkl_mps/correction_dialog.py`
- Create: `tests/test_correction_dialog_logic.py`

**Interfaces:**
- Consumes: `parse_simkl_url`, `search_simkl_multi`, `get_show_details`, `get_movie_details`
- Produces:
  ```python
  class CorrectionDialogController:
      @staticmethod
      def resolve_input(input_str: str, client_id: str, access_token: str | None) -> dict: ...
      @staticmethod
      def build_correction_payload(selected_item: dict, season_str: str, episode_str: str, apply_to_series: bool) -> dict: ...
  def show_correction_window(parent_root, scrobbler, on_success_callback=None) -> None: ...
  ```

- [ ] **Step 1: Write the failing tests for dialog controller logic**

In `tests/test_correction_dialog_logic.py`:
```python
import pytest
from simkl_mps.correction_dialog import CorrectionDialogController

def test_resolve_input_with_url(monkeypatch):
    from simkl_mps import simkl_api
    monkeypatch.setattr(simkl_api, "get_show_details", lambda simkl_id, *args: {"title": "Frieren", "type": "anime", "ids": {"simkl": simkl_id}})
    
    result = CorrectionDialogController.resolve_input(
        "https://simkl.com/anime/2095944/frieren",
        client_id="test_client",
        access_token="test_token"
    )
    assert result["mode"] == "direct"
    assert result["item"]["simkl_id"] == 2095944
    assert result["item"]["title"] == "Frieren"

def test_build_correction_payload_movie():
    selected = {"simkl_id": 1690042, "type": "movie", "title": "Dune: Part Two"}
    payload = CorrectionDialogController.build_correction_payload(
        selected_item=selected,
        season_str="1",
        episode_str="5",
        apply_to_series=False
    )
    assert payload["simkl_id"] == 1690042
    assert payload["media_type"] == "movie"
    assert payload["season"] is None
    assert payload["episode"] is None
    assert payload["apply_to_series"] is False

def test_build_correction_payload_show():
    selected = {"simkl_id": 2095944, "type": "anime", "title": "Frieren"}
    payload = CorrectionDialogController.build_correction_payload(
        selected_item=selected,
        season_str="2",
        episode_str="8",
        apply_to_series=True
    )
    assert payload["simkl_id"] == 2095944
    assert payload["media_type"] == "anime"
    assert payload["season"] == 2
    assert payload["episode"] == 8
    assert payload["apply_to_series"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_correction_dialog_logic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'simkl_mps.correction_dialog'`

- [ ] **Step 3: Implement `CorrectionDialogController` and `show_correction_window` in `simkl_mps/correction_dialog.py`**

Implement `CorrectionDialogController` logic, followed by the Tkinter modal window with async search thread, candidate `Listbox`, season/episode inputs, series checkbox, and apply button.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_correction_dialog_logic.py -v`
Expected: PASS

- [ ] **Step 5: Verify commit message**

Message: `feat(ui): implement Tkinter manual correction dialog and controller`

---

### Task 5: System Tray Integration (`simkl_mps/tray_base.py`, `simkl_mps/tray_win.py`)

**Files:**
- Modify: `simkl_mps/tray_base.py`
- Modify: `simkl_mps/tray_win.py`
- Create: `tests/test_tray_custom_mapping_menu.py`

**Interfaces:**
- Consumes: `CorrectionDialog`, `MediaScrobbler.apply_manual_correction`
- Produces:
  ```python
  class TrayAppBase:
      def correct_current_media(self, _=None) -> None: ...
      def open_custom_mappings(self, _=None) -> None: ...
  ```

- [ ] **Step 1: Write the failing tests for tray menu actions**

In `tests/test_tray_custom_mapping_menu.py`:
```python
import pytest
from unittest.mock import MagicMock
from simkl_mps.tray_base import TrayAppBase

class DummyTray(TrayAppBase):
    def update_icon(self): pass
    def show_notification(self, title, msg): pass
    def _ask_custom_threshold_dialog(self, cur): return None
    def _ask_custom_min_watch_time_dialog(self, cur): return None
    def _ask_directory_filter_dialog(self, t, cur, h): return None

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_tray_custom_mapping_menu.py -v`
Expected: FAIL with `AssertionError: assert hasattr(tray, "correct_current_media")`

- [ ] **Step 3: Implement tray menu entries and Windows dialog dispatch**

1. In `simkl_mps/tray_base.py`:
   - Add `correct_current_media` and `open_custom_mappings` methods.
   - Insert `pystray.MenuItem("Correct Current Media...", self.correct_current_media)` in the `Scrobbling` menu.
   - Insert `pystray.MenuItem("Open Custom Mappings", self.open_custom_mappings)` in the `Maintenance` menu.
2. In `simkl_mps/tray_win.py`:
   - Implement `_show_correction_dialog` via `_run_on_tk_thread` using `show_correction_window`.
   - Implement `open_custom_mappings` using `os.startfile` or text editor fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_tray_custom_mapping_menu.py -v`
Expected: PASS

- [ ] **Step 5: Verify commit message**

Message: `feat(tray): add correct media dialog trigger and custom mappings menu options`

---

### Task 6: Full Regression & Integration Verification

**Files:**
- Run: Entire test suite

- [ ] **Step 1: Run all tests in the repository**

Run: `poetry run pytest`
Expected: ALL PASS

- [ ] **Step 2: Verify commit message**

Message: `test(mapping): verify end-to-end regression and integration for manual media correction`
