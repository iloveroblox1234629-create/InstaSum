# InstaSum-Image CLI

BYOK command-line tool that fetches Instagram posts, runs local OCR, and produces structured Markdown summaries via a VLM (OpenAI or Gemini). Bring your own API key; nothing is stored remotely.

---

## Features

- **Two-stage pipeline** — local EasyOCR extracts text first; a VLM cross-references and synthesizes
- **Carousel support** — uses gallery-dl for feed posts and carousels, yt-dlp for Reels
- **Login-wall bypass** — borrows cookies from your browser when a post requires authentication
- **Batch input** — pass URLs directly or read them from a text file
- **BYOK** — OpenAI (`gpt-4o`) or Google Gemini (`gemini-2.5-flash-lite`), your key, your cost
- **Obsidian-ready output** — saves Markdown notes with YAML frontmatter to any folder you choose
- **Hardware-aware OCR** — auto-selects CUDA → Apple MPS → CPU

---

## Requirements

- Python 3.11+
- macOS, Linux, or Windows
- An OpenAI or Gemini API key

---

## Installation

### macOS (Homebrew)

```bash
# 1. System dependencies — match your Python version (e.g. @3.11, @3.12, @3.13)
brew install python-tk@$(python3 --version | awk '{print $2}' | cut -d. -f1,2)

# 2. Clone
git clone https://github.com/your-username/InstaSum-Image.git
cd InstaSum-Image

# 3. Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Python dependencies
pip install -r requirements.txt
```

> **Apple Silicon note:** `torch` and `easyocr` install CPU wheels by default via pip. MPS acceleration works automatically at runtime — no extra steps needed.

### Linux

```bash
pip install -r requirements.txt
```

---

## Usage

Run one or more URLs directly:

```bash
source .venv/bin/activate
python main.py https://www.instagram.com/p/POST_ID/
python main.py https://www.instagram.com/reel/REEL_ID/ https://www.instagram.com/p/POST_ID/
```

Read URLs from a file:

```bash
python main.py --url-file urls.txt
```

`urls.txt` accepts one URL per line. Blank lines and lines starting with `#` are ignored.

Use explicit CLI overrides:

```bash
python main.py \
  --provider gemini \
  --api-key "$GEMINI_API_KEY" \
  --model gemini-2.5-flash-lite \
  --output-dir ~/Documents/InstaSum \
  --browser chrome \
  https://www.instagram.com/p/POST_ID/
```

For private posts, either use browser cookies:

```bash
python main.py --browser safari https://www.instagram.com/p/POST_ID/
```

or pass Instagram session cookies manually:

```bash
python main.py \
  --session-id "$INSTAGRAM_SESSION_ID" \
  --csrf-token "$INSTAGRAM_CSRF_TOKEN" \
  https://www.instagram.com/p/POST_ID/
```

Each successful URL prints the saved Markdown note path. If some URLs fail, the command prints a failure summary and exits nonzero.

### CLI Options

```text
usage: instasum-image [-h] [--url-file URL_FILE] [--provider {openai,gemini}]
                      [--api-key API_KEY] [--output-dir OUTPUT_DIR]
                      [--browser BROWSER] [--session-id SESSION_ID]
                      [--csrf-token CSRF_TOKEN] [--model MODEL] [--verbose]
                      [urls ...]
```

| Option | Description |
|---|---|
| `urls` | Instagram post or Reel URLs |
| `--url-file` | File containing one URL per line |
| `--provider` | `openai` or `gemini`; defaults to saved settings |
| `--api-key` | API key override for the selected provider |
| `--output-dir` | Markdown output directory override |
| `--browser` | Browser cookie source, such as `chrome`, `firefox`, `safari`, or `none` |
| `--session-id` | Instagram `sessionid` cookie override |
| `--csrf-token` | Instagram `csrftoken` cookie override |
| `--model` | VLM model override |
| `--verbose` | Enable debug logging and tracebacks for failures |

---

## Configuration

API keys and settings persist in `~/.config/instasum/`. You can also place a `.env` file in the project root:

```bash
OPENAI_API_KEY=...
GEMINI_API_KEY=...
```

| Setting | Default | Description |
|---|---|---|
| `output_dir` | `~/Documents/InstaSum` | Where notes are saved |
| `provider` | `openai` | `openai` or `gemini` |
| `openai_model` | `gpt-4o` | OpenAI model ID |
| `gemini_model` | `gemini-2.5-flash-lite` | Gemini model ID |
| `cookie_browser` | _(none)_ | Browser to borrow cookies from |
| `instagram_session_id` | _(none)_ | Optional Instagram `sessionid` cookie |
| `instagram_csrf_token` | _(none)_ | Optional Instagram `csrftoken` cookie |

---

## Project Structure

```
InstaSum-Image/
├── main.py              # CLI entry point
├── requirements.txt
├── tests/
│   └── test_cli.py      # CLI behavior tests
└── app/
    ├── cli.py           # argparse CLI and pipeline orchestration
    ├── config.py        # Settings & API key persistence
    ├── fetcher.py       # gallery-dl feed/carousel download + yt-dlp Reels metadata
    ├── processor.py     # EasyOCR + VLM two-stage pipeline
    ├── writer.py        # Markdown / Obsidian note generation
    └── gui.py           # Legacy CustomTkinter GUI module, not used by main.py on this branch
```

---

## Privacy

- API keys stored locally in `~/.config/instasum/config.env`
- Images downloaded to a temp folder, deleted after processing
- No telemetry, no accounts, no cloud sync
