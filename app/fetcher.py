"""
Data acquisition layer for InstaSum-Image.

Strategy (2026-era Instagram):
  Pass 1 — anonymous yt-dlp metadata extraction (skip_download=True).
  Pass 2 — if Instagram returns a login wall, retry with the user's live
            browser session via yt-dlp's cookiesfrombrowser option.

Images are downloaded ourselves via requests after we have the URLs;
yt-dlp is used purely as a metadata/URL resolver.
"""

import os
import re
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

import yt_dlp
import requests
from PIL import Image

logger = logging.getLogger(__name__)

# Keywords in yt-dlp error messages that indicate an Instagram login wall.
_LOGIN_SIGNALS = (
    "login required",
    "not logged in",
    "log in",
    "sign in",
    "checkpoint",
    "authentication",
    "private",
    "restricted",
    "age-restricted",
    "this content",      # "This content isn't available"
)

# ---------------------------------------------------------------------------
# Browser registry
# ---------------------------------------------------------------------------
# yt-dlp resolves the OS-specific cookie/profile path automatically from the
# browser name alone — the same key works on Windows, macOS, and Linux.
#
# For browsers yt-dlp doesn't know natively (Arc, Zen, LibreWolf …) we map
# them to their engine.  The engine key is what actually goes to yt-dlp;
# the mapping and a log note are stored here so the user understands what's
# happening.
#
# native=True  → yt-dlp supports this browser name directly
# native=False → we pass ydl_key (the parent engine) to yt-dlp and warn the
#                user that the profile directory may differ

@dataclass
class _BrowserEntry:
    label:   str    # human-readable name shown in the GUI
    ydl_key: str    # key passed to yt-dlp's cookiesfrombrowser
    native:  bool   # True = yt-dlp natively supports this key
    note:    str = ""  # logged when native=False so the user knows what's happening


# Internal registry keyed by the ID that gets stored in settings.json
BROWSER_REGISTRY: dict[str, _BrowserEntry] = {
    # ── Chromium-based ────────────────────────────────────────────────────
    "chrome":       _BrowserEntry("Chrome",           "chrome",    True),
    "chromium":     _BrowserEntry("Chromium",         "chromium",  True),
    "brave":        _BrowserEntry("Brave",            "brave",     True),
    "edge":         _BrowserEntry("Microsoft Edge",   "edge",      True),
    "opera":        _BrowserEntry("Opera",            "opera",     True),
    "opera_gx":     _BrowserEntry("Opera GX",         "opera",     False,
                                  "Opera GX shares Opera's cookie store — using 'opera'."),
    "vivaldi":      _BrowserEntry("Vivaldi",          "vivaldi",   True),
    "whale":        _BrowserEntry("Naver Whale",      "whale",     True),
    # Arc is Chromium-based but stores its profile separately from Chrome.
    # yt-dlp doesn't have a dedicated Arc extractor; we fall back to the
    # Chrome engine, which will read Arc's Chromium-compatible cookie DB if
    # Arc's data dir happens to shadow Chrome's default path (common on macOS).
    "arc":          _BrowserEntry("Arc",              "chrome",    False,
                                  "Arc is Chromium-based. Falling back to 'chrome' cookie store. "
                                  "If this fails, export your Instagram cookies from Arc manually."),
    "thorium":      _BrowserEntry("Thorium",          "chrome",    False,
                                  "Thorium is Chromium-based — using 'chrome' cookie store."),
    "ungoogled":    _BrowserEntry("Ungoogled Chromium", "chromium", False,
                                  "Ungoogled Chromium shares Chromium's cookie store."),
    "iridium":      _BrowserEntry("Iridium",          "chromium",  False,
                                  "Iridium is Chromium-based — using 'chromium' cookie store."),
    # ── Firefox-based ─────────────────────────────────────────────────────
    "firefox":      _BrowserEntry("Firefox",          "firefox",   True),
    "librewolf":    _BrowserEntry("LibreWolf",        "firefox",   False,
                                  "LibreWolf uses its own Firefox profile directory. "
                                  "yt-dlp will attempt the default Firefox path; "
                                  "if it fails, export cookies manually."),
    "zen":          _BrowserEntry("Zen Browser",      "firefox",   False,
                                  "Zen Browser is Firefox-based but keeps a separate profile. "
                                  "Falling back to 'firefox'. Export cookies manually if needed."),
    "waterfox":     _BrowserEntry("Waterfox",         "firefox",   False,
                                  "Waterfox is Firefox-based — using 'firefox' cookie store."),
    "floorp":       _BrowserEntry("Floorp",           "firefox",   False,
                                  "Floorp is Firefox-based — using 'firefox' cookie store."),
    "mullvad":      _BrowserEntry("Mullvad Browser",  "firefox",   False,
                                  "Mullvad Browser is Firefox-based — using 'firefox' cookie store."),
    "basilisk":     _BrowserEntry("Basilisk",         "firefox",   False,
                                  "Basilisk is Gecko-based — using 'firefox' cookie store."),
    "pale_moon":    _BrowserEntry("Pale Moon",        "firefox",   False,
                                  "Pale Moon is Gecko-based — using 'firefox' cookie store."),
    # ── Apple ─────────────────────────────────────────────────────────────
    "safari":       _BrowserEntry("Safari",           "safari",    True),
}

# Ordered list for the GUI dropdown (groups separated by empty label-slots in the dict above)
BROWSER_OPTIONS: list[str] = [
    # Chromium family
    "chrome", "chromium", "brave", "edge",
    "opera", "opera_gx", "vivaldi", "arc",
    "whale", "thorium", "ungoogled", "iridium",
    # Firefox family
    "firefox", "librewolf", "zen", "waterfox",
    "floorp", "mullvad", "basilisk", "pale_moon",
    # Other
    "safari",
]

# Convenience: flat list of yt-dlp-native keys (used elsewhere)
SUPPORTED_BROWSERS: list[str] = [k for k, e in BROWSER_REGISTRY.items() if e.native]


@dataclass
class PostData:
    url: str
    title: str
    caption: str
    upload_date: str           # YYYYMMDD
    creator: str
    image_paths: list[str] = field(default_factory=list)
    temp_dir: str = ""         # caller must shutil.rmtree when done


def _sanitize_title(raw: str, max_len: int = 60) -> str:
    clean = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE)
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean[:max_len] or "instagram_post"


def _is_login_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(sig in msg for sig in _LOGIN_SIGNALS)


def _resolve_browser(browser_id: str, log_cb) -> str:
    """
    Look up browser_id in the registry and return the yt-dlp key to use.
    Logs a note when a community browser is mapped to its parent engine.
    """
    entry = BROWSER_REGISTRY.get(browser_id)
    if entry is None:
        # Unknown ID — pass as-is and let yt-dlp surface any error
        return browser_id
    if not entry.native and entry.note:
        log_cb(f"  Note: {entry.note}")
    return entry.ydl_key


def _build_ydl_opts(cookie_browser: str | None = None) -> dict:
    """
    Build yt-dlp options for pure metadata extraction.

    skip_download=True  — we never want yt-dlp to download anything;
                          we pull image bytes ourselves once we have the URLs.
    extract_flat=False  — required to get full child-entry data for carousels.
    format not set      — irrelevant when skip_download=True; avoids confusing
                          yt-dlp's format selector on non-video posts.

    cookie_browser is the *resolved* yt-dlp key (already looked up via
    _resolve_browser before this is called).
    """
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    if cookie_browser:
        opts["cookiesfrombrowser"] = (cookie_browser,)
    return opts


def _extract_info(url: str, opts: dict) -> dict:
    """Run yt-dlp extract_info and return the info dict."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch_post(
    url: str,
    log_cb: Callable[[str], None] | None = None,
    cookie_browser: str | None = None,
) -> PostData:
    """
    Fetch an Instagram post (single image or carousel).

    Two-pass extraction:
      1. Try anonymous (no cookies).
      2. If Instagram returns a login wall, retry with cookie_browser session.

    Returns PostData with local temp image paths.
    Caller is responsible for deleting temp_dir when done.
    """
    tmp = tempfile.mkdtemp(prefix="instasum_")

    def _log(msg: str):
        logger.info(msg)
        if log_cb:
            log_cb(msg)

    # ── Resolve browser ID → yt-dlp key (with fallback mapping + note) ────
    ydl_browser: str | None = None
    if cookie_browser:
        ydl_browser = _resolve_browser(cookie_browser, _log)

    # ── Pass 1: anonymous ──────────────────────────────────────────────
    _log(f"Fetching metadata (anonymous): {url}")
    info = None
    try:
        info = _extract_info(url, _build_ydl_opts(cookie_browser=None))
    except Exception as exc:
        if _is_login_error(exc) and ydl_browser:
            display = BROWSER_REGISTRY.get(cookie_browser, None)
            label = display.label if display else cookie_browser
            _log(f"  Login wall detected. Retrying with {label} cookies…")
            info = None   # fall through to Pass 2
        else:
            raise

    # ── Pass 2: browser-cookie session (only if Pass 1 hit a login wall) ──
    if info is None:
        if not ydl_browser:
            raise RuntimeError(
                "Instagram requires a login to access this post.\n"
                "Select a browser under 'Browser Session' so InstaSum can "
                "borrow your existing Instagram session."
            )
        _log(f"  Retrying with browser session cookies…")
        info = _extract_info(url, _build_ydl_opts(cookie_browser=ydl_browser))

    # ── Parse the info dict ────────────────────────────────────────────
    entries = _collect_entries(info)
    _log(f"Found {len(entries)} image(s) in post.")

    caption     = info.get("description") or info.get("title") or ""
    title_raw   = info.get("title") or info.get("id") or "post"
    upload_date = info.get("upload_date") or "00000000"
    creator     = info.get("uploader") or info.get("channel") or "Unknown"

    # ── Download images locally ────────────────────────────────────────
    image_paths: list[str] = []
    for idx, entry in enumerate(entries):
        img_path = _download_image(entry, tmp, idx, _log)
        if img_path:
            image_paths.append(img_path)

    if not image_paths:
        raise RuntimeError(
            "No images could be downloaded from this post.\n"
            "The post may be private, age-restricted, or behind a login wall.\n"
            "Try selecting a browser under 'Browser Session'."
        )

    return PostData(
        url=url,
        title=_sanitize_title(title_raw),
        caption=caption,
        upload_date=upload_date,
        creator=creator,
        image_paths=image_paths,
        temp_dir=tmp,
    )


# ── Entry collection ───────────────────────────────────────────────────────


def _collect_entries(info: dict) -> list[dict]:
    """Return a flat list of media entries (handles single + carousel)."""
    # Carousel / sidecar: yt-dlp exposes child posts under 'entries'
    if info.get("entries"):
        return [e for e in info["entries"] if e]
    # Playlist wrapper with no real children → treat as single
    return [info]


# ── Image download ─────────────────────────────────────────────────────────


def _download_image(entry: dict, dest_dir: str, idx: int, log_cb) -> str | None:
    img_url = _best_image_url(entry)
    if not img_url:
        log_cb(f"  Skipping slot {idx}: no usable image URL found.")
        return None

    ext      = _guess_ext(img_url)
    out_path = os.path.join(dest_dir, f"image_{idx:02d}{ext}")

    log_cb(f"  Downloading image {idx + 1}…")
    try:
        headers = {
            # Mimic a regular browser request so CDN servers don't reject us
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.instagram.com/",
        }
        resp = requests.get(img_url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()

        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Verify the file is a valid image before returning it
        with Image.open(out_path) as im:
            im.verify()

        return out_path

    except Exception as exc:
        log_cb(f"  Warning: could not download image {idx + 1}: {exc}")
        return None


def _best_image_url(entry: dict) -> str:
    """
    Pick the highest-resolution still-image URL from an entry dict.

    Priority order:
      1. 'url' field — yt-dlp puts the direct media URL here; for static
         posts this IS the full-res JPEG. Skip if it looks like a video.
      2. 'thumbnails' list — yt-dlp appends thumbnails in ascending
         resolution order, so we walk it in reverse and take the first
         non-video URL.
      3. 'thumbnail' (singular) — lower-res fallback.
    """
    # 1. Direct URL (best for static posts & carousel slides)
    direct = entry.get("url", "")
    if direct and not _is_video_url(direct):
        return direct

    # 2. Thumbnails list — largest last
    for thumb in reversed(entry.get("thumbnails") or []):
        u = thumb.get("url", "")
        if u and not _is_video_url(u):
            return u

    # 3. Singular thumbnail key
    thumb_url = entry.get("thumbnail", "")
    if thumb_url and not _is_video_url(thumb_url):
        return thumb_url

    return ""


def _is_video_url(url: str) -> bool:
    path = url.split("?")[0].lower()
    return path.endswith((".mp4", ".mov", ".webm", ".m4v"))


def _guess_ext(url: str) -> str:
    path = url.split("?")[0].lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ext
    return ".jpg"
