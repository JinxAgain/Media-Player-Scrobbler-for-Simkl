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
    scrobbler.display_season = 2
    scrobbler.display_episode = 2
    scrobbler.simkl_id = 12345
    scrobbler.state = PLAYING
    scrobbler.current_position_seconds = 100
    scrobbler.total_duration_seconds = 3600

    scrobbler._sync_discord_presence()
    assert mock_rpc.update_presence.called
    kwargs = mock_rpc.update_presence.call_args[1]
    assert kwargs["title"] == "Succession"
    assert kwargs["media_type"] == "show"
    assert kwargs["season"] == 2
    assert kwargs["episode"] == 2
    assert kwargs["is_paused"] is False


@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_syncs_discord_on_paused(mock_rpc_cls, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.movie_name = "Inception"
    scrobbler.media_type = "movie"
    scrobbler.simkl_id = 472214
    scrobbler.state = PAUSED
    scrobbler.current_position_seconds = 500
    scrobbler.total_duration_seconds = 7200

    scrobbler._sync_discord_presence()
    assert mock_rpc.update_presence.called
    kwargs = mock_rpc.update_presence.call_args[1]
    assert kwargs["title"] == "Inception"
    assert kwargs["is_paused"] is True


@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_clears_discord_on_stop(mock_rpc_cls, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.state = STOPPED
    scrobbler._sync_discord_presence()
    assert mock_rpc.clear_presence.called


@patch("simkl_mps.media_scrobbler.get_setting")
@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_disabled_setting_clears_discord(mock_rpc_cls, mock_get_setting, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    def fake_get_setting(key, default=None):
        if key == "enable_discord_rpc":
            return False
        return default

    mock_get_setting.side_effect = fake_get_setting

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.movie_name = "Inception"
    scrobbler.state = PLAYING
    scrobbler._sync_discord_presence()
    assert mock_rpc.clear_presence.called
    assert not mock_rpc.update_presence.called


@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_resolves_poster_url(mock_rpc_cls, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.movie_name = "Inception"
    scrobbler.media_type = "movie"
    scrobbler.simkl_id = 472214
    scrobbler.state = PLAYING
    scrobbler.current_filepath = "C:/Videos/Inception.mkv"

    # Add cache entry with poster key
    scrobbler.media_cache.cache["Inception"] = {
        "title": "Inception",
        "poster": "47/472214posterkey"
    }

    scrobbler._sync_discord_presence()
    kwargs = mock_rpc.update_presence.call_args[1]
    assert kwargs["poster_url"] == "https://simkl.net/posters/47/472214posterkey_m.jpg"


@patch("simkl_mps.media_scrobbler.DiscordRPCManager")
def test_media_scrobbler_resolves_poster_via_simkl_id_lookup(mock_rpc_cls, tmp_path):
    mock_rpc = MagicMock()
    mock_rpc_cls.return_value = mock_rpc

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.movie_name = "Succession"
    scrobbler.media_type = "show"
    scrobbler.simkl_id = 739608
    scrobbler.state = PLAYING
    scrobbler.current_filepath = "V:/My Pack/Succession.S02E03.Hunting.1080p.mkv"

    # Cache is keyed by lowercase filename (as Simkl search does)
    scrobbler.media_cache.set("succession.s02e03.hunting.1080p.mkv", {
        "simkl_id": 739608,
        "movie_name": "Succession",
        "poster_url": "13/13667609b5f759c72f",
        "year": 2018
    })

    scrobbler._sync_discord_presence()
    kwargs = mock_rpc.update_presence.call_args[1]
    assert kwargs["poster_url"] == "https://simkl.net/posters/13/13667609b5f759c72f_m.jpg"
    assert kwargs["year"] == 2018

