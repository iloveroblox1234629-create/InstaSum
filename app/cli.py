"""
Command-line interface for InstaSum-Image.
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import TextIO
from urllib.parse import urlparse

from .config import (
    get_api_key,
    load_env,
    load_settings,
)

logger = logging.getLogger(__name__)
VALID_PROVIDERS = {"openai", "gemini"}


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, stderr: TextIO | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._stderr = stderr

    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if not parsed.urls and not parsed.url_file:
            self.error("provide at least one URL or --url-file")
        return parsed

    def error(self, message):
        stream = self._stderr or sys.stderr
        self.print_usage(stream)
        print(f"{self.prog}: error: {message}", file=stream)
        raise SystemExit(2)


def build_parser(stderr: TextIO | None = None) -> argparse.ArgumentParser:
    parser = _Parser(
        prog="instasum-image",
        description="Fetch Instagram posts, summarize images, and write Markdown notes.",
        stderr=stderr,
    )
    parser.add_argument("urls", nargs="*", help="Instagram post or reel URL")
    parser.add_argument(
        "--url-file",
        help="File containing one URL per line. Blank lines and # comments are ignored.",
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "gemini"),
        help="AI provider. Defaults to settings.",
    )
    parser.add_argument("--api-key", help="API key override.")
    parser.add_argument("--output-dir", help="Output directory override.")
    parser.add_argument(
        "--browser",
        help="Cookie browser override. Use empty string or 'none' for anonymous.",
    )
    parser.add_argument("--session-id", help="Instagram session ID override.")
    parser.add_argument("--csrf-token", help="Instagram CSRF token override.")
    parser.add_argument("--model", help="Model override.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser


def collect_urls(positional_urls: list[str], url_file: str | None) -> list[str]:
    urls = list(positional_urls)
    if not url_file:
        return urls

    for line in Path(url_file).expanduser().read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)
    return urls


def run(
    argv: list[str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = build_parser(stderr=stderr)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        urls = collect_urls(args.urls, args.url_file)
    except OSError as exc:
        print(f"Could not read URL file: {exc}", file=stderr)
        return 2
    if not urls:
        print("No URLs provided.", file=stderr)
        return 2
    invalid_url = first_invalid_url(urls)
    if invalid_url:
        print(f"Invalid URL: {invalid_url}", file=stderr)
        return 2

    load_env()
    settings = load_settings()
    provider = args.provider or settings.get("provider", "openai")
    if provider not in VALID_PROVIDERS:
        print(
            f"Invalid provider '{provider}'. Expected one of: gemini, openai.",
            file=stderr,
        )
        return 2

    api_key = args.api_key or get_api_key(provider)
    output_dir = args.output_dir or settings.get("output_dir", "")
    cookie_browser = _normalize_optional(args.browser, settings.get("cookie_browser", ""))
    session_id = _normalize_optional(
        args.session_id,
        settings.get("instagram_session_id", ""),
    )
    csrf_token = _normalize_optional(
        args.csrf_token,
        settings.get("instagram_csrf_token", ""),
    )
    model = args.model or settings.get(
        "openai_model" if provider == "openai" else "gemini_model"
    )

    if not api_key:
        print(
            f"Missing API key for provider '{provider}'. Use --api-key or configure it in settings.",
            file=stderr,
        )
        return 2

    fetch_post, summarize, write_note = _load_pipeline()

    saved_files: list[str] = []
    failures: list[tuple[str, str]] = []

    def log_cb(message: str):
        print(message, file=stdout)

    for url in urls:
        log_cb("")
        log_cb("=" * 50)
        log_cb(f"Processing: {url}")
        post_data = None
        try:
            post_data = fetch_post(
                url,
                log_cb=log_cb,
                cookie_browser=cookie_browser,
                instagram_session_id=session_id,
                instagram_csrf_token=csrf_token,
            )
            result = summarize(
                image_paths=post_data.image_paths,
                caption=post_data.caption,
                provider=provider,
                api_key=api_key,
                model=model,
                log_cb=log_cb,
            )
            out_path = write_note(post_data, result, output_dir)
            saved_files.append(str(out_path))
            print(str(out_path), file=stdout)
        except Exception as exc:
            if args.verbose:
                logger.exception("Error processing %s", url)
            failures.append((url, str(exc)))
            print(f"ERROR: {url}: {exc}", file=stderr)
        finally:
            if post_data and getattr(post_data, "temp_dir", ""):
                shutil.rmtree(post_data.temp_dir, ignore_errors=True)

    if failures:
        print(
            f"Completed with {len(saved_files)} success(es) and {len(failures)} failure(s).",
            file=stderr,
        )
        for url, error in failures:
            print(f"- {url}: {error}", file=stderr)
        return 1

    return 0


def _normalize_optional(override: str | None, default: str | None) -> str | None:
    value = default if override is None else override
    if value is None:
        return None
    value = value.strip()
    if not value or value.lower() == "none":
        return None
    return value


def _load_pipeline():
    from .fetcher import fetch_post
    from .processor import summarize
    from .writer import write_note

    return fetch_post, summarize, write_note


def first_invalid_url(urls: list[str]) -> str | None:
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return url
    return None


def main() -> None:
    sys.exit(run())
