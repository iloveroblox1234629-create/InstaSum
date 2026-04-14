"""
GUI layer for InstaSum-Image.
Built with customtkinter for a modern dark-mode look on Linux/KDE and macOS.
"""

import shutil
import threading
import logging
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk

from .config import (
    load_settings, save_settings,
    get_api_key, save_api_key,
    load_env,
)
from .fetcher import fetch_post, BROWSER_REGISTRY, BROWSER_OPTIONS
from .processor import summarize
from .writer import write_note

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "InstaSum-Image"
APP_VERSION = "1.0.0"
WINDOW_MIN_W = 720
WINDOW_MIN_H = 680


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        load_env()
        self.settings = load_settings()

        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.minsize(WINDOW_MIN_W, WINDOW_MIN_H)
        self.geometry(f"{WINDOW_MIN_W}x{WINDOW_MIN_H}")
        self.resizable(True, True)

        self._build_ui()
        self._load_saved_values()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- Header ----
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("#1a1a2e", "#1a1a2e"))
        header.pack(fill="x", padx=0, pady=0)
        ctk.CTkLabel(
            header,
            text=APP_TITLE,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#e0aaff",
        ).pack(side="left", padx=20, pady=12)
        ctk.CTkLabel(
            header,
            text="Extract & summarize Instagram post knowledge",
            font=ctk.CTkFont(size=12),
            text_color="#aaaaaa",
        ).pack(side="left", padx=0, pady=12)

        # ---- Main scrollable content area ----
        main = ctk.CTkScrollableFrame(self, label_text="")
        main.pack(fill="both", expand=True, padx=16, pady=(8, 0))
        main.columnconfigure(1, weight=1)

        row = 0

        # --- URL input ---
        ctk.CTkLabel(main, text="Instagram URL(s)", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(12, 2))
        row += 1

        self.url_textbox = ctk.CTkTextbox(main, height=80, wrap="word")
        self.url_textbox.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
        row += 1

        ctk.CTkLabel(main, text="One URL per line. Supports single posts and carousels.",
                     text_color="#888888", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 10))
        row += 1

        # --- Provider selection ---
        ctk.CTkLabel(main, text="AI Provider", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=4, pady=(4, 2))
        row += 1

        self.provider_var = ctk.StringVar(value=self.settings.get("provider", "openai"))
        provider_frame = ctk.CTkFrame(main, fg_color="transparent")
        provider_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 8))

        ctk.CTkRadioButton(
            provider_frame, text="OpenAI (gpt-4o)", variable=self.provider_var,
            value="openai", command=self._on_provider_change,
        ).pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(
            provider_frame, text="Google Gemini (gemini-2.5-flash-lite)", variable=self.provider_var,
            value="gemini", command=self._on_provider_change,
        ).pack(side="left")
        row += 1

        # --- API Key ---
        self.api_key_label = ctk.CTkLabel(main, text="OpenAI API Key", anchor="w",
                                           font=ctk.CTkFont(weight="bold"))
        self.api_key_label.grid(row=row, column=0, sticky="w", padx=4, pady=(4, 2))
        row += 1

        key_frame = ctk.CTkFrame(main, fg_color="transparent")
        key_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 2))
        key_frame.columnconfigure(0, weight=1)

        self.api_key_entry = ctk.CTkEntry(key_frame, placeholder_text="sk-…  or  AIza…",
                                           show="•", height=36)
        self.api_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.show_key_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(key_frame, text="Show", variable=self.show_key_var,
                        command=self._toggle_key_visibility, width=70).grid(row=0, column=1)

        ctk.CTkButton(key_frame, text="Save Key", width=90, height=36,
                      command=self._save_key).grid(row=0, column=2, padx=(8, 0))
        row += 1

        ctk.CTkLabel(main, text="Key is saved locally to ~/.config/instasum/config.env — never sent to our servers.",
                     text_color="#888888", font=ctk.CTkFont(size=11)).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 10))
        row += 1

        # --- Output directory ---
        ctk.CTkLabel(main, text="Output Folder", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=4, pady=(4, 2))
        row += 1

        out_frame = ctk.CTkFrame(main, fg_color="transparent")
        out_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 10))
        out_frame.columnconfigure(0, weight=1)

        self.output_dir_entry = ctk.CTkEntry(out_frame, height=36,
                                              placeholder_text="e.g. ~/vault/Brain")
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.output_dir_entry.bind("<FocusOut>", self._on_output_dir_change)
        self.output_dir_entry.bind("<Return>", self._on_output_dir_change)
        ctk.CTkButton(out_frame, text="Browse…", width=90, height=36,
                      command=self._browse_output_dir).grid(row=0, column=1)
        row += 1

        # --- Browser session (cookie fallback) ---
        ctk.CTkLabel(main, text="Browser Session", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=4, pady=(4, 2))
        row += 1

        browser_frame = ctk.CTkFrame(main, fg_color="transparent")
        browser_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 2))

        # Build display-name list from the registry (preserves BROWSER_OPTIONS order)
        _NONE_LABEL = "None (anonymous)"
        self._browser_display_options = [_NONE_LABEL] + [
            BROWSER_REGISTRY[k].label for k in BROWSER_OPTIONS
        ]
        # Reverse map: display label → internal key
        self._browser_label_to_key = {
            BROWSER_REGISTRY[k].label: k for k in BROWSER_OPTIONS
        }

        self.browser_var = ctk.StringVar(value=_NONE_LABEL)
        ctk.CTkOptionMenu(
            browser_frame,
            values=self._browser_display_options,
            variable=self.browser_var,
            width=220,
            command=self._on_browser_change,
        ).pack(side="left")

        # Tag line: native vs community engine
        ctk.CTkLabel(
            browser_frame,
            text="  ← cross-platform: same name works on Windows, macOS & Linux",
            text_color="#666666",
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(8, 0))
        row += 1

        ctk.CTkLabel(
            main,
            text=(
                "If Instagram shows a login wall, pick the browser where you're "
                "already logged in.\nInstaSum will borrow only your session cookie "
                "— your password is never touched."
            ),
            text_color="#888888",
            font=ctk.CTkFont(size=11),
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 10))
        row += 1

        # --- Process button ---
        self.process_btn = ctk.CTkButton(
            main,
            text="   Extract & Summarize",
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#7b2ff7",
            hover_color="#5a1db5",
            command=self._start_processing,
        )
        self.process_btn.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 12))
        row += 1

        # --- Progress bar ---
        self.progress = ctk.CTkProgressBar(main, mode="indeterminate")
        self.progress.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 8))
        self.progress.set(0)
        row += 1

        # --- Log output ---
        ctk.CTkLabel(main, text="Activity Log", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 2))
        row += 1

        self.log_box = ctk.CTkTextbox(main, height=180, wrap="word",
                                       font=ctk.CTkFont(family="monospace", size=12))
        self.log_box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
        self.log_box.configure(state="disabled")
        row += 1

        log_btn_frame = ctk.CTkFrame(main, fg_color="transparent")
        log_btn_frame.grid(row=row, column=0, columnspan=2, sticky="e", padx=4, pady=(0, 12))
        ctk.CTkButton(log_btn_frame, text="Clear Log", width=90, height=28,
                      command=self._clear_log).pack(side="right")
        row += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
            self.browser_var.set("None (anonymous)")

    def _on_browser_change(self, display_label: str):
        """Translate GUI display label → internal key and persist."""
        if display_label == "None (anonymous)":
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
        label = "OpenAI API Key" if provider == "openai" else "Google Gemini API Key"
        self.api_key_label.configure(text=label)

    def _toggle_key_visibility(self):
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "•")

    def _save_key(self):
        provider = self.provider_var.get()
        key = self.api_key_entry.get().strip()
        if not key:
            messagebox.showwarning("No Key", "Please enter an API key first.")
            return
        save_api_key(provider, key)
        self._log(f"API key for {provider} saved to ~/.config/instasum/config.env")

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
            if busy:
                self.process_btn.configure(state="disabled", text="   Processing…")
                self.progress.start()
            else:
                self.process_btn.configure(state="normal", text="   Extract & Summarize")
                self.progress.stop()
                self.progress.set(0)
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
        cookie_browser = None if browser_raw == "None (anonymous)" else browser_raw

        if not api_key:
            messagebox.showwarning("No API Key", "Please enter your API key.")
            return
        if not output_dir:
            messagebox.showwarning("No Output Folder", "Please select an output folder.")
            return

        self._set_busy(True)
        thread = threading.Thread(
            target=self._pipeline_thread,
            args=(urls, provider, api_key, output_dir, cookie_browser),
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
    ):
        saved_files = []
        errors = []

        for url in urls:
            self._log(f"\n{'='*50}")
            self._log(f"Processing: {url}")
            post_data = None
            try:
                # Step 1: Fetch
                post_data = fetch_post(url, log_cb=self._log, cookie_browser=cookie_browser)

                # Step 2: Summarize
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

                # Step 3: Write
                out_path = write_note(post_data, result, output_dir)
                saved_files.append(str(out_path))
                self._log(f"  Saved: {out_path}")

            except Exception as exc:
                logger.exception(f"Error processing {url}")
                self._log(f"  ERROR: {exc}")
                errors.append((url, str(exc)))
            finally:
                if post_data and post_data.temp_dir:
                    shutil.rmtree(post_data.temp_dir, ignore_errors=True)

        # Done
        self._set_busy(False)
        self._log(f"\n{'='*50}")
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
