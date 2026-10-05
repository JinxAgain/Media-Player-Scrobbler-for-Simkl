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
    assert "start" in payload["timestamps"]
    assert "end" in payload["timestamps"]
    assert payload["large_image"] == "https://simkl.net/posters/test_m.jpg"
    assert payload["large_text"] == "Inception"
    assert payload["small_image"] is None
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
    assert payload["buttons"][0]["label"] == "View on Simkl"
    assert payload["buttons"][0]["url"] == "https://simkl.com/tv/12345"

def test_format_payload_anime_playing():
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    payload = mgr._build_payload(
        title="Demon Slayer",
        year=2019,
        media_type="anime",
        season=1,
        episode=1,
        episode_title="Cruelty",
        current_position=120.0,
        total_duration=1440.0,
        poster_url="https://simkl.net/posters/anime_m.jpg",
        simkl_id=831411,
        is_paused=False
    )
    assert payload["details"] == "Demon Slayer (2019)"
    assert payload["state"] == "S01E01 · Cruelty"
    assert "start" in payload["timestamps"]
    assert "end" in payload["timestamps"]
    assert payload["buttons"][0]["url"] == "https://simkl.com/anime/831411"

def test_format_payload_fallback_no_year():
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    payload = mgr._build_payload(
        title="Unknown Film",
        year=None,
        media_type="movie",
        season=None,
        episode=None,
        episode_title=None,
        current_position=None,
        total_duration=None,
        poster_url=None,
        simkl_id=None,
        is_paused=False
    )
    assert payload["details"] == "Unknown Film"
    assert payload["state"] == "Watching"
    assert "timestamps" not in payload or payload["timestamps"] is None
    assert "buttons" not in payload or not payload["buttons"]

def test_connect_handles_discord_not_running():
    with patch("pypresence.Presence.connect", side_effect=Exception("Discord not found")):
        mgr = DiscordRPCManager(client_id="1556713709462880316")
        assert mgr.connect() is False
        assert mgr.is_connected is False

def test_update_presence_handles_pipe_closed():
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    mock_presence = MagicMock()
    mock_presence.update.side_effect = Exception("Pipe closed")
    mgr._presence = mock_presence
    mgr.is_connected = True

    result = mgr.update_presence(
        title="Inception",
        year=2010,
        media_type="movie",
        season=None,
        episode=None,
        episode_title=None,
        current_position=100.0,
        total_duration=1000.0,
        poster_url=None,
        simkl_id=123
    )
    assert result is False
    assert mgr.is_connected is False

def test_clear_presence():
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    mock_presence = MagicMock()
    mgr._presence = mock_presence
    mgr.is_connected = True

    assert mgr.clear_presence() is True
    assert mock_presence.clear.called

def test_update_presence_passes_watching_and_timestamps():
    from pypresence import ActivityType
    mgr = DiscordRPCManager(client_id="1556713709462880316")
    mock_presence = MagicMock()
    mgr._presence = mock_presence
    mgr.is_connected = True

    result = mgr.update_presence(
        title="Succession",
        year=2018,
        media_type="show",
        season=2,
        episode=3,
        episode_title="Hunting",
        current_position=289.0,
        total_duration=3673.0,
        poster_url="https://simkl.net/posters/13/13667609b5f759c72f_m.jpg",
        simkl_id=739608,
        is_paused=False
    )
    assert result is True
    assert mock_presence.update.called
    kwargs = mock_presence.update.call_args[1]
    assert kwargs["activity_type"] == ActivityType.WATCHING
    assert kwargs["details"] == "Succession (2018)"
    assert kwargs["state"] == "S02E03 · Hunting"
    assert "start" in kwargs and "end" in kwargs
    assert kwargs["large_image"] == "https://simkl.net/posters/13/13667609b5f759c72f_m.jpg"
    assert kwargs["buttons"][0]["label"] == "View on Simkl"
    assert kwargs["buttons"][0]["url"] == "https://simkl.com/tv/739608"

