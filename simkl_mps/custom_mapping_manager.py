"""
Custom mapping manager for Media Player Scrobbler for SIMKL.
Handles persistent user overrides and two-tier media matching rules.
"""

import os
import re
import json
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class CustomMappingManager:
    """Manages persistent custom media mappings and rules."""

    def __init__(self, app_data_dir: Path, filename: str = "custom_mappings.json"):
        self.app_data_dir = Path(app_data_dir)
        self.file_path = self.app_data_dir / filename
        self._lock = threading.Lock()
        self.data = self._load()

    def _default_data(self) -> dict:
        return {
            "version": 1,
            "exact_files": {},
            "show_rules": {}
        }

    def _load(self) -> dict:
        """Load mappings from disk or initialize clean data if missing/corrupt."""
        if not self.file_path.exists():
            return self._default_data()

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    loaded.setdefault("version", 1)
                    loaded.setdefault("exact_files", {})
                    loaded.setdefault("show_rules", {})
                    return loaded
                logger.warning(f"Unexpected data format in {self.file_path}. Resetting.")
        except Exception as e:
            logger.error(f"Failed to read custom mappings file {self.file_path}: {e}")
            try:
                corrupt_backup = self.file_path.with_suffix(".json.corrupted")
                if self.file_path.exists():
                    self.file_path.replace(corrupt_backup)
                    logger.info(f"Backed up corrupted mapping file to {corrupt_backup}")
            except Exception as backup_err:
                logger.error(f"Failed to backup corrupted mapping file: {backup_err}")

        return self._default_data()

    def _save(self) -> None:
        """Persist mapping data atomically to disk."""
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = self.file_path.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            tmp_file.replace(self.file_path)
        except Exception as e:
            logger.error(f"Error saving custom mappings to {self.file_path}: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def get_all(self) -> dict:
        """Return a copy of the entire mappings data structure."""
        with self._lock:
            return json.loads(json.dumps(self.data))

    def clear(self) -> None:
        """Clear all custom mapping rules."""
        with self._lock:
            self.data = self._default_data()
            self._save()

    def add_exact_mapping(
        self,
        filename_or_path: str,
        simkl_id: int,
        media_type: str,
        title: str,
        season: int | None = None,
        episode: int | None = None,
        poster_url: str | None = None,
        year: int | None = None
    ) -> dict:
        """
        Add or update an exact file mapping.
        """
        key = os.path.basename(filename_or_path).lower().strip()
        if poster_url and isinstance(poster_url, str):
            poster_url = poster_url.strip()
            if poster_url and not poster_url.startswith("http://") and not poster_url.startswith("https://"):
                poster_url = f"https://simkl.net/posters/{poster_url}_m.jpg"

        record = {
            "simkl_id": int(simkl_id),
            "type": media_type.lower().strip(),
            "title": title.strip(),
            "season": season,
            "episode": episode,
            "poster_url": poster_url,
            "year": year,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        with self._lock:
            self.data["exact_files"][key] = record
            self._save()
        logger.info(f"Custom mapping added for exact file '{key}' -> Simkl ID {simkl_id}")
        return record

    def add_show_rule(
        self,
        match_key: str,
        simkl_id: int,
        media_type: str,
        title: str,
        default_season: int = 1,
        folder_keyword: str | None = None,
        poster_url: str | None = None
    ) -> dict:
        """
        Add or update a series-level rule applied to all matching episodes.
        """
        key = match_key.lower().strip()
        if poster_url and isinstance(poster_url, str):
            poster_url = poster_url.strip()
            if poster_url and not poster_url.startswith("http://") and not poster_url.startswith("https://"):
                poster_url = f"https://simkl.net/posters/{poster_url}_m.jpg"

        rule = {
            "simkl_id": int(simkl_id),
            "type": media_type.lower().strip(),
            "title": title.strip(),
            "default_season": default_season if default_season is not None else 1,
            "folder_keyword": folder_keyword.lower().strip() if folder_keyword else key,
            "poster_url": poster_url,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        with self._lock:
            self.data["show_rules"][key] = rule
            self._save()
        logger.info(f"Custom show rule added for '{key}' -> Simkl ID {simkl_id}")
        return rule

    def remove_exact_mapping(self, filename_or_path: str) -> bool:
        """Remove an exact file mapping."""
        key = os.path.basename(filename_or_path).lower().strip()
        with self._lock:
            if key in self.data["exact_files"]:
                del self.data["exact_files"][key]
                self._save()
                logger.info(f"Removed custom mapping for exact file '{key}'")
                return True
        return False

    def remove_show_rule(self, match_key: str) -> bool:
        """Remove a series-level rule."""
        key = match_key.lower().strip()
        with self._lock:
            if key in self.data["show_rules"]:
                del self.data["show_rules"][key]
                self._save()
                logger.info(f"Removed custom show rule for '{key}'")
                return True
        return False

    def resolve(
        self,
        filepath: str | None,
        raw_title: str | None = None,
        guessit_info: dict | None = None
    ) -> dict | None:
        """
        Resolve custom mapping for a video file or title.
        Priority:
          1. Exact file match (exact_files)
          2. Show rule match (show_rules)
        """
        with self._lock:
            exact_files = self.data.get("exact_files", {})
            show_rules = self.data.get("show_rules", {})

            # 1. Tier 1: Check exact file mapping
            if filepath:
                exact_key = os.path.basename(filepath).lower().strip()
                if exact_key in exact_files:
                    match = exact_files[exact_key].copy()
                    match["matched_by"] = "exact_file"
                    return match

            if raw_title:
                exact_raw_key = raw_title.lower().strip()
                if exact_raw_key in exact_files:
                    match = exact_files[exact_raw_key].copy()
                    match["matched_by"] = "exact_file"
                    return match

            # 2. Tier 2: Check show rules
            candidates = []
            if guessit_info and isinstance(guessit_info, dict):
                title_guess = guessit_info.get("title")
                if title_guess:
                    candidates.append(str(title_guess).lower().strip())

            if filepath:
                parent_dir = os.path.basename(os.path.dirname(filepath)).lower().strip()
                if parent_dir:
                    candidates.append(parent_dir)

            if raw_title:
                candidates.append(raw_title.lower().strip())

            norm_fp = filepath.lower().replace('\\', '/') if filepath else ""

            for rule_key, rule in show_rules.items():
                folder_kw = rule.get("folder_keyword", rule_key).lower().strip()
                matched = False

                # 1. Full path contains folder keyword (e.g. parent folder or series directory)
                if norm_fp and folder_kw and len(folder_kw) >= 3 and folder_kw in norm_fp:
                    matched = True

                # 2. Check candidates against rule key or folder keyword
                if not matched:
                    for candidate in candidates:
                        if not candidate or len(candidate) < 2:
                            continue
                        if rule_key == candidate or rule_key in candidate or (len(candidate) >= 3 and candidate in rule_key):
                            matched = True
                            break
                        if folder_kw and (folder_kw == candidate or folder_kw in candidate or (len(candidate) >= 3 and candidate in folder_kw)):
                            matched = True
                            break

                if matched:
                    result = rule.copy()
                    result["matched_by"] = "show_rule"

                    # Normalize poster_url if needed
                    p_url = result.get("poster_url")
                    if p_url and isinstance(p_url, str) and not p_url.startswith("http://") and not p_url.startswith("https://"):
                        result["poster_url"] = f"https://simkl.net/posters/{p_url}_m.jpg"

                    # Extract episode dynamically from guessit or filename
                    extracted_episode = None
                    extracted_season = None
                    if guessit_info and isinstance(guessit_info, dict):
                        extracted_episode = guessit_info.get("episode")
                        extracted_season = guessit_info.get("season")

                    if extracted_episode is None and filepath:
                        filename = os.path.basename(filepath)
                        m = re.search(r'[sS](\d{1,3})[eE](\d{1,4})', filename)
                        if m:
                            extracted_season = int(m.group(1))
                            extracted_episode = int(m.group(2))
                        else:
                            m2 = re.search(r'(\d{1,3})x(\d{1,4})', filename)
                            if m2:
                                extracted_season = int(m2.group(1))
                                extracted_episode = int(m2.group(2))
                            else:
                                m3 = re.search(r'[eE](\d{1,4})', filename)
                                if m3:
                                    extracted_episode = int(m3.group(1))

                    if extracted_episode is None and raw_title:
                        m = re.search(r'[sS](\d{1,3})[eE](\d{1,4})', raw_title)
                        if m:
                            extracted_season = int(m.group(1))
                            extracted_episode = int(m.group(2))

                    result["episode"] = extracted_episode
                    result["season"] = extracted_season if extracted_season is not None else rule.get("default_season", 1)
                    result["season_display"] = result["season"]
                    result["episode_display"] = result["episode"]
                    return result

        return None
