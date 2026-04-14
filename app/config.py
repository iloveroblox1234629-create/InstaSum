"""
Config management for InstaSum-Image.
Loads settings from ~/.config/instasum/config.env or a local .env file.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

CONFIG_DIR = Path.home() / ".config" / "instasum"
CONFIG_ENV_FILE = CONFIG_DIR / "config.env"
CONFIG_JSON_FILE = CONFIG_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "output_dir": str(Path.home() / "Documents" / "InstaSum"),
    "provider": "openai",
    "openai_model": "gpt-4o",
    "gemini_model": "gemini-2.5-flash-lite",
    # Browser to borrow cookies from when Instagram requires a login.
    # Empty string = anonymous (no cookies). Options: firefox, chrome,
    # chromium, brave, safari, edge, opera.
    "cookie_browser": "",
}

# Deprecated Gemini model names → replace with current default on load.
_DEPRECATED_GEMINI_MODELS: set[str] = {
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.0-pro",
    "gemini-pro",
    "gemini-pro-vision",
}


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_env():
    """Load .env from config dir, then local .env as fallback."""
    load_dotenv(dotenv_path=CONFIG_ENV_FILE, override=False)
    load_dotenv(dotenv_path=Path(".env"), override=False)


def get_api_key(provider: str) -> str:
    load_env()
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    elif provider == "gemini":
        return os.getenv("GEMINI_API_KEY", "")
    return ""


def save_api_key(provider: str, key: str):
    ensure_config_dir()
    lines = []
    env_key = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"

    if CONFIG_ENV_FILE.exists():
        lines = CONFIG_ENV_FILE.read_text().splitlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{env_key}="):
            lines[i] = f"{env_key}={key}"
            updated = True
            break

    if not updated:
        lines.append(f"{env_key}={key}")

    CONFIG_ENV_FILE.write_text("\n".join(lines) + "\n")
    # Reload so the new value is immediately available
    load_dotenv(dotenv_path=CONFIG_ENV_FILE, override=True)


def load_settings() -> dict:
    ensure_config_dir()
    if CONFIG_JSON_FILE.exists():
        try:
            data = json.loads(CONFIG_JSON_FILE.read_text())
            merged = {**DEFAULT_SETTINGS, **data}
            # Migrate stale/deprecated Gemini model names in-place.
            if merged.get("gemini_model") in _DEPRECATED_GEMINI_MODELS:
                merged["gemini_model"] = DEFAULT_SETTINGS["gemini_model"]
                # Persist the fix so it won't trigger again next run.
                try:
                    CONFIG_JSON_FILE.write_text(json.dumps(merged, indent=2))
                except OSError:
                    pass
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict):
    ensure_config_dir()
    existing = load_settings()
    existing.update(settings)
    try:
        CONFIG_JSON_FILE.write_text(json.dumps(existing, indent=2))
    except OSError as exc:
        import logging
        logging.getLogger(__name__).warning("Could not save settings: %s", exc)
