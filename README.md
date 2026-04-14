# InstaSum-Image

BYOK desktop app that fetches Instagram posts, runs local OCR, and produces structured Markdown summaries via a VLM (OpenAI or Gemini). Bring your own API key — nothing is stored remotely.

---

## Features

- **Two-stage pipeline** — local EasyOCR extracts text first; a VLM cross-references and synthesizes
- **Carousel support** — handles single posts and multi-image slideshows
- **Login-wall bypass** — borrows cookies from your browser when a post requires authentication
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
# 1. System dependencies
brew install python-tk@3.14   # match your Python version

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

```bash
source .venv/bin/activate
python main.py
```

1. Paste an Instagram post URL
2. Enter your API key (saved locally to `~/.config/instasum/config.env`)
3. Choose a provider and browser session (optional, for private posts)
4. Click **Summarize**
5. Find your Markdown note in the configured output folder (default: `~/Documents/InstaSum`)

---

## Configuration

API keys and settings persist in `~/.config/instasum/`. You can also place a `.env` file in the project root:

```bash
cp .env.example .env
# edit .env and fill in your keys
```

| Setting | Default | Description |
|---|---|---|
| `output_dir` | `~/Documents/InstaSum` | Where notes are saved |
| `provider` | `openai` | `openai` or `gemini` |
| `openai_model` | `gpt-4o` | OpenAI model ID |
| `gemini_model` | `gemini-2.5-flash-lite` | Gemini model ID |
| `cookie_browser` | _(none)_ | Browser to borrow cookies from |

---

## Project Structure

```
InstaSum-Image/
├── main.py              # Entry point
├── requirements.txt
├── .env.example
└── app/
    ├── config.py        # Settings & API key persistence
    ├── fetcher.py       # yt-dlp metadata + image download
    ├── processor.py     # EasyOCR + VLM two-stage pipeline
    ├── writer.py        # Markdown / Obsidian note generation
    └── gui.py           # customtkinter GUI
```

---

## Privacy

- API keys stored locally in `~/.config/instasum/config.env`
- Images downloaded to a temp folder, deleted after processing
- No telemetry, no accounts, no cloud sync
