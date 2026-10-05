# Discord Rich Presence Integration Design

## Overview
This feature integrates Discord Rich Presence into Media Player Scrobbler for Simkl (MPS). When the user plays media in a supported media player (e.g., MPV, VLC, PotPlayer, MPC-HC), MPS displays the active "Now Watching" title, season/episode details, countdown timer, poster artwork, and a link to Simkl directly in the user's Discord profile.

## Motivation & Architecture Choice
MPS already monitors local media players and Simkl scrobbling in real time. Rather than polling the Simkl cloud API (which violates Simkl API guidelines prohibiting polling timers and risks 429 rate limits), MPS uses a **local player-driven architecture**:
1. Zero extra network calls to Simkl: reuses local playback state and cached Simkl metadata.
2. Sub-second synchronization: immediately updates on play, pause, seek, and stop.
3. Clean, decoupled design: encapsulated in an independent `DiscordRPCManager` module with no impact on core scrobbling operations.

## Discord Rich Presence Card Layout (Harbor-Inspired)
The Discord Activity layout follows a clean, modern aesthetic inspired by Harbor:

```text
┌────────────────────────────────────────────────────────┐
│  正在观看 SIMKL                                         │  ← Activity Type (Watching / 3)
│                                                        │
│  [ Poster ]   Succession (2018)                        │  ← Details (Title + Year)
│  (LargeImg)  S02E03 · Hunting                         │  ← State (Season/Episode · Episode Title)
│              04:49 ━━━━━━━━━━━━━━━━ 56:46             │  ← Timestamps (Start + End progress bar)
│              [ View on Simkl ]                        │  ← Action Button (Visible to friends/viewers)
└────────────────────────────────────────────────────────┘
```

### Field Mapping Rules
1. **Activity Type**:
   - `ActivityType.WATCHING` (value 3). Displays as `正在观看 SIMKL` (or `Watching SIMKL` in English).
2. **Details**:
   - TV Show / Anime: `<Show Title> (<Year>)` (e.g., `Succession (2018)`)
   - Movie: `<Movie Title> (<Year>)` (e.g., `Inception (2010)`)
   - Fallback: Title without year if year is absent.
3. **State**:
   - TV Show / Anime (Playing): `S{season:02d}E{episode:02d} · {episode_title}` (e.g., `S02E03 · Hunting` or `S02E03`)
   - TV Show / Anime (Paused): `Paused · S{season:02d}E{episode:02d}`
   - Movie (Playing): `Watching`
   - Movie (Paused): `Paused`
4. **Timestamps (Progress Bar)**:
   - Playing: Calculate `start = time.time() - current_position` and `end = start + total_duration`. Passing both `start` and `end` triggers Discord's native media timeline progress bar showing elapsed time, progress slider, and total duration.
   - Paused: Clear timestamp (set to `None`) to prevent artificial timeline drift.
5. **Large Image & Large Text**:
   - Image: Full Simkl CDN poster URL (e.g., `https://simkl.net/posters/{poster}_m.jpg` resolved from `MediaCache` via Simkl ID, filename basename, or instance state).
   - Tooltip (`large_text`): Media title.
   - Fallback: Default Simkl logo or app icon if poster is unavailable.
6. **Small Image**:
   - Omitted (`None`) when poster is present to match Harbor's clean, unobscured poster presentation.
7. **Action Button (Single)**:
   - `label`: `View on Simkl`
   - `url`: `https://simkl.com/{type}/{simkl_id}` (where `type` is `movies`, `tv`, or `anime`).
   - *Note on Discord client visibility*: Discord's official client hides buttons when users view their own profile to prevent self-clicking, but buttons are fully visible and clickable to other Discord users viewing the profile.

## System Architecture & Components

### 1. Dependency
- Add `pypresence = "^4.3.0"` to `pyproject.toml`.
- `pypresence` communicates directly over local OS IPC named pipes (`\\.\pipe\discord-ipc-0` on Windows, UNIX domain sockets on Linux/macOS) with zero cloud overhead.

### 2. `DiscordRPCManager` (`simkl_mps/discord_rpc.py`)
Encapsulates all Discord IPC lifecycle management:
- **`__init__(client_id="1556713709462880316")`**: Stores Discord Application ID.
- **`connect()`**: Establishes IPC pipe connection asynchronously/safely without blocking the caller. Handles `DiscordNotFound`, `ConnectionRefusedError`, or timeouts gracefully.
- **`update_presence(details, state, end_timestamp=None, poster_url=None, simkl_url=None, media_title=None, is_paused=False)`**:
  - Connects lazily if not already connected.
  - Updates Discord activity payload using `pypresence.Presence.update`.
  - Debounces rapid updates to adhere to Discord's local IPC rate limits (~1 update per 1-2 seconds).
- **`clear_presence()`**: Clears the activity from Discord profile via `pypresence.Presence.clear`.
- **`disconnect()` / `close()`**: Closes IPC pipe on shutdown.

### 3. Integration into `MediaScrobbler` (`simkl_mps/media_scrobbler.py`)
Hooked cleanly into `MediaScrobbler` lifecycle hooks:
- Initialize `self.discord_rpc = DiscordRPCManager(client_id=get_setting("discord_client_id", "1556713709462880316"))` if `get_setting("enable_discord_rpc", True)` is enabled.
- **On State Change (Play/Resume)**:
  - When `self.state == PLAYING` and media is identified:
    - Gather title, season, episode, episode title, position, duration, and Simkl poster URL.
    - Call `self.discord_rpc.update_presence(...)`.
- **On State Change (Pause)**:
  - When `self.state == PAUSED`:
    - Call `self.discord_rpc.update_presence(..., is_paused=True)`.
- **On Playback Stop / Reset**:
  - When playback stops, player window closes, or media resets:
    - Call `self.discord_rpc.clear_presence()`.
- **On App Shutdown**:
  - Call `self.discord_rpc.close()`.

### 4. Configuration & Tray Menu Controls
- **Configuration** (`simkl_mps/config_manager.py`):
  - `enable_discord_rpc`: boolean, default `True`.
  - `discord_client_id`: string, default `"1556713709462880316"`.
- **System Tray** (`simkl_mps/tray_base.py`):
  - Add checkable menu item: `"Discord Rich Presence"`.
  - Checked callback reads `get_setting("enable_discord_rpc", True)`.
  - Click callback toggles the setting, writes config, and updates `MediaScrobbler`:
    - If disabled: immediately calls `clear_presence()` and disconnects.
    - If enabled: triggers an immediate status check if media is currently playing.

## Resilience & Error Handling
1. **Discord Not Running**:
   - `connect()` catches `DiscordNotFound` and `InvalidPipe` exceptions.
   - Logs at `DEBUG` level (does not spam warnings or pop up error dialogs).
   - Retries opportunistically when playback state changes (with min debounce interval of 30 seconds).
2. **Discord Closed / Crashed Mid-Playback**:
   - IPC pipe writes catch `PipeClosed` or `ConnectionResetError`.
   - Resets internal connection handle so subsequent calls can attempt reconnecting when Discord restarts.
3. **Missing Metadata / Fallbacks**:
   - If `duration_seconds` is unknown, omit `end_timestamp` (shows simple playback without countdown).
   - If poster is not yet cached or not available, use the default Discord application asset.
   - If single episode title is not yet available, fallback to `S{season:02d}E{episode:02d}`.

## Testing Strategy
1. **Unit Tests (`test_discord_rpc.py`)**:
   - Test payload formatting for Movie, TV Show, and Anime.
   - Test payload formatting for Playing vs Paused states.
   - Test timestamp calculation (remaining time).
   - Mock `pypresence.Presence` to verify `connect()`, `update()`, and `clear()` call signatures.
   - Test resilience when `pypresence` raises `DiscordNotFound` or `PipeClosed`.
2. **Integration Tests (`test_media_scrobbler_discord.py`)**:
   - Verify `MediaScrobbler` calls `discord_rpc.update_presence` on playing/pause and `clear_presence` on stop.
   - Verify toggling `enable_discord_rpc` disables updates and clears active presence.
