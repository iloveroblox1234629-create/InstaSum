"""
GUI layer for InstaSum-Image.
BMW-inspired dashboard interface built with customtkinter.
"""

import logging
import shutil
import tkinter as tk
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .config import (
    load_settings, save_settings,
    get_api_key, save_api_key,
    load_env,
    get_instagram_session_id, save_instagram_session_id,
    get_instagram_csrf_token, save_instagram_csrf_token,
)
from .fetcher import fetch_post, BROWSER_REGISTRY, BROWSER_OPTIONS
from .processor import summarize
from .writer import write_note

logger = logging.getLogger(__name__)

ctk.set_default_color_theme("blue")

APP_TITLE = "InstaSum-Image"
APP_VERSION = "1.0.0"
WINDOW_MIN_W = 1120
WINDOW_MIN_H = 760
SIDEBAR_W = 240
MAIN_CONTENT_W = 900
NONE_BROWSER_LABEL = "None (anonymous)"

THEMES = {
    "light": {
        "canvas": "#edf1f7",
        "sidebar": "#101722",
        "sidebar_soft": "#172231",
        "panel": "#ffffff",
        "panel_soft": "#f5f7fb",
        "bmw_blue": "#0066b1",
        "bmw_sky": "#00a3e0",
        "bmw_navy": "#1c2f5f",
        "bmw_red": "#e22718",
        "success": "#16834f",
        "warning": "#b87500",
        "error": "#c5322d",
        "text_primary": "#111318",
        "text_secondary": "#5f6775",
        "text_muted": "#8a93a3",
        "border": "#d9dee8",
        "white": "#ffffff",
        "chip_bg": "#e8f5fc",
        "chip_hover": "#d6ecf8",
        "sidebar_text": "#b9c2d2",
        "sidebar_muted": "#a9b3c4",
        "sidebar_border": "#283647",
        "sidebar_heading": "#d7deea",
        "status_track": "#2c3544",
        "preview_text": "#c3d0e4",
        "preview_tile_a": "#1f6eac",
        "preview_tile_b": "#294577",
        "preview_tile_border": "#5277aa",
        "preview_footer": "#152545",
    },
    "dark": {
        "canvas": "#0f141c",
        "sidebar": "#070b10",
        "sidebar_soft": "#111a26",
        "panel": "#151b24",
        "panel_soft": "#101722",
        "bmw_blue": "#1689e8",
        "bmw_sky": "#25b7f0",
        "bmw_navy": "#0a2240",
        "bmw_red": "#f05245",
        "success": "#3cc37b",
        "warning": "#e0a532",
        "error": "#ff6b5f",
        "text_primary": "#eef3fb",
        "text_secondary": "#aab4c3",
        "text_muted": "#7c8798",
        "border": "#273445",
        "white": "#f7fbff",
        "chip_bg": "#102a42",
        "chip_hover": "#173858",
        "sidebar_text": "#b8c2d0",
        "sidebar_muted": "#8f9aab",
        "sidebar_border": "#243348",
        "sidebar_heading": "#d9e2ef",
        "status_track": "#243142",
        "preview_text": "#c9d8ec",
        "preview_tile_a": "#135f9f",
        "preview_tile_b": "#233d67",
        "preview_tile_border": "#3d669a",
        "preview_footer": "#0d1a30",
    },
}

COLORS = THEMES["light"].copy()


def _normalize_appearance_mode(value: str | None) -> str:
    return "dark" if str(value).lower() == "dark" else "light"


def _set_appearance_mode(value: str | None) -> str:
    mode = _normalize_appearance_mode(value)
    COLORS.clear()
    COLORS.update(THEMES[mode])
    ctk.set_appearance_mode(mode)
    return mode


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        load_env()
        self.settings = load_settings()
        self.appearance_mode = _set_appearance_mode(
            self.settings.get("appearance_mode", "light")
        )
        self.is_processing = False
        self.active_tab = "Extract"
        self.sidebar_buttons = {}
        self.section_cards = {}
        self.main_scroll = None
        self.main_stack = None

        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.minsize(WINDOW_MIN_W, WINDOW_MIN_H)
        self.geometry(f"{WINDOW_MIN_W}x{WINDOW_MIN_H}")
        self.resizable(True, True)
        self.configure(fg_color=COLORS["canvas"])

        self._build_ui()
        self._load_saved_values()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.section_cards = {}
        self.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_W)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        content = ctk.CTkFrame(self, fg_color=COLORS["canvas"], corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self._build_topbar(content)

        self.main_scroll = ctk.CTkScrollableFrame(
            content,
            fg_color=COLORS["canvas"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["bmw_blue"],
        )
        self.main_scroll.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 18))
        self.main_scroll.grid_columnconfigure(0, weight=1)

        self.main_stack = ctk.CTkFrame(self.main_scroll, width=MAIN_CONTENT_W, fg_color=COLORS["canvas"])
        self.main_stack.grid(row=0, column=0, sticky="n")
        self.main_stack.grid_columnconfigure(0, weight=1)

        self.section_cards["Extract"] = self._build_url_card(self.main_stack, row=0)
        self._build_pipeline_card(self.main_stack, row=1)
        self.section_cards["Models"] = self._build_settings_card(self.main_stack, row=2)
        self.section_cards["Library"] = self._build_preview_card(self.main_stack, row=3)
        self.section_cards["Settings"] = self._build_session_card(self.main_stack, row=4)
        self._build_downloader_card(self.main_stack, row=5)
        self._build_log_card(self.main_stack, row=6)
        self._bind_main_scroll()

        self.status_label = ctk.CTkLabel(
            content,
            text="Ready",
            height=26,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.status_label.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 10))

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=COLORS["sidebar"],
            width=SIDEBAR_W,
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 24))
        brand.grid_columnconfigure(0, weight=1)

        self._create_logo(brand).grid(row=0, column=0, sticky="w", pady=(0, 10))

        ctk.CTkLabel(
            brand,
            text=APP_TITLE,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["white"],
        ).grid(row=1, column=0, sticky="w")
        ctk.CTkLabel(
            brand,
            text="Image Intelligence",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["sidebar_muted"],
        ).grid(row=2, column=0, sticky="w")

        self.sidebar_buttons = {}
        for label in ("Extract", "Library", "Models", "Settings"):
            active = label == self.active_tab
            button = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                height=42,
                corner_radius=8,
                fg_color=COLORS["bmw_blue"] if active else COLORS["sidebar"],
                hover_color=COLORS["sidebar_soft"],
                text_color=COLORS["white"] if active else COLORS["sidebar_text"],
                font=ctk.CTkFont(size=13, weight="bold" if active else "normal"),
                command=lambda tab=label: self._select_sidebar_tab(tab),
            )
            button.pack(fill="x", padx=18, pady=4)
            self.sidebar_buttons[label] = button

        status_panel = ctk.CTkFrame(
            sidebar,
            fg_color=COLORS["sidebar_soft"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["sidebar_border"],
        )
        status_panel.pack(side="bottom", fill="x", padx=18, pady=(12, 20))
        ctk.CTkLabel(
            status_panel,
            text="Session readiness",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["sidebar_heading"],
        ).pack(anchor="w", padx=14, pady=(14, 6))
        ctk.CTkProgressBar(
            status_panel,
            height=8,
            progress_color=COLORS["bmw_sky"],
            fg_color=COLORS["status_track"],
        ).pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkLabel(
            status_panel,
            text="Browser cookies optional",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["sidebar_muted"],
        ).pack(anchor="w", padx=14, pady=(0, 14))

    def _build_topbar(self, parent):
        topbar = ctk.CTkFrame(parent, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 14))
        topbar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topbar,
            text="Instagram visual summary",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            topbar,
            text="Clean capture, local OCR, and VLM synthesis for Obsidian-ready notes.",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.mode_var = ctk.StringVar(value=self.appearance_mode.title())
        ctk.CTkSegmentedButton(
            topbar,
            values=["Light", "Dark"],
            variable=self.mode_var,
            command=self._on_mode_change,
            height=30,
            corner_radius=16,
            selected_color=COLORS["bmw_blue"],
            selected_hover_color=COLORS["bmw_navy"],
            unselected_color=COLORS["panel"],
            unselected_hover_color=COLORS["chip_hover"],
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 8))
        ctk.CTkLabel(
            topbar,
            text="gallery-dl routing",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["bmw_blue"],
            fg_color=COLORS["chip_bg"],
            corner_radius=16,
            width=140,
            height=30,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 8))
        ctk.CTkLabel(
            topbar,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["bmw_navy"],
            fg_color=COLORS["panel"],
            corner_radius=16,
            width=62,
            height=30,
        ).grid(row=0, column=3, rowspan=2, sticky="e")

    def _build_url_card(self, parent, row: int):
        card = self._create_card(parent, "Instagram URLs", "Reels use yt-dlp, posts use gallery-dl")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 18))

        self.url_textbox = ctk.CTkTextbox(
            body,
            height=118,
            wrap="word",
            fg_color=COLORS["panel_soft"],
            border_color=COLORS["border"],
            border_width=1,
            font=ctk.CTkFont(family="monospace", size=13),
            text_color=COLORS["text_primary"],
        )
        self.url_textbox.pack(fill="x")

        self.process_btn = ctk.CTkButton(
            body,
            text="Extract and Summarize",
            height=50,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLORS["bmw_blue"],
            hover_color=COLORS["bmw_navy"],
            corner_radius=8,
            command=self._start_processing,
        )
        self.process_btn.pack(fill="x", pady=(14, 0))

        self.progress = ctk.CTkProgressBar(
            body,
            mode="indeterminate",
            progress_color=COLORS["bmw_sky"],
            fg_color=COLORS["border"],
        )
        self.progress.pack(fill="x", pady=(12, 0))
        self.progress.set(0)
        return card

    def _build_pipeline_card(self, parent, row: int):
        card = self._create_card(parent, "Pipeline", "Current job path")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=18, pady=(0, 18))
        for col in range(4):
            grid.grid_columnconfigure(col, weight=1, uniform="pipeline")

        steps = [
            ("Route", "Choose gallery-dl or yt-dlp."),
            ("Capture", "Download verified images."),
            ("OCR", "Run local EasyOCR."),
            ("Synthesize", "Write Markdown notes."),
        ]
        for col, (title, desc) in enumerate(steps):
            tile = self._create_pipeline_tile(grid, title, desc)
            tile.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        return card

    def _build_settings_card(self, parent, row: int):
        card = self._create_card(parent, "AI and Output", "Saved locally")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 18))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        self._field_label(body, "Provider").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._field_label(body, "Output Folder").grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.provider_var = ctk.StringVar(value=self.settings.get("provider", "openai"))
        provider_frame = ctk.CTkFrame(
            body,
            fg_color=COLORS["panel_soft"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        provider_frame.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(6, 14))
        self.openai_radio = ctk.CTkRadioButton(
            provider_frame,
            text="OpenAI",
            variable=self.provider_var,
            value="openai",
            command=self._on_provider_change,
            fg_color=COLORS["bmw_blue"],
            hover_color=COLORS["bmw_navy"],
            text_color=COLORS["text_primary"],
        )
        self.openai_radio.pack(side="left", padx=12, pady=10)
        self.gemini_radio = ctk.CTkRadioButton(
            provider_frame,
            text="Gemini",
            variable=self.provider_var,
            value="gemini",
            command=self._on_provider_change,
            fg_color=COLORS["bmw_blue"],
            hover_color=COLORS["bmw_navy"],
            text_color=COLORS["text_primary"],
        )
        self.gemini_radio.pack(side="left", padx=(0, 12), pady=10)

        output_frame = ctk.CTkFrame(body, fg_color="transparent")
        output_frame.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 14))
        output_frame.grid_columnconfigure(0, weight=1)
        self.output_dir_entry = self._entry(output_frame, placeholder="~/Documents/InstaSum")
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.output_dir_entry.bind("<FocusOut>", self._on_output_dir_change)
        self.output_dir_entry.bind("<Return>", self._on_output_dir_change)
        self._small_button(output_frame, "Browse", self._browse_output_dir).grid(row=0, column=1)

        self._field_label(body, "API Key").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self._field_label(body, "Browser Session").grid(row=2, column=1, sticky="w", padx=(8, 0))

        key_frame = ctk.CTkFrame(body, fg_color="transparent")
        key_frame.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(6, 0))
        key_frame.grid_columnconfigure(0, weight=1)
        self.api_key_entry = self._entry(key_frame, placeholder="Enter your API key...", show="*")
        self.api_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.show_key_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            key_frame,
            text="Show",
            variable=self.show_key_var,
            command=self._toggle_key_visibility,
            width=62,
            fg_color=COLORS["bmw_blue"],
            hover_color=COLORS["bmw_navy"],
        ).grid(row=0, column=1, padx=(0, 8))
        self._small_button(key_frame, "Save", self._save_key).grid(row=0, column=2)

        browser_frame = ctk.CTkFrame(body, fg_color="transparent")
        browser_frame.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        browser_frame.grid_columnconfigure(0, weight=1)

        self._browser_display_options = [NONE_BROWSER_LABEL] + [
            BROWSER_REGISTRY[k].label for k in BROWSER_OPTIONS
        ]
        self._browser_label_to_key = {
            BROWSER_REGISTRY[k].label: k for k in BROWSER_OPTIONS
        }
        self.browser_var = ctk.StringVar(value=NONE_BROWSER_LABEL)
        ctk.CTkOptionMenu(
            browser_frame,
            values=self._browser_display_options,
            variable=self.browser_var,
            height=40,
            fg_color=COLORS["panel_soft"],
            button_color=COLORS["bmw_blue"],
            button_hover_color=COLORS["bmw_navy"],
            text_color=COLORS["text_primary"],
            dropdown_fg_color=COLORS["white"],
            dropdown_hover_color=COLORS["chip_hover"],
            command=self._on_browser_change,
        ).grid(row=0, column=0, sticky="ew")
        return card

    def _build_log_card(self, parent, row: int):
        card = self._create_card(parent, "Activity Log", "Thread-safe processing output")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))

        self.log_box = ctk.CTkTextbox(
            card,
            height=190,
            wrap="word",
            font=ctk.CTkFont(family="monospace", size=12),
            fg_color=COLORS["panel_soft"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text_primary"],
        )
        self.log_box.pack(fill="x", padx=18, pady=(0, 10))
        self.log_box.configure(state="disabled")

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 18))
        self._small_button(actions, "Clear Log", self._clear_log).pack(side="right")
        return card

    def _build_preview_card(self, parent, row: int):
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["bmw_navy"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["bmw_blue"],
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))

        ctk.CTkLabel(
            card,
            text="Carousel capture ready",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["white"],
        ).pack(anchor="w", padx=20, pady=(20, 4))
        ctk.CTkLabel(
            card,
            text="A compact capture queue for OCR and synthesis. Session cookies stay local.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["preview_text"],
            justify="left",
            wraplength=680,
        ).pack(anchor="w", padx=20, pady=(0, 18))

        thumb_grid = ctk.CTkFrame(card, fg_color="transparent")
        thumb_grid.pack(fill="x", padx=20, pady=(0, 18))
        for col in range(3):
            thumb_grid.grid_columnconfigure(col, weight=1, uniform="thumb")
        for idx in range(6):
            tile = ctk.CTkFrame(
                thumb_grid,
                height=72,
                corner_radius=8,
                fg_color=COLORS["preview_tile_b"] if idx % 2 else COLORS["preview_tile_a"],
                border_width=1,
                border_color=COLORS["preview_tile_border"],
            )
            tile.grid(row=idx // 3, column=idx % 3, sticky="ew", padx=4, pady=4)

        metrics = ctk.CTkFrame(card, fg_color=COLORS["preview_footer"], corner_radius=0)
        metrics.pack(fill="x")
        self._metric(metrics, "6", "images detected").pack(side="left", padx=20, pady=14)
        self._metric(metrics, "2", "downloaders").pack(side="left", padx=20, pady=14)
        return card

    def _build_session_card(self, parent, row: int):
        card = self._create_card(parent, "Session Controls", "Private posts")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 18))
        body.grid_columnconfigure(0, weight=1)

        self._field_label(body, "Session ID").grid(row=0, column=0, sticky="w")
        session_row = ctk.CTkFrame(body, fg_color="transparent")
        session_row.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        session_row.grid_columnconfigure(0, weight=1)
        self.session_id_entry = self._entry(session_row, placeholder="Paste sessionid value...", show="*")
        self.session_id_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.show_session_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            session_row,
            text="Show",
            variable=self.show_session_var,
            command=self._toggle_session_visibility,
            width=62,
            fg_color=COLORS["bmw_blue"],
            hover_color=COLORS["bmw_navy"],
        ).grid(row=0, column=1, padx=(0, 8))
        self._small_button(session_row, "Save", self._save_session_id).grid(row=0, column=2)

        self._field_label(body, "CSRF Token").grid(row=2, column=0, sticky="w")
        csrf_row = ctk.CTkFrame(body, fg_color="transparent")
        csrf_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        csrf_row.grid_columnconfigure(0, weight=1)
        self.csrf_token_entry = self._entry(csrf_row, placeholder="Paste csrftoken value...", show="*")
        self.csrf_token_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.show_csrf_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            csrf_row,
            text="Show",
            variable=self.show_csrf_var,
            command=self._toggle_csrf_visibility,
            width=62,
            fg_color=COLORS["bmw_blue"],
            hover_color=COLORS["bmw_navy"],
        ).grid(row=0, column=1, padx=(0, 8))
        self._small_button(csrf_row, "Save", self._save_csrf_token).grid(row=0, column=2)
        return card

    def _build_downloader_card(self, parent, row: int):
        card = self._create_card(parent, "Downloader Mix", "Automatic routing")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 18))

        self._option_row(body, "gallery-dl", "Feed posts and carousel media", "posts").pack(fill="x", pady=(0, 10))
        self._option_row(body, "yt-dlp", "Instagram Reels and video metadata", "reels").pack(fill="x")
        return card

    def _create_logo(self, parent) -> tk.Canvas:
        canvas = tk.Canvas(
            parent,
            width=132,
            height=54,
            bg=COLORS["sidebar"],
            highlightthickness=0,
            bd=0,
        )
        canvas.create_rectangle(2, 7, 42, 47, fill="#e4405f", outline="")
        canvas.create_arc(2, 7, 42, 47, start=90, extent=90, fill="#833ab4", outline="")
        canvas.create_arc(2, 7, 42, 47, start=0, extent=90, fill="#f77737", outline="")
        canvas.create_oval(14, 19, 30, 35, outline=COLORS["white"], width=3)
        canvas.create_oval(32, 14, 37, 19, fill=COLORS["white"], outline="")
        canvas.create_line(50, 27, 78, 27, fill=COLORS["bmw_sky"], width=4, arrow=tk.LAST)
        canvas.create_rectangle(88, 7, 126, 47, fill=COLORS["panel"], outline=COLORS["border"], width=1)
        canvas.create_polygon(112, 7, 126, 21, 112, 21, fill=COLORS["chip_bg"], outline=COLORS["border"])
        canvas.create_text(107, 34, text="SVG", fill=COLORS["bmw_blue"], font=("Arial", 9, "bold"))
        return canvas

    def _create_card(self, parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["panel"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w")
        if subtitle:
            ctk.CTkLabel(
                header,
                text=subtitle,
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_secondary"],
            ).grid(row=0, column=1, sticky="e", padx=(12, 0))
        return card

    def _create_pipeline_tile(self, parent, title: str, description: str) -> ctk.CTkFrame:
        tile = ctk.CTkFrame(
            parent,
            fg_color=COLORS["panel_soft"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        ctk.CTkLabel(
            tile,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            tile,
            text=description,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            justify="left",
            wraplength=120,
        ).pack(anchor="w", padx=12, pady=(0, 12))
        return tile

    def _field_label(self, parent, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text.upper(),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
        )

    def _entry(self, parent, placeholder: str, show: str | None = None) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            height=40,
            placeholder_text=placeholder,
            show=show,
            fg_color=COLORS["panel_soft"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=13),
        )

    def _small_button(self, parent, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=82,
            height=40,
            command=command,
            corner_radius=8,
            fg_color=COLORS["white"],
            hover_color=COLORS["chip_hover"],
            text_color=COLORS["bmw_navy"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=12, weight="bold"),
        )

    def _metric(self, parent, value: str, label: str) -> ctk.CTkFrame:
        metric = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(
            metric,
            text=value,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["white"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            metric,
            text=label,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["preview_text"],
        ).pack(anchor="w")
        return metric

    def _option_row(self, parent, title: str, description: str, badge: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            parent,
            fg_color=COLORS["panel_soft"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            row,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_primary"],
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            row,
            text=description,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))
        ctk.CTkLabel(
            row,
            text=badge,
            width=62,
            height=24,
            corner_radius=12,
            fg_color=COLORS["chip_bg"],
            text_color=COLORS["bmw_blue"],
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=12)
        return row

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _bind_main_scroll(self):
        canvas = getattr(self.main_scroll, "_parent_canvas", None)
        if canvas is None:
            return
        canvas.bind_all("<MouseWheel>", self._on_main_mousewheel)
        canvas.bind_all("<Button-4>", self._on_main_mousewheel)
        canvas.bind_all("<Button-5>", self._on_main_mousewheel)

    def _on_main_mousewheel(self, event):
        canvas = getattr(self.main_scroll, "_parent_canvas", None)
        if canvas is None:
            return
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)
            units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        canvas.yview_scroll(units, "units")

    def _select_sidebar_tab(self, tab: str):
        self.active_tab = tab
        for label, button in self.sidebar_buttons.items():
            active = label == tab
            button.configure(
                fg_color=COLORS["bmw_blue"] if active else COLORS["sidebar"],
                text_color=COLORS["white"] if active else COLORS["sidebar_text"],
                font=ctk.CTkFont(size=13, weight="bold" if active else "normal"),
            )
        self._scroll_to_section(tab)

    def _scroll_to_section(self, tab: str):
        target = self.section_cards.get(tab)
        canvas = getattr(self.main_scroll, "_parent_canvas", None)
        if target is None or canvas is None or self.main_stack is None:
            return

        def _move():
            target_y = target.winfo_y()
            scrollable_height = max(1, self.main_stack.winfo_height() - canvas.winfo_height())
            canvas.yview_moveto(min(1, max(0, target_y / scrollable_height)))

        self.after(0, _move)

    def _on_mode_change(self, value: str):
        mode = _normalize_appearance_mode(value)
        if mode == self.appearance_mode:
            return
        if self.is_processing:
            self.mode_var.set(self.appearance_mode.title())
            messagebox.showinfo(
                "Processing",
                "Theme can be changed after the current extraction finishes.",
            )
            return

        state = self._capture_ui_state()
        self.appearance_mode = _set_appearance_mode(mode)
        self.settings["appearance_mode"] = mode
        save_settings({"appearance_mode": mode})

        for child in self.winfo_children():
            child.destroy()
        self.configure(fg_color=COLORS["canvas"])
        self._build_ui()
        self._restore_ui_state(state)
        self.status_label.configure(
            text=f"{mode.title()} mode",
            text_color=COLORS["success"],
        )

    def _capture_ui_state(self) -> dict:
        self.log_box.configure(state="normal")
        log_text = self.log_box.get("1.0", "end-1c")
        self.log_box.configure(state="disabled")
        return {
            "urls": self.url_textbox.get("1.0", "end-1c"),
            "provider": self.provider_var.get(),
            "api_key": self.api_key_entry.get(),
            "output_dir": self.output_dir_entry.get(),
            "browser": self.browser_var.get(),
            "session_id": self.session_id_entry.get(),
            "csrf_token": self.csrf_token_entry.get(),
            "show_key": self.show_key_var.get(),
            "show_session": self.show_session_var.get(),
            "show_csrf": self.show_csrf_var.get(),
            "log": log_text,
        }

    def _restore_ui_state(self, state: dict):
        self.url_textbox.delete("1.0", "end")
        self.url_textbox.insert("1.0", state.get("urls", ""))

        provider = state.get("provider", self.settings.get("provider", "openai"))
        self.provider_var.set(provider)
        self._update_key_label(provider)

        self.api_key_entry.delete(0, "end")
        self.api_key_entry.insert(0, state.get("api_key", ""))
        self.show_key_var.set(state.get("show_key", False))
        self._toggle_key_visibility()

        self.output_dir_entry.delete(0, "end")
        self.output_dir_entry.insert(0, state.get("output_dir", ""))

        self.browser_var.set(state.get("browser", NONE_BROWSER_LABEL))

        self.session_id_entry.delete(0, "end")
        self.session_id_entry.insert(0, state.get("session_id", ""))
        self.show_session_var.set(state.get("show_session", False))
        self._toggle_session_visibility()

        self.csrf_token_entry.delete(0, "end")
        self.csrf_token_entry.insert(0, state.get("csrf_token", ""))
        self.show_csrf_var.set(state.get("show_csrf", False))
        self._toggle_csrf_visibility()

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("1.0", state.get("log", ""))
        self.log_box.configure(state="disabled")

    def _load_saved_values(self):
        self.output_dir_entry.insert(0, self.settings.get("output_dir", ""))
        provider = self.settings.get("provider", "openai")
        self.provider_var.set(provider)
        key = get_api_key(provider)
        if key:
            self.api_key_entry.insert(0, key)
        self._update_key_label(provider)

        saved_browser_key = self.settings.get("cookie_browser", "")
        if saved_browser_key and saved_browser_key in BROWSER_REGISTRY:
            self.browser_var.set(BROWSER_REGISTRY[saved_browser_key].label)
        else:
            self.browser_var.set(NONE_BROWSER_LABEL)

        session_id = get_instagram_session_id()
        if session_id:
            self.session_id_entry.insert(0, session_id)
        csrf_token = get_instagram_csrf_token()
        if csrf_token:
            self.csrf_token_entry.insert(0, csrf_token)

    def _on_browser_change(self, display_label: str):
        """Translate GUI display label to internal key and persist."""
        if display_label == NONE_BROWSER_LABEL:
            key = ""
        else:
            key = self._browser_label_to_key.get(display_label, display_label)
        save_settings({"cookie_browser": key})

    def _on_provider_change(self):
        provider = self.provider_var.get()
        self._update_key_label(provider)
        self.api_key_entry.delete(0, "end")
        key = get_api_key(provider)
        if key:
            self.api_key_entry.insert(0, key)
        save_settings({"provider": provider})

    def _update_key_label(self, provider: str):
        label = "OpenAI API key" if provider == "openai" else "Google Gemini API key"
        self.api_key_entry.configure(placeholder_text=f"Enter your {label}...")

    def _toggle_key_visibility(self):
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _save_key(self):
        provider = self.provider_var.get()
        key = self.api_key_entry.get().strip()
        if not key:
            messagebox.showwarning("No Key", "Please enter an API key first.")
            return
        save_api_key(provider, key)
        self._log(f"API key for {provider} saved")
        self.status_label.configure(text="API key saved", text_color=COLORS["success"])

    def _toggle_session_visibility(self):
        self.session_id_entry.configure(show="" if self.show_session_var.get() else "*")

    def _save_session_id(self):
        session_id = self.session_id_entry.get().strip()
        if not session_id:
            messagebox.showwarning("No Session ID", "Please enter a session ID first.")
            return
        save_instagram_session_id(session_id)
        self._log("Instagram session ID saved")
        self.status_label.configure(text="Session ID saved", text_color=COLORS["success"])

    def _toggle_csrf_visibility(self):
        self.csrf_token_entry.configure(show="" if self.show_csrf_var.get() else "*")

    def _save_csrf_token(self):
        csrf_token = self.csrf_token_entry.get().strip()
        if not csrf_token:
            messagebox.showwarning("No CSRF Token", "Please enter a CSRF token first.")
            return
        save_instagram_csrf_token(csrf_token)
        self._log("Instagram CSRF token saved")
        self.status_label.configure(text="CSRF token saved", text_color=COLORS["success"])

    def _on_output_dir_change(self, _event=None):
        path = self.output_dir_entry.get().strip()
        if path:
            save_settings({"output_dir": path})

    def _browse_output_dir(self):
        chosen = filedialog.askdirectory(title="Select Output Folder")
        if chosen:
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, chosen)
            save_settings({"output_dir": chosen})

    def _log(self, msg: str):
        """Thread-safe log append."""

        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, _append)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy: bool):
        def _do():
            self.is_processing = busy
            if busy:
                self.process_btn.configure(state="disabled", text="Processing...")
                self.progress.start()
                self.status_label.configure(text="Processing...", text_color=COLORS["warning"])
            else:
                self.process_btn.configure(state="normal", text="Extract and Summarize")
                self.progress.stop()
                self.progress.set(0)
                self.status_label.configure(text="Ready", text_color=COLORS["text_muted"])

        self.after(0, _do)

    # ------------------------------------------------------------------
    # Processing pipeline
    # ------------------------------------------------------------------

    def _start_processing(self):
        urls_raw = self.url_textbox.get("1.0", "end").strip()
        if not urls_raw:
            messagebox.showwarning("No URL", "Please enter at least one Instagram URL.")
            return

        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]
        provider = self.provider_var.get()
        api_key = self.api_key_entry.get().strip()
        output_dir = self.output_dir_entry.get().strip()
        browser_raw = self.browser_var.get()
        cookie_browser = None if browser_raw == NONE_BROWSER_LABEL else browser_raw
        session_id = self.session_id_entry.get().strip() or None
        csrf_token = self.csrf_token_entry.get().strip() or None

        if not api_key:
            messagebox.showwarning("No API Key", "Please enter your API key.")
            return
        if not output_dir:
            messagebox.showwarning("No Output Folder", "Please select an output folder.")
            return

        self._set_busy(True)
        thread = threading.Thread(
            target=self._pipeline_thread,
            args=(urls, provider, api_key, output_dir, cookie_browser, session_id, csrf_token),
            daemon=True,
        )
        thread.start()

    def _pipeline_thread(
        self,
        urls: list[str],
        provider: str,
        api_key: str,
        output_dir: str,
        cookie_browser: str | None,
        session_id: str | None,
        csrf_token: str | None,
    ):
        saved_files = []
        errors = []

        for url in urls:
            self._log(f"\n{'=' * 50}")
            self._log(f"Processing: {url}")
            post_data = None
            try:
                post_data = fetch_post(
                    url,
                    log_cb=self._log,
                    cookie_browser=cookie_browser,
                    instagram_session_id=session_id,
                    instagram_csrf_token=csrf_token,
                )

                settings = load_settings()
                model = settings.get(
                    "openai_model" if provider == "openai" else "gemini_model"
                )
                result = summarize(
                    image_paths=post_data.image_paths,
                    caption=post_data.caption,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    log_cb=self._log,
                )

                out_path = write_note(post_data, result, output_dir)
                saved_files.append(str(out_path))
                self._log(f"Saved: {Path(out_path).name}")

            except Exception as exc:
                logger.exception(f"Error processing {url}")
                self._log(f"ERROR: {exc}")
                errors.append((url, str(exc)))
            finally:
                if post_data and post_data.temp_dir:
                    shutil.rmtree(post_data.temp_dir, ignore_errors=True)

        self._set_busy(False)
        self._log(f"\n{'=' * 50}")
        self._log(f"Done. {len(saved_files)} note(s) saved, {len(errors)} error(s).")

        if saved_files:
            self.after(0, lambda: messagebox.showinfo(
                "Complete",
                f"{len(saved_files)} note(s) saved to:\n{output_dir}\n\n"
                + "\n".join(Path(p).name for p in saved_files),
            ))
        elif errors:
            self.after(0, lambda: messagebox.showerror(
                "Failed",
                f"All {len(errors)} URL(s) failed.\nCheck the log for details.",
            ))
