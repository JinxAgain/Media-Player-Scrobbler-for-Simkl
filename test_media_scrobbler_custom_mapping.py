import pytest
from pathlib import Path
from simkl_mps.media_scrobbler import MediaScrobbler

def test_identify_uses_custom_mapping_first(tmp_path: Path):
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
    assert scrobbler.media_type == "anime"

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
    assert saved_rule is not None
    assert saved_rule["simkl_id"] == 2095944

def test_apply_manual_correction_when_playing(tmp_path: Path, monkeypatch):
    from simkl_mps import media_scrobbler
    from simkl_mps.utils.constants import PLAYING

    scrobbled_actions = []
    def fake_scrobble(action, item, progress, *args, **kwargs):
        scrobbled_actions.append((action, progress))
        return {"ok": True}

    monkeypatch.setattr(media_scrobbler, "scrobble", fake_scrobble)
    monkeypatch.setattr(media_scrobbler, "is_internet_connected", lambda: True)

    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id", access_token="token")
    scrobbler.current_filepath = "D:/Videos/frieren_01.mkv"
    scrobbler.currently_tracking = "frieren_01.mkv"
    scrobbler.state = PLAYING
    scrobbler.current_position_seconds = 600
    scrobbler.total_duration_seconds = 1200

    success = scrobbler.apply_manual_correction(
        simkl_id=2095944,
        media_type="anime",
        title="Frieren",
        season=1,
        episode=1
    )

    assert success is True
    assert len(scrobbled_actions) == 1
    assert scrobbled_actions[0][0] == "start"
    assert scrobbled_actions[0][1] == 50.0  # 600 / 1200 = 50%


def test_unidentified_media_sends_notification_and_sets_cooldown(tmp_path: Path, monkeypatch):
    from simkl_mps import media_scrobbler
    monkeypatch.setattr(media_scrobbler, "search_movie", lambda *args, **kwargs: None)
    monkeypatch.setattr(media_scrobbler, "is_internet_connected", lambda: True)

    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id", access_token="test_token")
    scrobbler.current_filepath = "D:/Videos/unknown_film.mkv"
    scrobbler.currently_tracking = "unknown film"

    notifications = []
    scrobbler.set_notification_callback(lambda title, msg: notifications.append((title, msg)))

    scrobbler._identify_movie("unknown film")

    assert "unknown film" in scrobbler._failed_identification_attempts
    assert "unknown_film.mkv" in scrobbler._failed_identification_attempts
    assert len(notifications) == 1
    assert "Unidentified" in notifications[0][0]
    assert "unknown film" in notifications[0][1]

def test_update_playback_state_debounces_failed_search(tmp_path: Path, monkeypatch):
    from simkl_mps import media_scrobbler
    search_calls = []
    monkeypatch.setattr(media_scrobbler, "search_movie", lambda *args, **kwargs: search_calls.append(True) or None)
    monkeypatch.setattr(media_scrobbler, "is_internet_connected", lambda: True)

    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id", access_token="test_token")
    scrobbler.current_filepath = "D:/Videos/unknown_film.mkv"
    scrobbler.currently_tracking = "unknown film"
    scrobbler.media_type = "movie"

    # Simulate that it already failed recently
    import time
    scrobbler._failed_identification_attempts["unknown_film.mkv"] = time.time()
    scrobbler._failed_identification_attempts["unknown film"] = time.time()

    # Call _update_tracking
    scrobbler.last_update_time = time.time() - 1
    scrobbler._update_tracking(window_info={'title': 'unknown film'})

    # Search should NOT have been called due to cooldown
    assert len(search_calls) == 0


def test_show_rule_overrides_stale_media_cache_on_start_new_media_item(tmp_path: Path):
    """
    Regression test: When media_cache has a stale match for episode 6,
    a custom show rule created on episode 4 must take precedence over media_cache.
    """
    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id")

    ep6_filename = "Succession.S02E06.Argestes.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb.mkv"
    ep6_path = f"V:/My Pack/Succession.S02.1080p.AMZN.WEBRip.DDP5.1.x264-NTb[rartv]/{ep6_filename}"

    # Pre-populate media_cache with the old/wrong detection (Succession ID 739608)
    scrobbler.media_cache.set(ep6_filename.lower(), {
        "simkl_id": 739608,
        "movie_name": "Succession",
        "type": "show",
        "season": 2,
        "episode": 6,
        "source": "simkl_api"
    })

    # Add custom show rule pointing to Community (ID 15495)
    scrobbler.custom_mappings.add_show_rule(
        match_key="succession.s02.1080p.amzn.webrip.ddp5.1.x264-ntb[rartv]",
        simkl_id=15495,
        media_type="show",
        title="Community",
        default_season=2,
        folder_keyword="succession.s02.1080p.amzn.webrip.ddp5.1.x264-ntb[rartv]",
        poster_url="https://simkl.net/posters/test_poster_m.jpg"
    )

    # Start tracking new media item for episode 6
    scrobbler._start_new_media_item(
        raw_title="Succession S02E06",
        filepath=ep6_path,
        initial_media_type_guess="episode",
        guessit_info={"title": "Succession", "season": 2, "episode": 6, "type": "episode"}
    )

    # Must match the custom show rule (Community ID 15495), NOT the stale cache (739608)
    assert scrobbler.simkl_id == 15495
    assert scrobbler.movie_name == "Community"
    assert scrobbler.media_type == "show"
    assert scrobbler.season == 2
    assert scrobbler.episode == 6

    # Verify media_cache was updated with the corrected show rule result
    cached_now = scrobbler.media_cache.get(ep6_filename.lower())
    assert cached_now is not None
    assert cached_now["simkl_id"] == 15495
    assert cached_now["movie_name"] == "Community"


def test_manual_correction_normalizes_poster_and_pushes_to_discord(tmp_path: Path):
    """
    Regression test: Manual correction must normalize raw poster hashes
    into full Simkl CDN URLs and immediately push them to Discord RPC.
    """
    scrobbler = MediaScrobbler(app_data_dir=tmp_path, client_id="test_id")
    scrobbler.current_filepath = "V:/My Pack/42.up.1998.part2.1080p.bluray.x264-usury.mkv"
    scrobbler.currently_tracking = "42 up (1998)"
    from simkl_mps.utils.constants import PLAYING
    scrobbler.state = PLAYING

    # Mock Discord RPC
    class MockDiscordRPC:
        def __init__(self):
            self.last_update = None
        def update_presence(self, **kwargs):
            self.last_update = kwargs
            return True
        def clear_presence(self):
            pass

    mock_rpc = MockDiscordRPC()
    scrobbler.discord_rpc = mock_rpc

    # Apply manual correction with a raw relative poster hash
    success = scrobbler.apply_manual_correction(
        simkl_id=77508,
        media_type="movie",
        title="42 Up",
        year=1999,
        poster_url="20/20035305560d0e0a35"
    )

    assert success is True
    expected_poster_url = "https://simkl.net/posters/20/20035305560d0e0a35_m.jpg"
    assert scrobbler.poster_url == expected_poster_url

    # Check Discord RPC received the full URL with force=True
    assert mock_rpc.last_update is not None
    assert mock_rpc.last_update["poster_url"] == expected_poster_url
    assert mock_rpc.last_update["force"] is True


