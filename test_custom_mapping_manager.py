import json
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
    assert result["year"] == 2024

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
    assert result["title"] == "Frieren: Beyond Journey's End"
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
    assert result is not None
    assert result["simkl_id"] == 999999
    assert result["title"] == "Frieren Special"

def test_remove_mappings(tmp_path: Path):
    manager = CustomMappingManager(tmp_path)
    manager.add_exact_mapping("sample.mkv", 123, "movie", "Sample")
    manager.add_show_rule("sample_show", 456, "show", "Sample Show")
    
    assert manager.remove_exact_mapping("sample.mkv") is True
    assert manager.remove_exact_mapping("non_existent.mkv") is False
    assert manager.remove_show_rule("sample_show") is True
    assert manager.remove_show_rule("non_existent") is False
    assert manager.resolve("sample.mkv") is None

def test_persistence_reload(tmp_path: Path):
    m1 = CustomMappingManager(tmp_path)
    m1.add_exact_mapping("movie.mkv", 101, "movie", "Movie 101")
    m1.add_show_rule("series_a", 202, "anime", "Series A")

    # Load in new instance
    m2 = CustomMappingManager(tmp_path)
    exact = m2.resolve("movie.mkv")
    show = m2.resolve("D:/series_a/ep01.mkv", guessit_info={"title": "series_a", "episode": 1})
    assert exact is not None and exact["simkl_id"] == 101
    assert show is not None and show["simkl_id"] == 202

def test_corrupt_file_recovery(tmp_path: Path):
    corrupt_file = tmp_path / "custom_mappings.json"
    corrupt_file.write_text("{invalid_json: true", encoding="utf-8")
    manager = CustomMappingManager(tmp_path)
    data = manager.get_all()
    assert data == {"version": 1, "exact_files": {}, "show_rules": {}}
    assert (tmp_path / "custom_mappings.json.corrupted").exists()
