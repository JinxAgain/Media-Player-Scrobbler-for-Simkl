"""
Correction Dialog module for Media Player Scrobbler for SIMKL.
Provides a native Tkinter interface to search, verify, and correct media matches.
"""

import os
import re
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable

from simkl_mps import simkl_api

logger = logging.getLogger(__name__)

class CorrectionDialogController:
    """Controller logic for parsing inputs and building correction payloads."""

    @staticmethod
    def resolve_input(input_str: str, client_id: str, access_token: str | None = None) -> dict:
        """
        Resolve user input which could be a Simkl URL, a numerical ID, or a title search query.
        Returns:
            {"mode": "direct", "item": {...}} or {"mode": "search", "results": [...]}
        """
        if not input_str or not input_str.strip():
            return {"mode": "empty", "results": []}

        text = input_str.strip()

        # 1. Check for Simkl URL
        parsed_url = simkl_api.parse_simkl_url(text)
        if parsed_url:
            media_type, simkl_id = parsed_url
            details = None
            try:
                if media_type in ('show', 'anime'):
                    details = simkl_api.get_show_details(simkl_id, client_id, access_token)
                else:
                    details = simkl_api.get_movie_details(simkl_id, client_id, access_token)
            except Exception as e:
                logger.warning(f"Error fetching details for URL Simkl ID {simkl_id}: {e}")

            if not details:
                details = {"title": f"Simkl ID {simkl_id}", "type": media_type, "ids": {"simkl": simkl_id}}

            item_type = details.get("type") or media_type
            if item_type == "tv":
                item_type = "show"

            poster_val = details.get("poster_url") or details.get("poster")
            if poster_val and isinstance(poster_val, str):
                poster_val = poster_val.strip()
                if poster_val and not poster_val.startswith("http://") and not poster_val.startswith("https://"):
                    poster_val = f"https://simkl.net/posters/{poster_val}_m.jpg"

            item = {
                "simkl_id": simkl_id,
                "type": item_type,
                "title": details.get("title", f"ID {simkl_id}"),
                "year": details.get("year"),
                "poster_url": poster_val
            }
            return {"mode": "direct", "item": item}

        # 2. Check for numeric ID
        if text.isdigit():
            simkl_id = int(text)
            details = None
            try:
                # Try show first, then movie
                details = simkl_api.get_show_details(simkl_id, client_id, access_token)
                if not details or not details.get("title"):
                    details = simkl_api.get_movie_details(simkl_id, client_id, access_token)
            except Exception as e:
                logger.warning(f"Error fetching details for numeric ID {simkl_id}: {e}")

            if not details:
                details = {"title": f"Simkl ID {simkl_id}", "type": "anime", "ids": {"simkl": simkl_id}}

            item_type = details.get("type", "anime")
            if item_type == "tv":
                item_type = "show"

            poster_val = details.get("poster_url") or details.get("poster")
            if poster_val and isinstance(poster_val, str):
                poster_val = poster_val.strip()
                if poster_val and not poster_val.startswith("http://") and not poster_val.startswith("https://"):
                    poster_val = f"https://simkl.net/posters/{poster_val}_m.jpg"

            item = {
                "simkl_id": simkl_id,
                "type": item_type,
                "title": details.get("title", f"ID {simkl_id}"),
                "year": details.get("year"),
                "poster_url": poster_val
            }
            return {"mode": "direct", "item": item}

        # 3. Fallback to keyword search
        results = simkl_api.search_simkl_multi(text, client_id, access_token)
        return {"mode": "search", "results": results}

    @staticmethod
    def build_correction_payload(
        selected_item: dict,
        season_str: str | None,
        episode_str: str | None,
        apply_to_series: bool
    ) -> dict:
        """Construct the parameter dictionary for MediaScrobbler.apply_manual_correction."""
        media_type = selected_item.get("type", "movie").lower()
        if media_type == "tv":
            media_type = "show"

        is_movie = media_type == "movie"

        season = None
        episode = None
        if not is_movie:
            if season_str and str(season_str).strip().isdigit():
                season = int(season_str.strip())
            if episode_str and str(episode_str).strip().isdigit():
                episode = int(episode_str.strip())

        poster_url = selected_item.get("poster_url")
        if poster_url and isinstance(poster_url, str):
            poster_url = poster_url.strip()
            if poster_url and not poster_url.startswith("http://") and not poster_url.startswith("https://"):
                poster_url = f"https://simkl.net/posters/{poster_url}_m.jpg"

        return {
            "simkl_id": int(selected_item["simkl_id"]),
            "media_type": media_type,
            "title": selected_item.get("title", "Unknown"),
            "season": season,
            "episode": episode,
            "year": selected_item.get("year"),
            "poster_url": poster_url,
            "apply_to_series": apply_to_series and not is_movie
        }


def show_correction_window(
    parent_root: tk.Tk | tk.Toplevel | None,
    scrobbler: Any,
    on_success_callback: Callable[[], None] | None = None
) -> tk.Toplevel | tk.Tk:
    """
    Open the modal manual correction dialog.
    """
    if parent_root is None:
        win = tk.Tk()
    else:
        win = tk.Toplevel(parent_root)

    win.title("Correct Simkl Media")
    win.geometry("540x520")
    win.minsize(480, 420)

    # Only set transient if parent_root is an active, viewable window.
    # If parent_root is withdrawn (e.g. tray background Tk root), setting transient
    # causes the Windows OS window manager to keep the child Toplevel hidden (winfo_viewable() == 0).
    try:
        if parent_root and parent_root.winfo_exists() and parent_root.winfo_viewable():
            win.transient(parent_root)
    except Exception:
        pass

    win.deiconify()
    win.attributes("-topmost", True)
    win.lift()
    win.focus_force()

    # Data variables
    selected_candidate: dict | None = None
    search_results_cache: list[dict] = []

    # Current context info
    current_filepath = getattr(scrobbler, "current_filepath", None)
    current_title = getattr(scrobbler, "movie_name", None) or getattr(scrobbler, "currently_tracking", None)
    current_id = getattr(scrobbler, "simkl_id", None)
    current_season = getattr(scrobbler, "season", None) or getattr(scrobbler, "_season_guess_from_filename", None) or 1
    current_episode = getattr(scrobbler, "episode", None) or getattr(scrobbler, "_episode_guess_from_filename", None) or 1

    filename_display = os.path.basename(current_filepath) if current_filepath else (current_title or "No active file")

    # Header Frame
    header_frame = ttk.LabelFrame(win, text="Active Video Info", padding=8)
    header_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

    file_label = ttk.Label(header_frame, text=f"File: {filename_display}", font=("Segoe UI", 9, "bold"))
    file_label.pack(anchor=tk.W)

    if current_id:
        status_str = f"Matched: {current_title} (ID: {current_id})"
    elif current_title:
        status_str = f"Status: Unidentified / No Simkl ID (Detected: {current_title})"
    else:
        status_str = "Status: Unidentified / No Simkl ID"
    match_label = ttk.Label(header_frame, text=status_str, foreground="#2b579a")
    match_label.pack(anchor=tk.W)

    # Search & Input Frame
    search_frame = ttk.LabelFrame(win, text="1. Search or Enter Simkl Item", padding=8)
    search_frame.pack(fill=tk.X, padx=10, pady=5)

    input_row = ttk.Frame(search_frame)
    input_row.pack(fill=tk.X, pady=2)

    search_var = tk.StringVar()
    if current_title and current_title != "None":
        search_var.set(current_title)

    search_entry = ttk.Entry(input_row, textvariable=search_var)
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

    search_status_label = ttk.Label(search_frame, text="Enter keyword, Simkl URL, or ID, then click Search.", font=("Segoe UI", 8), foreground="#666666")
    search_status_label.pack(anchor=tk.W, pady=(2, 0))

    # Candidate Listbox Frame
    list_frame = ttk.Frame(win, padding=(10, 0))
    list_frame.pack(fill=tk.BOTH, expand=True)

    candidates_listbox = tk.Listbox(
        list_frame,
        height=5,
        font=("Segoe UI", 9),
        selectmode=tk.SINGLE,
        exportselection=False
    )
    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=candidates_listbox.yview)
    candidates_listbox.configure(yscrollcommand=scrollbar.set)
    candidates_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Season & Episode Frame
    season_frame = ttk.LabelFrame(win, text="2. Season & Episode Calibration", padding=8)
    season_frame.pack(fill=tk.X, padx=10, pady=5)

    se_row = ttk.Frame(season_frame)
    se_row.pack(fill=tk.X, pady=2)

    season_label = ttk.Label(se_row, text="Season:")
    season_label.pack(side=tk.LEFT, padx=(0, 5))
    season_var = tk.StringVar(value=str(current_season))
    season_entry = ttk.Entry(se_row, textvariable=season_var, width=6)
    season_entry.pack(side=tk.LEFT, padx=(0, 15))

    episode_label = ttk.Label(se_row, text="Episode:")
    episode_label.pack(side=tk.LEFT, padx=(0, 5))
    episode_var = tk.StringVar(value=str(current_episode))
    episode_entry = ttk.Entry(se_row, textvariable=episode_var, width=6)
    episode_entry.pack(side=tk.LEFT)

    series_rule_var = tk.BooleanVar(value=True)
    series_rule_check = ttk.Checkbutton(
        season_frame,
        text="Apply to all episodes of this show",
        variable=series_rule_var
    )
    series_rule_check.pack(anchor=tk.W, pady=(4, 0))

    def on_candidate_selected(event=None):
        nonlocal selected_candidate
        selection = candidates_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        if idx < len(search_results_cache):
            selected_candidate = search_results_cache[idx]
            media_type = selected_candidate.get("type", "movie").lower()
            if media_type == "movie":
                season_entry.configure(state=tk.DISABLED)
                episode_entry.configure(state=tk.DISABLED)
                series_rule_check.configure(state=tk.DISABLED)
            else:
                season_entry.configure(state=tk.NORMAL)
                episode_entry.configure(state=tk.NORMAL)
                series_rule_check.configure(state=tk.NORMAL)
            search_status_label.configure(
                text=f"Selected: {selected_candidate.get('title')} (ID: {selected_candidate.get('simkl_id')})",
                foreground="#008800"
            )

    candidates_listbox.bind("<<ListboxSelect>>", on_candidate_selected)
    candidates_listbox.bind("<ButtonRelease-1>", on_candidate_selected)

    def do_search():
        query = search_var.get().strip()
        if not query:
            return

        search_btn.configure(state=tk.DISABLED)
        search_status_label.configure(text="Searching Simkl...", foreground="#2b579a")
        candidates_listbox.delete(0, tk.END)

        def _bg_task():
            client_id = getattr(scrobbler, "client_id", None)
            access_token = getattr(scrobbler, "access_token", None)
            if not client_id:
                try:
                    from simkl_mps.credentials import get_credentials
                    creds = get_credentials()
                    client_id = creds.get("client_id")
                    if not access_token:
                        access_token = creds.get("access_token")
                except Exception as cred_err:
                    logger.debug(f"Failed to fetch credentials in correction dialog: {cred_err}")

            res = CorrectionDialogController.resolve_input(query, client_id or "", access_token)

            def _update_ui():
                try:
                    if not win.winfo_exists():
                        return
                except Exception:
                    return

                search_btn.configure(state=tk.NORMAL)
                mode = res.get("mode")
                search_results_cache.clear()

                if mode == "direct":
                    item = res.get("item")
                    if item:
                        search_results_cache.append(item)
                        candidates_listbox.insert(
                            tk.END,
                            f"[{item['type'].upper()}] {item['title']} ({item.get('year') or 'N/A'}) - ID: {item['simkl_id']}"
                        )
                        candidates_listbox.selection_set(0)
                        on_candidate_selected()
                elif mode == "search":
                    results = res.get("results", [])
                    if not results:
                        search_status_label.configure(text="No matching items found on Simkl.", foreground="#aa0000")
                    else:
                        search_results_cache.extend(results)
                        for itm in results:
                            candidates_listbox.insert(
                                tk.END,
                                f"[{itm['type'].upper()}] {itm['title']} ({itm.get('year') or 'N/A'}) - ID: {itm['simkl_id']}"
                            )
                        candidates_listbox.selection_set(0)
                        on_candidate_selected()
                else:
                    search_status_label.configure(text="Please enter a valid search term.", foreground="#aa0000")

            try:
                win.after(0, _update_ui)
            except Exception:
                pass

        threading.Thread(target=_bg_task, daemon=True).start()

    search_btn = ttk.Button(input_row, text="Search", command=do_search)
    search_btn.pack(side=tk.RIGHT)
    search_entry.bind("<Return>", lambda e: do_search())

    # Buttons Frame
    btn_frame = ttk.Frame(win, padding=10)
    btn_frame.pack(fill=tk.X)

    def on_save():
        target_candidate = selected_candidate
        if not target_candidate:
            # Fallback: check listbox curselection directly
            cur_sel = candidates_listbox.curselection()
            if cur_sel and cur_sel[0] < len(search_results_cache):
                target_candidate = search_results_cache[cur_sel[0]]

        if not target_candidate:
            messagebox.showwarning("Notice", "Please select a Simkl item from the list first.", parent=win)
            return

        payload = CorrectionDialogController.build_correction_payload(
            selected_item=target_candidate,
            season_str=season_var.get(),
            episode_str=episode_var.get(),
            apply_to_series=series_rule_var.get()
        )

        try:
            success = scrobbler.apply_manual_correction(**payload)
            if success:
                if on_success_callback:
                    on_success_callback()
                win.destroy()
            else:
                messagebox.showerror("Error", "Failed to apply correction.", parent=win)
        except Exception as err:
            logger.error(f"Error applying correction: {err}", exc_info=True)
            messagebox.showerror("Error", f"Error applying correction: {err}", parent=win)

    save_btn = ttk.Button(btn_frame, text="Save & Apply", command=on_save)
    save_btn.pack(side=tk.RIGHT, padx=(5, 0))

    cancel_btn = ttk.Button(btn_frame, text="Cancel", command=win.destroy)
    cancel_btn.pack(side=tk.RIGHT)

    # Initial search if query available
    if search_var.get().strip():
        win.after(100, do_search)

    return win
