import pytest
from simkl_mps.simkl_api import parse_simkl_url, search_simkl_multi

def test_parse_simkl_url_valid_formats():
    assert parse_simkl_url("https://simkl.com/anime/2095944/sousou-no-frieren") == ("anime", 2095944)
    assert parse_simkl_url("https://simkl.com/tv/1690042/shogun") == ("show", 1690042)
    assert parse_simkl_url("https://simkl.com/movies/12345/dune") == ("movie", 12345)
    assert parse_simkl_url("https://simkl.com/movie/12345/dune") == ("movie", 12345)
    assert parse_simkl_url("simkl.com/anime/2095944") == ("anime", 2095944)
    assert parse_simkl_url("http://simkl.com/tv/999/") == ("show", 999)

def test_parse_simkl_url_invalid():
    assert parse_simkl_url("https://www.imdb.com/title/tt1234567/") is None
    assert parse_simkl_url("not a url") is None
    assert parse_simkl_url("") is None
    assert parse_simkl_url(None) is None

def test_search_simkl_multi(monkeypatch):
    def fake_get(url, *args, **kwargs):
        class FakeResponse:
            status_code = 200
            def json(self):
                if "/search/anime" in url:
                    return [{"ids": {"simkl": 2095944}, "title": "Frieren", "year": 2023, "type": "anime"}]
                elif "/search/tv" in url:
                    return [{"ids": {"simkl": 3001}, "title": "Breaking Bad", "year": 2008, "type": "show"}]
                elif "/search/movie" in url:
                    return [{"ids": {"simkl": 4001}, "title": "Inception", "year": 2010, "type": "movie"}]
                return []
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    results = search_simkl_multi("query", client_id="fake_client_id")
    assert len(results) == 3
    ids = [r["simkl_id"] for r in results]
    assert 2095944 in ids
    assert 3001 in ids
    assert 4001 in ids
    types = {r["type"] for r in results}
    assert "anime" in types
    assert "show" in types
    assert "movie" in types
