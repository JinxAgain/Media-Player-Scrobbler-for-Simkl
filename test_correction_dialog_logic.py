import pytest
from simkl_mps.correction_dialog import CorrectionDialogController

def test_resolve_input_with_url(monkeypatch):
    from simkl_mps import simkl_api
    monkeypatch.setattr(
        simkl_api,
        "get_show_details",
        lambda simkl_id, *args, **kwargs: {"title": "Frieren", "type": "anime", "ids": {"simkl": simkl_id}, "year": 2023}
    )

    result = CorrectionDialogController.resolve_input(
        "https://simkl.com/anime/2095944/frieren",
        client_id="test_client",
        access_token="test_token"
    )
    assert result["mode"] == "direct"
    assert result["item"]["simkl_id"] == 2095944
    assert result["item"]["title"] == "Frieren"
    assert result["item"]["type"] == "anime"

def test_resolve_input_with_numeric_id(monkeypatch):
    from simkl_mps import simkl_api
    monkeypatch.setattr(simkl_api, "get_show_details", lambda simkl_id, *args, **kwargs: None)
    monkeypatch.setattr(
        simkl_api,
        "get_movie_details",
        lambda simkl_id, *args, **kwargs: {"title": "Dune", "type": "movie", "ids": {"simkl": simkl_id}, "year": 2021}
    )

    result = CorrectionDialogController.resolve_input(
        "12345",
        client_id="test_client",
        access_token="test_token"
    )
    assert result["mode"] == "direct"
    assert result["item"]["simkl_id"] == 12345
    assert result["item"]["title"] == "Dune"

def test_resolve_input_with_search_query(monkeypatch):
    from simkl_mps import simkl_api
    monkeypatch.setattr(
        simkl_api,
        "search_simkl_multi",
        lambda query, *args, **kwargs: [{"simkl_id": 999, "title": "SearchResult", "type": "anime", "year": 2024}]
    )

    result = CorrectionDialogController.resolve_input(
        "frieren",
        client_id="test_client",
        access_token="test_token"
    )
    assert result["mode"] == "search"
    assert len(result["results"]) == 1
    assert result["results"][0]["simkl_id"] == 999

def test_build_correction_payload_movie():
    selected = {"simkl_id": 1690042, "type": "movie", "title": "Dune: Part Two", "year": 2024}
    payload = CorrectionDialogController.build_correction_payload(
        selected_item=selected,
        season_str="1",
        episode_str="5",
        apply_to_series=True
    )
    assert payload["simkl_id"] == 1690042
    assert payload["media_type"] == "movie"
    assert payload["season"] is None
    assert payload["episode"] is None
    assert payload["apply_to_series"] is False

def test_build_correction_payload_show():
    selected = {"simkl_id": 2095944, "type": "anime", "title": "Frieren", "year": 2023}
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

def test_show_correction_window_viewable_with_withdrawn_parent():
    import tkinter as tk
    from unittest.mock import MagicMock
    from simkl_mps.correction_dialog import show_correction_window

    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip(f"Tkinter not available or failed to initialize: {e}")
    root.withdraw()

    mock_scrobbler = MagicMock()
    mock_scrobbler.current_filepath = "test_movie.mkv"
    mock_scrobbler.movie_name = "Test Movie"
    mock_scrobbler.client_id = "test_client"
    mock_scrobbler.access_token = "test_token"

    win = show_correction_window(parent_root=root, scrobbler=mock_scrobbler)
    win.update()

    try:
        assert win.winfo_viewable() == 1
    finally:
        win.destroy()
        root.destroy()

def test_show_correction_window_ui_english():
    import tkinter as tk
    from unittest.mock import MagicMock
    from simkl_mps.correction_dialog import show_correction_window

    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip(f"Tkinter not available or failed to reinitialize: {e}")
    root.withdraw()

    mock_scrobbler = MagicMock()
    mock_scrobbler.current_filepath = "test_movie.mkv"
    mock_scrobbler.movie_name = "Test Movie"
    mock_scrobbler.client_id = "test_client"
    mock_scrobbler.access_token = "test_token"

    win = show_correction_window(parent_root=root, scrobbler=mock_scrobbler)
    win.update()

    try:
        assert win.title() == "Correct Simkl Media"
        assert "修正" not in win.title()
    finally:
        win.destroy()
        root.destroy()


