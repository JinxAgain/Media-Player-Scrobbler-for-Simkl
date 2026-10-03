# Simkl Scrobble Lifecycle & Two-Way Playback Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report real-time playback to Simkl (`start`/`pause`), save unfinished progress to the Playback Progress Manager on exit, and auto-seek MPV to the saved position when the same media is reopened.

**Architecture:** `simkl_api.py` gets thin wrappers for `/scrobble/*` and `/sync/playback`. `MediaScrobbler` (already polled every 10 s by `Monitor`) gains a reconcile-style state sync (`_sync_scrobble_state`), a threshold-aware `stop_tracking()` finalizer, and a one-shot resume step run right after a media item is identified. MPV IPC gets `seek_absolute` / `show_osd`. Settings live in `settings.json` via `config_manager`.

**Tech Stack:** Python 3.12, `requests`, `pytest` + `monkeypatch`, pystray tray menu, MPV JSON IPC (named pipe / unix socket).

**Spec:** `docs/superpowers/specs/2026-10-03-simkl-scrobble-resume-design.md` (read its new §6 "Implementation Adjustments" too).

## Global Constraints

- All code, comments, log messages and commit messages in **English**.
- **Never hardcode 80.** Always read `self.completion_threshold` (tray: 65 / 80 / 90 / custom, valid 1–100).
- Unfinished progress is saved with `POST /scrobble/pause`, **never** `/scrobble/stop` (Simkl's server-side stop rule is a fixed 80 %). Never send `allow_rewatch` on scrobble calls.
- Scrobble only on state changes (start / pause / exit). **No heartbeat, no per-seek calls.**
- Minimum progress to save a playback: `2.0` %; minimum watched time: `30` s (`MIN_REPORT_WATCH_SECONDS`); minimum spacing between scrobble calls: `2.5` s (`SCROBBLE_MIN_INTERVAL`).
- Resume only when remote progress is in `[2.0, completion_threshold)`, local position `<= resume_start_tolerance_seconds` (default **30**), and `abs(local - target) > 5` s. At most once per media item.
- Scrobble/resume code must never raise into the monitor loop: catch `requests.RequestException` and log at `debug`/`warning`.
- Required request params on every call: `client_id`, `app-name`, `app-version`; headers `Authorization: Bearer`, `simkl-api-key`, `User-Agent` (reuse `_add_user_agent`, `APP_NAME`, `__version__`).
- **Do not run `git commit` / `git push` automatically.** Each task ends by proposing a commit message to the user. Work happens on branch `feature/simkl-scrobble-and-resume`.
- Tests live in the repo root as `test_*.py` (existing convention). Run with `python -m pytest <file> -v`.

## Review Focus

1. Player already closed when `stop_tracking()` runs (IPC gone): the last polled position (≤ 10 s stale) must still produce a `pause` report. → Task 5 test.
2. Playlist advance inside the same MPV (media change → `stop_tracking()` of the old item): the **old** item's progress is reported and the new item starts with a fresh `start`. → Task 5 test.
3. Simkl `400 RATE_LIMIT`, network error, or `409`: never crash; 409 counts as success; failures stay "unreported" so the next poll retries. → Tasks 2 and 4 tests.
4. Unidentified / offline media (`simkl_id` is `None` or `temp_…`, or no credentials): zero scrobble calls, zero resume attempts, no exception. → Tasks 4 and 6 tests.
5. Threshold boundaries: `pct == threshold` → history path, `threshold=90, pct=85` → pause, `pct=1.9` → nothing, `remote >= threshold` → no seek, user already seeked past tolerance → no seek, `duration` not yet known → no seek yet. → Tasks 5 and 6 tests.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `simkl_mps/config_manager.py` | modify | New defaults in `DEFAULT_SETTINGS` |
| `simkl_mps/simkl_api.py` | modify | `scrobble`, `get_playback_sessions`, `delete_playback` |
| `simkl_mps/players/mpv.py` | modify | `seek_absolute`, `show_osd`, `_run_command` |
| `simkl_mps/players/mpv_wrappers.py` | modify | Delegating `seek_absolute`, `show_osd` |
| `simkl_mps/media_scrobbler.py` | modify | Scrobble state sync, stop finalizer, resume, cleanup, MPV pause detection |
| `simkl_mps/tray_base.py` | modify | Two new checkbox menu items + toggle handlers |
| `test_config_scrobble_settings.py` | create | Task 1 |
| `test_simkl_scrobble_api.py` | create | Task 2 |
| `test_mpv_control.py` | create | Task 3 |
| `test_scrobble_state.py` | create | Tasks 4, 5, 7 (shared fixtures) |
| `test_playback_resume.py` | create | Task 6 |
| `docs/` config page | modify | Task 9 |

---

### Task 0: Working test environment

**Files:** none (environment only).

The default Python lacks project deps (`pygetwindow` import fails when collecting `test_media_scrobbler_notifications.py`) and `poetry` is not installed.

- [ ] **Step 1:** Create a venv and install the project with dev extras: `python -m venv .venv` then `.venv\Scripts\python -m pip install -e ".[dev]"` (ask the user before installing). Ensure `.venv` is git-ignored.
- [ ] **Step 2:** Run `.venv\Scripts\python -m pytest test_media_scrobbler_notifications.py -q`. Expected: all tests PASS. Record any pre-existing failures so they are not blamed on this work.
- [ ] **Step 3:** No commit.

---

### Task 1: Settings defaults

**Files:**
- Modify: `simkl_mps/config_manager.py:38-46` (`DEFAULT_SETTINGS`)
- Test: `test_config_scrobble_settings.py`

**Interfaces:**
- Produces: settings keys read via `get_setting(...)` by later tasks:
  `enable_realtime_scrobble: bool = True`, `enable_playback_resume: bool = True`, `resume_start_tolerance_seconds: int = 30`.

- [ ] **Step 1: Write failing test** `test_scrobble_settings_defaults` asserting `DEFAULT_SETTINGS["enable_realtime_scrobble"] is True`, `DEFAULT_SETTINGS["enable_playback_resume"] is True`, `DEFAULT_SETTINGS["resume_start_tolerance_seconds"] == 30` (import via the same `sys.modules` package-stub pattern as `test_media_scrobbler_notifications.py`).
- [ ] **Step 2:** Run `python -m pytest test_config_scrobble_settings.py -v`. Expected: FAIL with `KeyError`.
- [ ] **Step 3:** Add the three keys to `DEFAULT_SETTINGS`. `load_settings()` already back-fills missing keys, so existing users upgrade transparently.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** Propose commit: `feat(config): add scrobble and resume settings defaults`.

---

### Task 2: Simkl API wrappers

**Files:**
- Modify: `simkl_mps/simkl_api.py` (append after `get_activities`, ~line 625)
- Test: `test_simkl_scrobble_api.py`

**Interfaces:**
- Produces:
  - `scrobble(action: str, item: dict, progress: float, client_id: str, access_token: str) -> dict` → `{"ok": bool, "status": int | None, "error": str | None}`. `action ∈ {"start","pause","stop"}`; body is `{**item, "progress": round(progress, 2)}`; `POST {SIMKL_API_BASE_URL}/scrobble/{action}` with params `client_id/app-name/app-version`, `timeout=5`. `ok=True` for 2xx **and** 409. Invalid `action` or missing credentials → `ok=False, status=None` without a request. 400/other statuses → `ok=False` with `status` set. `requests.RequestException` → `ok=False, status=None, error=str(e)`. Does **not** call `is_internet_connected()` (extra latency; the request itself fails fast).
  - `get_playback_sessions(client_id: str, access_token: str, media_type: str | None = None) -> list[dict] | None`: `GET /sync/playback[/episodes|/movies]`; returns the JSON list, `None` on any failure; `timeout=10`.
  - `delete_playback(playback_id: int, client_id: str, access_token: str) -> bool`: `DELETE /sync/playback/{id}`; `True` on 2xx.

- [ ] **Step 1: Write failing tests** (monkeypatch `simkl_api.requests.post/get/delete` with fakes returning objects with `status_code`, `json()`, `text`):
  - `test_scrobble_posts_body_and_params` – asserts URL ends `/scrobble/pause`, JSON body contains `{"movie": {...}, "progress": 42.5}`, params contain `client_id`, `app-name`, `app-version`, header `Authorization == "Bearer tok"`.
  - `test_scrobble_409_is_soft_success` – status 409 → `ok is True`.
  - `test_scrobble_400_is_failure_without_raising` – status 400 → `ok is False and status == 400`.
  - `test_scrobble_network_error_returns_not_ok` – fake raises `requests.ConnectionError` → `ok is False and status is None`.
  - `test_scrobble_rejects_unknown_action` – `"seek"` → `ok is False`, fake never called.
  - `test_get_playback_sessions_paths` – `media_type="episodes"` hits `/sync/playback/episodes`; `None` hits `/sync/playback`; non-2xx → `None`.
  - `test_delete_playback_uses_delete_method` – returns `True` on 200/204.
- [ ] **Step 2:** Run. Expected: FAIL (`AttributeError: module has no attribute 'scrobble'`).
- [ ] **Step 3:** Implement the three functions with the signatures above, following the header/params style of `add_to_history`.
- [ ] **Step 4:** Run. Expected: all PASS.
- [ ] **Step 5:** Propose commit: `feat(api): add scrobble and playback session endpoints`.

---

### Task 3: MPV control over IPC

**Files:**
- Modify: `simkl_mps/players/mpv.py` (add after `is_paused`, ~line 525)
- Modify: `simkl_mps/players/mpv_wrappers.py` (add after `is_paused`, ~line 508)
- Test: `test_mpv_control.py`

**Interfaces:**
- Produces on `MPVIntegration`:
  - `_run_command(self, command: list) -> bool` – under `self.ipc_lock`: `_connect()`, `_send_command(command)`, `_receive_response()`, `_disconnect()` in `finally`; `True` iff response `error == "success"`; `MPVError` → `False`.
  - `seek_absolute(self, seconds: float) -> bool` → `_run_command(["seek", round(seconds, 2), "absolute"])`.
  - `show_osd(self, text: str, duration_ms: int = 3500) -> bool` → `_run_command(["show-text", text, duration_ms])`.
- Produces on `MPVWrapperIntegration` (decorated with `@with_custom_ipc_path` like `is_paused`): `seek_absolute(self, seconds, process_name=None) -> bool`, `show_osd(self, text, duration_ms=3500, process_name=None) -> bool`, delegating to `self.mpv_integration`.

- [ ] **Step 1: Write failing tests** (build `MPVIntegration` with `monkeypatch` stubs for `_connect`, `_disconnect`, `_send_command`, `_receive_response`; on Windows `win32*` may be missing, so stub at method level only):
  - `test_seek_absolute_sends_expected_command` – captured command `== ["seek", 754.33, "absolute"]` for input `754.333`.
  - `test_show_osd_sends_expected_command` – `["show-text", "hello", 3500]`.
  - `test_run_command_returns_false_on_error_response` – response `{"error": "property unavailable", "request_id": 1}` → `False`.
  - `test_run_command_returns_false_when_not_connected` – `_connect` raises `MPVError` → `False`, no exception.
  - `test_wrapper_delegates` – wrapper with stub `mpv_integration` records calls (bypass the decorator's path logic by calling through a fake `is_mpv_wrapper`/`_get_custom_ipc_path`, or test the undecorated function via `__wrapped__` if `wraps` was used).
- [ ] **Step 2:** Run. Expected: FAIL (`AttributeError`).
- [ ] **Step 3:** Implement per the Interfaces block.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Propose commit: `feat(mpv): add seek and OSD IPC helpers`.

---

### Task 4: Real-time scrobble state sync

**Files:**
- Modify: `simkl_mps/media_scrobbler.py` — imports (`~line 21`), `__init__` (`~line 130`), `_detect_pause` (`~line 928`), end of `_update_tracking` (before the `return` at `~line 889`)
- Test: `test_scrobble_state.py`

**Interfaces:**
- Consumes: `scrobble(...)` from Task 2 (import into `media_scrobbler` namespace so tests can monkeypatch `media_scrobbler_module.scrobble`); settings from Task 1.
- Produces on `MediaScrobbler`:
  - class constants `SCROBBLE_MIN_INTERVAL = 2.5`, `MIN_REPORT_WATCH_SECONDS = 30`, `MIN_RESUME_PROGRESS = 2.0`.
  - fields (init in `__init__`, reset in `_start_new_media_item` and `stop_tracking`): `_scrobble_reported_state: str | None = None`, `_last_scrobble_attempt: float = 0.0`.
  - `_build_scrobble_item(self) -> dict | None` – `None` if `simkl_id` falsy or `str(simkl_id).startswith("temp_")` or not int-convertible. `movie` → `{"movie": {"ids": {"simkl": id}}}`; `show` → `{"show": {"ids": {...}}, "episode": {"season": s, "number": e}}` (needs both, else `None`); `anime` → `{"anime": {"ids": {...}}, "episode": {"number": e}}` plus `"season"` only if `self.season is not None`; other types → `None`.
  - `_current_progress_pct(self) -> float | None` → `self._calculate_percentage(use_position=True)`.
  - `_report_scrobble(self, action: str, progress: float) -> bool` – returns `False` without calling the API if credentials missing or `_build_scrobble_item()` is `None`; otherwise calls `scrobble(...)`, stamps `_last_scrobble_attempt`, logs, returns `result["ok"]`.
  - `_sync_scrobble_state(self) -> None` – no-op unless `get_setting("enable_realtime_scrobble", True)` and tracking an identified item and `not self.completed`. Desired action = `"pause"` if `self.state == PAUSED` else `"start"`. If `desired != _scrobble_reported_state` and `time.time() - _last_scrobble_attempt >= SCROBBLE_MIN_INTERVAL`: report with `_current_progress_pct() or 0.0`; on success set `_scrobble_reported_state = desired`. A failed call leaves the state unchanged so the next poll retries.
  - `_detect_pause(window_info)` extended: for MPV-family integrations (integration has `is_paused`, selected via `_get_player_integration(process_name.lower())` and class name in `{"MPVIntegration", "MPVWrapperIntegration"}`), use `is_paused()`; if it returns `None`/raises, fall back to the existing title-keyword logic. (The title check never fires for stock MPV, so without this `pause` would never be reported.)

- [ ] **Step 1: Write failing tests** using a shared `_make_scrobbler(tmp_path, monkeypatch)` fixture (credentials set, `scrobble` replaced by a recorder returning `{"ok": True, "status": 200, "error": None}`, `time.time` controlled via a mutable clock, `simkl_id=123`, `media_type="movie"`, `currently_tracking="X"`, `total_duration_seconds=1000`, `current_position_seconds=100`):
  - `test_build_scrobble_item_variants` – movie / show with S+E / anime with E only / show missing episode (`None`) / `temp_ab12cd34` (`None`).
  - `test_sync_sends_start_once_then_nothing` – two syncs 10 s apart while playing → exactly one `start` with `progress == 10.0`.
  - `test_sync_sends_pause_on_state_change_and_start_on_resume` – PLAYING→PAUSED→PLAYING (clock +10 s each) yields `["start","pause","start"]`.
  - `test_sync_respects_min_interval` – state flips 1 s after the last attempt → no call; after 2.5 s → one call.
  - `test_sync_failure_is_retried_next_poll` – recorder returns `{"ok": False, "status": 400, ...}` once → `_scrobble_reported_state` stays `None`, next sync calls again.
  - `test_sync_skipped_when_setting_disabled` – monkeypatch `get_setting` for `enable_realtime_scrobble=False` → no calls.
  - `test_sync_skipped_for_unidentified_or_completed` – `simkl_id=None`, `"temp_x"`, or `completed=True` → no calls.
  - `test_detect_pause_uses_mpv_is_paused` – fake MPV integration (class named `MPVIntegration`) returning `True` → `_detect_pause({"process_name": "mpv.exe", "title": "movie.mkv - mpv"}) is True`; returning `None` with a title containing "paused" → `True` (fallback).
- [ ] **Step 2:** Run `python -m pytest test_scrobble_state.py -v`. Expected: FAIL (`AttributeError`).
- [ ] **Step 3:** Implement the interfaces; call `_sync_scrobble_state()` at the end of `_update_tracking` after the completion check (so a just-completed item is not reported).
- [ ] **Step 4:** Run. Expected: PASS. Also re-run `test_media_scrobbler_notifications.py` (no regressions).
- [ ] **Step 5:** Propose commit: `feat(scrobbler): report start and pause to Simkl in real time`.

---

### Task 5: Threshold-aware stop finalizer

**Files:**
- Modify: `simkl_mps/media_scrobbler.py:939-1008` (`stop_tracking`)
- Test: `test_scrobble_state.py`

**Interfaces:**
- Consumes: `_report_scrobble`, `_current_progress_pct`, constants from Task 4.
- Produces: `stop_tracking()` keeps its return dict; additionally, **before the state reset**, after the existing "met completion threshold upon stopping" block:
  - if `not self.completed` and `get_setting("enable_realtime_scrobble", True)` and `self.watch_time >= MIN_REPORT_WATCH_SECONDS` and `MIN_RESUME_PROGRESS <= pct < self.completion_threshold` → `_report_scrobble("pause", pct)` (ignore the throttle interval here; failures only log).
  - Reset `_scrobble_reported_state = None` and `_last_scrobble_attempt = 0.0` with the other fields.
  - The existing `self._attempt_add_to_history()` branch for `pct >= threshold` is unchanged.

- [ ] **Step 1: Write failing tests** (same fixture; set `watch_time`, `current_position_seconds`, `total_duration_seconds`, `completion_threshold`):
  - `test_stop_below_threshold_reports_pause` – threshold 80, 45 % → one `pause` with `progress == 45.0`.
  - `test_stop_custom_threshold_90_at_85_reports_pause` – threshold 90, 85 % → `pause` (never `stop`).
  - `test_stop_at_threshold_uses_history_not_pause` – threshold 65, 65 %, `_attempt_add_to_history` monkeypatched to a recorder → recorder called, no `pause`.
  - `test_stop_below_min_progress_reports_nothing` – 1.9 % → no calls; also `watch_time=10` at 50 % → no calls.
  - `test_stop_completed_item_reports_nothing` – `completed=True`, 70 % → no calls.
  - `test_stop_with_stale_position_still_reports` – player integration raising `requests.RequestException`; `current_position_seconds` stays at last polled value → `pause` reported (Review Focus #1).
  - `test_media_change_reports_old_item_then_resets` – call `stop_tracking()` for item A at 40 % then verify `_scrobble_reported_state is None` and a following `_sync_scrobble_state()` for item B sends `start` (Review Focus #2).
  - `test_stop_network_error_does_not_raise` – recorder raises `requests.ConnectionError` → `stop_tracking()` still returns the dict.
- [ ] **Step 2:** Run. Expected: FAIL (no `pause` recorded).
- [ ] **Step 3:** Implement per Interfaces. Catch exceptions around the report so teardown never fails.
- [ ] **Step 4:** Run `test_scrobble_state.py` fully. Expected: PASS.
- [ ] **Step 5:** Propose commit: `feat(scrobbler): save unfinished progress on stop using the configured threshold`.

---

### Task 6: Reverse playback resume

**Files:**
- Modify: `simkl_mps/media_scrobbler.py` — imports, `__init__`, `_start_new_media_item` (reset), `_update_tracking` (call before `_sync_scrobble_state`)
- Test: `test_playback_resume.py`

**Interfaces:**
- Consumes: `get_playback_sessions` (Task 2), `seek_absolute`/`show_osd` (Task 3), settings (Task 1), `_report_scrobble` (Task 4).
- Produces on `MediaScrobbler`:
  - fields reset per item: `_resume_done: bool = False`, `_resume_sessions: list | None = None`.
  - `@staticmethod _format_timestamp(seconds: float) -> str` → `"M:SS"` below one hour, `"H:MM:SS"` otherwise (`754.3` → `"12:34"`, `3725` → `"1:02:05"`).
  - `_find_matching_playback(self, sessions: list[dict]) -> dict | None` – movie: `session["movie"]["ids"]["simkl"] == int(simkl_id)`; show/anime: `(session.get("show") or session.get("anime"))["ids"]["simkl"]` equals the id **and** `session["episode"]["number"] == self.episode` **and** (when `self.season` is not None and the session has `season`) `season` equal. Picks the most recent `paused_at` if several. Returns `None` for unidentified media.
  - `_try_resume_playback(self, process_name: str, position: float | None, duration: float | None) -> None` – runs at most once per item (`_resume_done` set as soon as a decision is final, i.e. after a seek, after deciding not to seek, or when sessions fetch fails). Steps: setting `enable_playback_resume` on; identified item with credentials; `duration` known (else return **without** setting `_resume_done` so the next poll retries); fetch sessions once (`media_type="movies"` or `"episodes"`) into `_resume_sessions`; find match; `progress = float(session["progress"])`; require `MIN_RESUME_PROGRESS <= progress < self.completion_threshold`; require `position <= get_setting("resume_start_tolerance_seconds", 30)`; `target = progress / 100 * duration`; skip seek when `abs(position - target) <= 5`; else `integration.seek_absolute(target)` then `integration.show_osd(f"[Simkl] Resumed at {int(progress)}% ({self._format_timestamp(target)})")` when the integration has those methods; update `self.current_position_seconds = target`; log the event with `_log_playback_event("resume_applied", {...})`.

- [ ] **Step 1: Write failing tests** (fake integration object with `seek_absolute`/`show_osd` recorders, class name `MPVIntegration`; `get_playback_sessions` monkeypatched in the module namespace; session dicts shaped like the Simkl docs: `{"id": 1, "progress": 42.2, "paused_at": "...", "type": "episode", "episode": {"season": 1, "number": 3}, "show": {"title": "...", "ids": {"simkl": 123}}}`):
  - `test_format_timestamp`.
  - `test_find_matching_playback_movie_and_episode` – matches by id+episode; no match for different episode; `None` for temp id.
  - `test_resume_seeks_and_shows_osd` – position 5, duration 1000, progress 45, threshold 80 → `seek_absolute(450.0)`, OSD text `"[Simkl] Resumed at 45% (7:30)"`.
  - `test_resume_waits_for_duration` – `duration=None` → no fetch, no seek, `_resume_done is False`; next call with duration seeks.
  - `test_resume_skips_when_user_already_past_tolerance` – position 120 → no seek, `_resume_done is True`.
  - `test_resume_skips_when_close_to_target` – position 448, target 450 → no seek.
  - `test_resume_skips_at_or_above_threshold` – threshold 90, progress 92 → no seek; threshold 65, progress 70 → no seek.
  - `test_resume_skips_below_min_progress` – progress 1.0.
  - `test_resume_runs_once_per_item` – second call after success makes no second fetch.
  - `test_resume_disabled_setting` – `enable_playback_resume=False` → no fetch.
  - `test_resume_api_failure_is_silent` – `get_playback_sessions` returns `None` → no exception, `_resume_done is True`.
  - `test_resume_skipped_for_integration_without_seek` – VLC-like fake without `seek_absolute` → no exception, no seek.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement per Interfaces. In `_update_tracking`, after position/duration are known and the item is identified, call `self._try_resume_playback(process_name, self.current_position_seconds, self.total_duration_seconds)` **before** `_sync_scrobble_state()`, so the first `start` already carries the resumed progress.
- [ ] **Step 4:** Run. Expected: PASS; re-run `test_scrobble_state.py`.
- [ ] **Step 5:** Propose commit: `feat(scrobbler): resume MPV playback from Simkl saved position`.

---

### Task 7: Clear stale pause after completion

**Files:**
- Modify: `simkl_mps/media_scrobbler.py` — success branch of `_attempt_add_to_history` (`~line 1658-1660`)
- Test: `test_scrobble_state.py`

**Why:** A `pause` sent earlier in the session (e.g. user paused at 60 % with threshold 65 %, then finished) would stay in the Playback Progress Manager. Simkl docs only promise `stop ≥ 80` clears playback, not `sync/history`, so remove it explicitly.

**Interfaces:**
- Consumes: `get_playback_sessions`, `delete_playback` (Task 2), `_find_matching_playback` (Task 6).
- Produces: `_clear_saved_playback(self) -> None` – only acts when `_scrobble_reported_state == "pause"` or a resume session was applied (`_resume_sessions` not `None`); fetches sessions, deletes the matching one by `id`, swallows all errors. Called right after `self.completed = True` in the successful history branch.

- [ ] **Step 1: Write failing tests:** `test_completion_deletes_matching_saved_playback` (monkeypatched API functions; asserts `delete_playback(1, ...)` called), `test_completion_without_prior_pause_makes_no_calls`, `test_clear_saved_playback_swallows_errors`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run `test_scrobble_state.py` and `test_playback_resume.py`. Expected: PASS.
- [ ] **Step 5:** Propose commit: `fix(scrobbler): remove stale saved playback once an item is completed`.

---

### Task 8: Tray menu toggles

**Files:**
- Modify: `simkl_mps/tray_base.py` — add handlers after `toggle_rewatch_enabled` (`~line 1206`) and menu items in the `Scrobbling` submenu (`~line 1260`)
- Test: manual (pystray menus are not unit-tested in this repo)

**Interfaces:**
- Produces: `toggle_realtime_scrobble(self, _=None)` and `toggle_playback_resume(self, _=None)` mirroring `toggle_notifications_disabled` (flip with `set_setting`, `self.update_icon()`, `self.show_notification("Settings Updated", ...)`, `return 0`).
- Menu labels: `"Realtime Scrobbling (Watching Now)"` → `checked=lambda item: get_setting('enable_realtime_scrobble', True)`; `"Auto-Resume from Simkl"` → `checked=lambda item: get_setting('enable_playback_resume', True)`. Insert both after "Record Rewatches", before "Turn Notifications Off".

- [ ] **Step 1:** Implement the handlers and menu items.
- [ ] **Step 2:** Verify `python -c "import simkl_mps.tray_base"` imports cleanly (inside the venv).
- [ ] **Step 3:** Manual: launch the tray app, toggle both items, confirm check marks persist across restart and `settings.json` contains the new keys.
- [ ] **Step 4:** Propose commit: `feat(tray): add realtime scrobble and auto-resume toggles`.

---

### Task 9: Docs and end-to-end verification

**Files:**
- Modify: the configuration docs page under `docs/` (find the page that documents `watch_completion_threshold` / `allow_rewatch`) and `README.md` feature list.

- [ ] **Step 1:** Document the three settings, the 2 % / 30 s guards, and that unfinished progress uses `/scrobble/pause`.
- [ ] **Step 2:** Run the full suite: `python -m pytest -q`. Expected: new tests PASS; any failures must match the baseline recorded in Task 0.
- [ ] **Step 3 (manual E2E, Simkl account + MPV with `input-ipc-server`):**
  1. Play a known episode to ~45 %, close MPV → Simkl Playback Progress Manager shows ~45 %.
  2. Reopen the file → MPV jumps to ~45 % and shows the OSD message; "Watching now" appears on simkl.com.
  3. Set threshold to 90 %, stop at 85 % → saved as playback, **not** marked watched.
  4. Pause → after the next poll the dashboard shows the pause; spacebar-mash does not produce errors in the log.
  5. Complete the episode → marked watched and the saved playback disappears.
  6. Verify the real shape of `GET /sync/playback` for an **anime** entry (key `anime` vs `show`, `episode.number` numbering) and adjust `_find_matching_playback` if it differs.
- [ ] **Step 4:** Propose commit: `docs: document scrobble lifecycle and auto-resume settings`.
