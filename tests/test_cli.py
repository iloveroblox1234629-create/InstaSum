import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class CliTests(unittest.TestCase):
    def test_cli_module_does_not_import_runtime_pipeline_at_import_time(self):
        import app.cli as cli

        self.assertFalse(hasattr(cli, "fetch_post"))
        self.assertFalse(hasattr(cli, "summarize"))
        self.assertFalse(hasattr(cli, "write_note"))

    def test_argument_parsing_rejects_no_urls(self):
        from app.cli import build_parser

        parser = build_parser()

        with self.assertRaises(SystemExit) as err:
            parser.parse_args([])

        self.assertNotEqual(err.exception.code, 0)

    def test_run_without_urls_writes_error_to_injected_stderr(self):
        from app.cli import run

        stderr = io.StringIO()
        code = run([], stderr=stderr)

        self.assertNotEqual(code, 0)
        self.assertIn("URL", stderr.getvalue())

    def test_url_file_ignores_blank_lines_and_comments(self):
        from app.cli import collect_urls

        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("\n")
            handle.write("# ignored\n")
            handle.write("https://example.com/one\n")
            handle.write("   \n")
            handle.write("  # also ignored\n")
            handle.write("https://example.com/two\n")
            path = handle.name

        self.addCleanup(Path(path).unlink)

        urls = collect_urls(["https://example.com/arg"], path)

        self.assertEqual(
            urls,
            [
                "https://example.com/arg",
                "https://example.com/one",
                "https://example.com/two",
            ],
        )

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    @mock.patch("app.cli.load_settings")
    def test_run_orchestrates_pipeline_with_effective_options(
        self,
        load_settings,
        get_api_key,
        load_pipeline,
    ):
        load_settings.return_value = {
            "provider": "openai",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-2.5-flash-lite",
            "output_dir": "/settings/out",
            "cookie_browser": "firefox",
            "instagram_session_id": "settings-session",
            "instagram_csrf_token": "settings-csrf",
        }
        get_api_key.return_value = "settings-key"
        post = SimpleNamespace(
            image_paths=["/tmp/one.jpg"],
            caption="caption",
            temp_dir="",
        )
        result = SimpleNamespace()
        fetch_post = mock.Mock(return_value=post)
        summarize = mock.Mock(return_value=result)
        write_note = mock.Mock(return_value=Path("/notes/out.md"))
        load_pipeline.return_value = (fetch_post, summarize, write_note)

        from app.cli import run

        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            [
                "https://instagram.com/p/one",
                "--provider",
                "gemini",
                "--model",
                "gemini-custom",
                "--output-dir",
                "/override/out",
                "--browser",
                "chrome",
                "--session-id",
                "override-session",
                "--csrf-token",
                "override-csrf",
            ],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0, stderr.getvalue())
        load_pipeline.assert_called_once_with()
        fetch_post.assert_called_once_with(
            "https://instagram.com/p/one",
            log_cb=mock.ANY,
            cookie_browser="chrome",
            instagram_session_id="override-session",
            instagram_csrf_token="override-csrf",
        )
        summarize.assert_called_once_with(
            image_paths=["/tmp/one.jpg"],
            caption="caption",
            provider="gemini",
            api_key="settings-key",
            model="gemini-custom",
            log_cb=mock.ANY,
        )
        write_note.assert_called_once_with(post, result, "/override/out")
        self.assertIn("/notes/out.md", stdout.getvalue())

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    @mock.patch("app.cli.load_settings")
    def test_missing_api_key_exits_before_fetching(
        self,
        load_settings,
        get_api_key,
        load_pipeline,
    ):
        load_settings.return_value = {
            "provider": "openai",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-2.5-flash-lite",
            "output_dir": "/settings/out",
            "cookie_browser": "",
            "instagram_session_id": "",
            "instagram_csrf_token": "",
        }
        get_api_key.return_value = ""

        from app.cli import run

        stderr = io.StringIO()
        code = run(["https://instagram.com/p/one"], stderr=stderr)

        self.assertNotEqual(code, 0)
        self.assertIn("Missing API key", stderr.getvalue())
        load_pipeline.assert_not_called()

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    @mock.patch("app.cli.load_settings")
    def test_invalid_provider_from_settings_exits_before_api_key_lookup(
        self,
        load_settings,
        get_api_key,
        load_pipeline,
    ):
        load_settings.return_value = {
            "provider": "bad",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-2.5-flash-lite",
            "output_dir": "/settings/out",
            "cookie_browser": "",
            "instagram_session_id": "",
            "instagram_csrf_token": "",
        }

        from app.cli import run

        stderr = io.StringIO()
        code = run(["https://instagram.com/p/one"], stderr=stderr)

        self.assertEqual(code, 2)
        self.assertIn("Invalid provider", stderr.getvalue())
        get_api_key.assert_not_called()
        load_pipeline.assert_not_called()

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    @mock.patch("app.cli.load_settings")
    def test_non_verbose_fetch_failure_does_not_log_traceback(
        self,
        load_settings,
        get_api_key,
        load_pipeline,
    ):
        load_settings.return_value = {
            "provider": "openai",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-2.5-flash-lite",
            "output_dir": "/settings/out",
            "cookie_browser": "",
            "instagram_session_id": "",
            "instagram_csrf_token": "",
        }
        get_api_key.return_value = "settings-key"
        fetch_post = mock.Mock(side_effect=RuntimeError("fetch failed"))
        summarize = mock.Mock()
        write_note = mock.Mock()
        load_pipeline.return_value = (fetch_post, summarize, write_note)

        from app.cli import run

        stderr = io.StringIO()
        with mock.patch("app.cli.logger.exception") as log_exception:
            code = run(["https://instagram.com/p/one"], stderr=stderr)

        self.assertEqual(code, 1)
        self.assertIn("fetch failed", stderr.getvalue())
        log_exception.assert_not_called()
        summarize.assert_not_called()
        write_note.assert_not_called()

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    @mock.patch("app.cli.load_settings")
    def test_verbose_fetch_failure_logs_traceback(
        self,
        load_settings,
        get_api_key,
        load_pipeline,
    ):
        load_settings.return_value = {
            "provider": "openai",
            "openai_model": "gpt-4o",
            "gemini_model": "gemini-2.5-flash-lite",
            "output_dir": "/settings/out",
            "cookie_browser": "",
            "instagram_session_id": "",
            "instagram_csrf_token": "",
        }
        get_api_key.return_value = "settings-key"
        fetch_post = mock.Mock(side_effect=RuntimeError("fetch failed"))
        summarize = mock.Mock()
        write_note = mock.Mock()
        load_pipeline.return_value = (fetch_post, summarize, write_note)

        from app.cli import run

        stderr = io.StringIO()
        with mock.patch("app.cli.logger.exception") as log_exception:
            code = run(["--verbose", "https://instagram.com/p/one"], stderr=stderr)

        self.assertEqual(code, 1)
        self.assertIn("fetch failed", stderr.getvalue())
        log_exception.assert_called_once_with(
            "Error processing %s",
            "https://instagram.com/p/one",
        )
        summarize.assert_not_called()
        write_note.assert_not_called()

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    def test_empty_url_file_exits_before_api_key_lookup(
        self,
        get_api_key,
        load_pipeline,
    ):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("\n")
            handle.write("# ignored\n")
            handle.write("  # also ignored\n")
            path = handle.name

        self.addCleanup(Path(path).unlink)

        from app.cli import run

        stderr = io.StringIO()
        code = run(["--url-file", path], stderr=stderr)

        self.assertNotEqual(code, 0)
        self.assertIn("No URLs", stderr.getvalue())
        get_api_key.assert_not_called()
        load_pipeline.assert_not_called()

    @mock.patch("app.cli._load_pipeline")
    @mock.patch("app.cli.get_api_key")
    @mock.patch("app.cli.load_settings")
    @mock.patch("app.cli.load_env")
    def test_invalid_url_exits_before_api_key_lookup(
        self,
        load_env,
        load_settings,
        get_api_key,
        load_pipeline,
    ):
        from app.cli import run

        stderr = io.StringIO()
        code = run(["not-a-url"], stderr=stderr)

        self.assertNotEqual(code, 0)
        self.assertIn("Invalid URL", stderr.getvalue())
        load_env.assert_not_called()
        load_settings.assert_not_called()
        get_api_key.assert_not_called()
        load_pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
