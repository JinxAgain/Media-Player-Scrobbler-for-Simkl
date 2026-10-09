import pytest
import requests
from unittest.mock import MagicMock
from simkl_mps.simkl_api import extract_title_and_year, search_movie, search_simkl_multi
from simkl_mps.media_scrobbler import MediaScrobbler


def test_extract_title_and_year_patterns():
    # Dot-separated scene names
    assert extract_title_and_year("Teki.Cometh.2024") == ("Teki Cometh", 2024)
    assert extract_title_and_year("42.Up.1998") == ("42 Up", 1998)

    # Standard parentheses
    assert extract_title_and_year("Teki Cometh (2024)") == ("Teki Cometh", 2024)
    assert extract_title_and_year("42 Up (1998)") == ("42 Up", 1998)

    # Square brackets
    assert extract_title_and_year("Teki Cometh [2024]") == ("Teki Cometh", 2024)

    # Titles with numbers that are not release years
    assert extract_title_and_year("2001: A Space Odyssey") == ("2001: A Space Odyssey", None)
    assert extract_title_and_year("1917") == ("1917", None)

    # Title ending in title number but with year in parentheses
    assert extract_title_and_year("Blade Runner 2049 (2017)") == ("Blade Runner 2049", 2017)


def test_search_movie_year_tolerance_fallback(monkeypatch):
    monkeypatch.setattr("simkl_mps.simkl_api.is_internet_connected", lambda: True)

    def fake_get(url, *args, **kwargs):
        params = kwargs.get("params", {})
        q = params.get("q", "")
        resp = MagicMock()
        resp.status_code = 200

        if "/search/movie" in url:
            if q == "42 Up (1998)":
                resp.json.return_value = []
            elif q == "42 Up (1999)":
                resp.json.return_value = [{
                    "title": "42 Up",
                    "year": 1999,
                    "ids": {"simkl_id": 77508}
                }]
            else:
                resp.json.return_value = []
        elif "/search/anime" in url:
            resp.json.return_value = []
        else:
            resp.json.return_value = []
        return resp

    monkeypatch.setattr(requests, "get", fake_get)

    result = search_movie("42 Up (1998)", client_id="fake_client", access_token="fake_token")
    assert result is not None
    assert "movie" in result
    movie = result["movie"]
    assert movie["title"] == "42 Up"
    assert movie["year"] == 1999
    assert movie["ids"]["simkl"] == 77508


def test_search_movie_year_tolerance_teki_cometh(monkeypatch):
    monkeypatch.setattr("simkl_mps.simkl_api.is_internet_connected", lambda: True)

    def fake_get(url, *args, **kwargs):
        params = kwargs.get("params", {})
        q = params.get("q", "")
        resp = MagicMock()
        resp.status_code = 200

        if "/search/movie" in url:
            if q == "Teki Cometh (2024)":
                resp.json.return_value = []
            elif q == "Teki Cometh (2025)":
                resp.json.return_value = [{
                    "title": "Teki Cometh",
                    "year": 2025,
                    "ids": {"simkl_id": 2592949}
                }]
            else:
                resp.json.return_value = []
        else:
            resp.json.return_value = []
        return resp

    monkeypatch.setattr(requests, "get", fake_get)

    result = search_movie("Teki Cometh (2024)", client_id="fake_client", access_token="fake_token")
    assert result is not None
    assert "movie" in result
    movie = result["movie"]
    assert movie["title"] == "Teki Cometh"
    assert movie["year"] == 2025
    assert movie["ids"]["simkl"] == 2592949


def test_search_simkl_multi_year_tolerance(monkeypatch):
    def fake_get(url, *args, **kwargs):
        params = kwargs.get("params", {})
        q = params.get("q", "")
        resp = MagicMock()
        resp.status_code = 200

        if "/search/movie" in url and q == "Teki Cometh (2025)":
            resp.json.return_value = [{
                "title": "Teki Cometh",
                "year": 2025,
                "ids": {"simkl_id": 2592949},
                "type": "movie"
            }]
        else:
            resp.json.return_value = []
        return resp

    monkeypatch.setattr(requests, "get", fake_get)

    results = search_simkl_multi("Teki Cometh (2024)", client_id="fake_client")
    assert len(results) == 1
    assert results[0]["title"] == "Teki Cometh"
    assert results[0]["year"] == 2025
    assert results[0]["simkl_id"] == 2592949


def test_media_scrobbler_identifies_movie_and_caches_both_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("simkl_mps.media_scrobbler.is_internet_connected", lambda: True)

    def fake_search_movie(title, client_id, access_token, file_path=None):
        if "Teki Cometh" in title:
            return {
                "movie": {
                    "title": "Teki Cometh",
                    "year": 2025,
                    "ids": {"simkl": 2592949}
                }
            }
        return None

    monkeypatch.setattr("simkl_mps.media_scrobbler.search_movie", fake_search_movie)

    scrobbler = MediaScrobbler(app_data_dir=tmp_path)
    scrobbler.client_id = "test_client"
    scrobbler.access_token = "test_token"
    scrobbler.currently_tracking = "Teki Cometh (2024)"
    scrobbler.current_filepath = "D:/Movies/Teki.Cometh.2024.1080p.mkv"

    scrobbler._identify_movie("Teki Cometh (2024)")

    assert scrobbler.simkl_id == 2592949
    assert scrobbler.movie_name == "Teki Cometh"
    assert scrobbler.year == 2025

    # Verify both title key and file key exist in media_cache
    title_cached = scrobbler.media_cache.get("teki cometh (2024)")
    file_cached = scrobbler.media_cache.get("teki.cometh.2024.1080p.mkv")

    assert title_cached is not None
    assert title_cached.get("simkl_id") == 2592949
    assert file_cached is not None
    assert file_cached.get("simkl_id") == 2592949
