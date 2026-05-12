"""
Data acquisition layer for InstaSum-Image.

Strategy (2026-era Instagram):
  Pass 1 — anonymous yt-dlp metadata extraction (skip_download=True).
  Pass 2 — if Instagram returns a login wall, retry with the user's live
            browser session via yt-dlp's cookiesfrombrowser option.

Reels are resolved with yt-dlp. Feed posts/carousels are downloaded with
gallery-dl, which handles Instagram sidecar media more reliably.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

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

_GALLERY_DL_TIMEOUT_SECONDS = 180
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

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
    Accepts both stored browser IDs and GUI display labels.
    """
    entry = _browser_entry_for_id(browser_id)
    if entry is None:
        log_cb(f"  Warning: unknown browser ID '{browser_id}' — passing directly to yt-dlp.")
        return browser_id
    if not entry.native and entry.note:
        log_cb(f"  Note: {entry.note}")
    return entry.ydl_key


def _browser_entry_for_id(browser_id: str) -> _BrowserEntry | None:
    key = browser_id.strip()
    entry = BROWSER_REGISTRY.get(key) or BROWSER_REGISTRY.get(key.lower())
    if entry is not None:
        return entry
    lowered = key.lower()
    for candidate in BROWSER_REGISTRY.values():
        if candidate.label.lower() == lowered:
            return candidate
    return None


def _build_ydl_opts(cookie_browser: str | None = None, cookie_file: str | None = None) -> dict:
    """
    Build yt-dlp options for pure metadata extraction.

    skip_download=True  — we never want yt-dlp to download anything;
                          we pull image bytes ourselves once we have the URLs.
    extract_flat=False  — required to get full child-entry data for carousels.
    format="best"          — prevents "no video in this post" errors on image-
                           only posts; yt-dlp still skips the actual download
                           but needs a format selector to parse the metadata.
    ignoreerrors=True     — skips unrecoverable entries (e.g. video-only
                           carousel slides) instead of raising.

    cookie_browser is the *resolved* yt-dlp key (already looked up via
    _resolve_browser before this is called).
    cookie_file is a path to a Netscape-format cookie file (for manual session ID).
    """
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "best",
        "ignoreerrors": True,
    }
    if cookie_browser:
        opts["cookiesfrombrowser"] = (cookie_browser,)
    if cookie_file:
        opts["cookies"] = cookie_file
    return opts


def _extract_info(url: str, opts: dict) -> dict:
    """Run yt-dlp extract_info and return the info dict."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch_post(
    url: str,
    log_cb: Callable[[str], None] | None = None,
    cookie_browser: str | None = None,
    instagram_session_id: str | None = None,
    instagram_csrf_token: str | None = None,
) -> PostData:
    """Fetch an Instagram URL with the downloader best suited to its media type."""
    if _is_reel_url(url):
        return _fetch_post_with_yt_dlp(
            url,
            log_cb=log_cb,
            cookie_browser=cookie_browser,
            instagram_session_id=instagram_session_id,
            instagram_csrf_token=instagram_csrf_token,
        )
    return _fetch_post_with_gallery_dl(
        url,
        log_cb=log_cb,
        cookie_browser=cookie_browser,
        instagram_session_id=instagram_session_id,
        instagram_csrf_token=instagram_csrf_token,
    )


def _is_reel_url(url: str) -> bool:
    """Return True when an Instagram URL targets a Reel."""
    path_parts = [part for part in urlparse(url).path.lower().split("/") if part]
    return bool(path_parts and path_parts[0] in {"reel", "reels"})


def _fetch_post_with_yt_dlp(
    url: str,
    log_cb: Callable[[str], None] | None = None,
    cookie_browser: str | None = None,
    instagram_session_id: str | None = None,
    instagram_csrf_token: str | None = None,
) -> PostData:
    """
    Fetch an Instagram Reel with yt-dlp.

    Two-pass extraction:
      1. Try anonymous (no cookies).
      2. If Instagram returns a login wall, retry with cookie_browser session
         or instagram_session_id.

    Returns PostData with local temp image paths.
    Caller is responsible for deleting temp_dir when done.
    """
    tmp = tempfile.mkdtemp(prefix="instasum_")
    keep_tmp = False

    def _log(msg: str):
        logger.info(msg)
        if log_cb:
            log_cb(msg)

    try:
        # ── Resolve browser ID → yt-dlp key (with fallback mapping + note) ────
        ydl_browser: str | None = None
        if cookie_browser:
            ydl_browser = _resolve_browser(cookie_browser, _log)

        # ── Build cookie file from session ID if provided ─────────────────────
        cookie_file: str | None = None
        if instagram_session_id:
            cookie_file = _build_cookie_file(instagram_session_id, tmp, instagram_csrf_token)

        # ── Pass 1: anonymous ──────────────────────────────────────────────
        _log(f"Fetching metadata (anonymous): {url}")
        info = None
        try:
            info = _extract_info(url, _build_ydl_opts(cookie_browser=None, cookie_file=None))
        except Exception as exc:
            if _is_login_error(exc) and (ydl_browser or cookie_file):
                if ydl_browser:
                    display = BROWSER_REGISTRY.get(cookie_browser, None)
                    label = display.label if display else cookie_browser
                    _log(f"  Login wall detected. Retrying with {label} cookies…")
                else:
                    _log("  Login wall detected. Retrying with session ID…")
                info = None   # fall through to Pass 2
            else:
                raise

        # ── Soft login wall: Pass 1 succeeded but returned no usable images ─────────
        # Instagram sometimes serves a 200 page with metadata but no image URLs.
        if info is not None and (ydl_browser or cookie_file):
            entries = _collect_entries(info)
            if not entries:
                display = BROWSER_REGISTRY.get(cookie_browser, None) if cookie_browser else None
                label = display.label if display else (cookie_browser or "session ID")
                _log(f"  Anonymous fetch returned no entries (possible soft login wall). Retrying with {label}…")
                info = None
            elif not _entries_have_images(entries):
                display = BROWSER_REGISTRY.get(cookie_browser, None) if cookie_browser else None
                label = display.label if display else "session ID"
                _log(f"  Anonymous fetch returned entries with no image URLs (soft login wall). Retrying with {label}…")
                _log(f"  Debug: entry keys: {list(entries[0].keys())[:15]}")
                info = None

        # ── Pass 2: browser-cookie session or session ID ───────────────────
        if info is None:
            if not ydl_browser and not cookie_file:
                raise RuntimeError(
                    "Instagram requires a login to access this post.\n"
                    "Select a browser under 'Browser Session' or enter your "
                    "Instagram session ID in Settings."
                )
            if cookie_file:
                _log("  Retrying with Instagram session ID…")
                try:
                    info = _extract_info(url, _build_ydl_opts(cookie_browser=None, cookie_file=cookie_file))
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to fetch post with session ID: {exc}\n"
                        "The session ID may be expired. Try getting a new one."
                    ) from exc
            else:
                _log("  Retrying with browser session cookies…")
                try:
                    info = _extract_info(url, _build_ydl_opts(cookie_browser=ydl_browser, cookie_file=None))
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to fetch post with browser cookies: {exc}\n"
                        "Try manually providing your Instagram session ID in Settings."
                    ) from exc

            if info is None:
                raise RuntimeError(
                    "Failed to fetch post: yt-dlp returned no data.\n"
                    "The post may be private, deleted, or require authentication."
                )

        # ── Parse the info dict ────────────────────────────────────────────
        if info is None:
            raise RuntimeError(
                "Failed to fetch post: No data returned from Instagram.\n"
                "The post may be private, deleted, or require authentication."
            )

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

        # Warn if some images failed to download
        if len(image_paths) < len(entries):
            _log(f"  Warning: Only {len(image_paths)}/{len(entries)} images downloaded successfully.")

        if not image_paths:
            raise RuntimeError(
                "No images could be downloaded from this post.\n"
                "The post may be private, age-restricted, or behind a login wall.\n"
                "Try selecting a browser under 'Browser Session'."
            )

        keep_tmp = True
        return PostData(
            url=url,
            title=_sanitize_title(title_raw),
            caption=caption,
            upload_date=upload_date,
            creator=creator,
            image_paths=image_paths,
            temp_dir=tmp,
        )
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# ── gallery-dl feed post / carousel path ───────────────────────────────────


def _fetch_post_with_gallery_dl(
    url: str,
    log_cb: Callable[[str], None] | None = None,
    cookie_browser: str | None = None,
    instagram_session_id: str | None = None,
    instagram_csrf_token: str | None = None,
) -> PostData:
    """
    Fetch an Instagram feed post/carousel with gallery-dl.

    gallery-dl is used for non-Reel posts because it downloads every sidecar
    image directly instead of depending on yt-dlp's carousel metadata shape.
    """
    tmp = tempfile.mkdtemp(prefix="instasum_")
    keep_tmp = False

    def _log(msg: str):
        logger.info(msg)
        if log_cb:
            log_cb(msg)

    try:
        gallery_browser: str | None = None
        if cookie_browser:
            gallery_browser = _resolve_gallery_browser(cookie_browser, _log)

        cookie_file: str | None = None
        if instagram_session_id:
            cookie_file = _build_cookie_file(instagram_session_id, tmp, instagram_csrf_token)

        _log(f"Fetching carousel/media with gallery-dl: {url}")
        metadata = _probe_gallery_dl_metadata(url, gallery_browser, cookie_file, _log)
        _download_with_gallery_dl(url, tmp, gallery_browser, cookie_file, _log)

        image_paths = _collect_gallery_dl_images(tmp, _log)
        if not image_paths:
            raise RuntimeError(
                "No images could be downloaded from this post with gallery-dl.\n"
                "The post may be private, deleted, video-only, or require authentication."
            )

        _log(f"Found {len(image_paths)} image(s) in post.")
        metadata = metadata or {}

        keep_tmp = True
        return PostData(
            url=url,
            title=_sanitize_title(_gallery_title(metadata, url)),
            caption=_gallery_caption(metadata),
            upload_date=_gallery_upload_date(metadata),
            creator=_gallery_creator(metadata),
            image_paths=image_paths,
            temp_dir=tmp,
        )
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _resolve_gallery_browser(browser_id: str, log_cb) -> str:
    entry = _browser_entry_for_id(browser_id)
    if entry is None:
        log_cb(f"  Warning: unknown browser ID '{browser_id}' - passing directly to gallery-dl.")
        return browser_id
    if not entry.native and entry.note:
        log_cb(f"  Note: {entry.note}")
    return entry.ydl_key


def _gallery_dl_base_args(
    cookie_browser: str | None = None,
    cookie_file: str | None = None,
) -> list[str]:
    args = [sys.executable, "-m", "gallery_dl", "--no-input", "--no-colors", "--config-ignore"]
    if cookie_file:
        args.extend(["--cookies", cookie_file])
    elif cookie_browser:
        args.extend(["--cookies-from-browser", cookie_browser])
    return args


def _gallery_dl_target(url: str) -> str:
    """Force gallery-dl's Instagram extractor for regular Instagram URLs."""
    parsed = urlparse(url)
    if "instagram.com" in parsed.netloc.lower() and not url.startswith("instagram:"):
        return f"instagram:{url}"
    return url


def _run_gallery_dl(args: list[str], log_cb) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=_GALLERY_DL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gallery-dl is not installed in this Python environment.\n"
            "Run: pip install -r requirements.txt"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gallery-dl timed out while fetching this post.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        if "No module named gallery_dl" in stderr:
            raise RuntimeError(
                "gallery-dl is not installed in this Python environment.\n"
                "Run: pip install -r requirements.txt"
            ) from exc
        log_cb(f"  gallery-dl failed: {stderr or exc}")
        raise RuntimeError(
            "gallery-dl failed to fetch this post.\n"
            f"{stderr or exc}"
        ) from exc


def _probe_gallery_dl_metadata(
    url: str,
    cookie_browser: str | None,
    cookie_file: str | None,
    log_cb,
) -> dict:
    args = _gallery_dl_base_args(cookie_browser, cookie_file)
    args.extend(["--dump-json", "--simulate", _gallery_dl_target(url)])
    try:
        result = _run_gallery_dl(args, log_cb)
    except RuntimeError as exc:
        _log_metadata_probe_failure(exc, log_cb)
        return {}

    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            return item
    return {}


def _log_metadata_probe_failure(exc: RuntimeError, log_cb) -> None:
    log_cb(f"  Warning: gallery-dl metadata probe failed; continuing with download only. {exc}")


def _download_with_gallery_dl(
    url: str,
    dest_dir: str,
    cookie_browser: str | None,
    cookie_file: str | None,
    log_cb,
) -> None:
    args = _gallery_dl_base_args(cookie_browser, cookie_file)
    args.extend(["--directory", dest_dir, "--filename", "/O"])
    args.append(_gallery_dl_target(url))
    _run_gallery_dl(args, log_cb)


def _collect_gallery_dl_images(dest_dir: str, log_cb) -> list[str]:
    image_paths: list[str] = []
    for root, _dirs, files in os.walk(dest_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            if not name.lower().endswith(_IMAGE_EXTENSIONS):
                continue
            try:
                with Image.open(path) as im:
                    im.verify()
            except Exception as exc:
                log_cb(f"  Skipping invalid image {name}: {exc}")
                continue
            image_paths.append(path)
    return image_paths


def _gallery_caption(metadata: dict) -> str:
    return _first_gallery_value(metadata, ("description", "caption", "content", "title"))


def _gallery_title(metadata: dict, url: str) -> str:
    return (
        _first_gallery_value(metadata, ("shortcode", "code", "id", "title"))
        or _shortcode_from_url(url)
        or "post"
    )


def _gallery_creator(metadata: dict) -> str:
    return _first_gallery_value(
        metadata,
        ("username", "user", "owner_username", "author", "account", "channel"),
    ) or "Unknown"


def _gallery_upload_date(metadata: dict) -> str:
    raw = metadata.get("date") or metadata.get("timestamp") or metadata.get("upload_date")
    if isinstance(raw, datetime):
        return raw.strftime("%Y%m%d")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y%m%d")
    if isinstance(raw, str):
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 8:
            return digits[:8]
    return "00000000"


def _first_gallery_value(metadata: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            for nested_key in ("username", "name", "full_name", "id"):
                nested = value.get(nested_key)
                if nested:
                    return str(nested)
            continue
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item)
        value = str(value).strip()
        if value:
            return value
    return ""


def _shortcode_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() in {"p", "tv", "reel", "reels"}:
        return parts[1]
    return ""


# ── Entry collection ───────────────────────────────────────────────────────


def _collect_entries(info: dict) -> list[dict]:
    """Return a flat list of media entries (handles single + carousel)."""
    # Carousel / sidecar: yt-dlp exposes child posts under 'entries'
    if info.get("entries"):
        # Filter out video entries (carousels can have mixed content)
        filtered = []
        for e in info["entries"]:
            if not e:
                continue
            # Skip video entries - we only process images
            if e.get("is_video", False):
                continue
            filtered.append(e)
        # Return filtered list (may be empty if all entries are videos)
        return filtered
    # Single post (no entries) → treat as single
    return [info]


def _entries_have_images(entries: list[dict]) -> bool:
    """Check if at least one entry has a usable image URL."""
    for entry in entries:
        if _best_image_url(entry):
            return True
    return False


# ── Image download ─────────────────────────────────────────────────────────


def _download_image(entry: dict, dest_dir: str, idx: int, log_cb) -> str | None:
    img_url = _best_image_url(entry)
    if not img_url:
        log_cb(f"  Skipping slot {idx}: no usable image URL found.")
        return None

    ext      = _guess_ext(img_url)
    out_path = os.path.join(dest_dir, f"image_{idx:02d}{ext}")

    log_cb(f"  Downloading image {idx + 1}…")
    headers = {
        # Mimic a regular browser request so CDN servers don't reject us
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.instagram.com/",
    }
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
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
            last_exc = exc
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))  # 1s, 2s back-off

    log_cb(f"  Warning: could not download image {idx + 1} after 3 attempts: {last_exc}")
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
    # For carousel entries, thumbnails tend to be more reliable than 'url'
    thumbnails = entry.get("thumbnails") or []
    if thumbnails:
        for thumb in reversed(thumbnails):
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


def _build_cookie_file(session_id: str, tmp_dir: str, csrf_token: str | None = None) -> str:
    """
    Create a Netscape-format cookie file for yt-dlp from Instagram cookies.
    Returns the path to the temporary cookie file.
    """
    import time

    cookie_path = os.path.join(tmp_dir, "instagram_cookies.txt")
    # Far future expiration (~100 years from now)
    far_future = str(int(time.time()) + (86400 * 365 * 100))

    lines = ["# Netscape HTTP Cookie File"]
    # Domain, flag, path, secure, expiration, name, value
    # No leading dot - yt-dlp handles subdomain matching internally
    lines.append("instagram.com\tTRUE\t/\tTRUE\t" + far_future + "\tsessionid\t" + session_id)

    if csrf_token:
        lines.append("instagram.com\tTRUE\t/\tFALSE\t" + far_future + "\tcsrftoken\t" + csrf_token)

    with open(cookie_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return cookie_path
