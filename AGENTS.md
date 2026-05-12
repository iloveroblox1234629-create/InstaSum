<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **InstaSum** (261 symbols, 427 relationships, 14 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/InstaSum/context` | Codebase overview, check index freshness |
| `gitnexus://repo/InstaSum/clusters` | All functional areas |
| `gitnexus://repo/InstaSum/processes` | All execution flows |
| `gitnexus://repo/InstaSum/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# InstaSum-Image

## Quick Start

```bash
source .venv/bin/activate  # macOS/Linux
python main.py
```

## Setup Notes

- **Python 3.11+** required
- **Virtual environment**: `.venv` (already in `.gitignore`)
- **macOS**: `brew install python-tk@$(python3 --version | awk '{print $2}' | cut -d. -f1,2)`
- **Linux**: `pip install -r requirements.txt` (torch defaults to CUDA — several GB)
- **CPU/MPS only**: `pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu`

## Architecture

- **Entry point**: `main.py` → `app.gui.App` (customtkinter)
- **Pipeline**: `fetcher.py` (gallery-dl feed posts/carousels, yt-dlp Reels) → `processor.py` (EasyOCR + VLM) → `writer.py` (Markdown)
- **Config**: `~/.config/instasum/config.env` (API keys) + `settings.json` (preferences)
- **Optional**: `.env` in project root (loaded as fallback)
- **OCR hardware**: auto-selects CUDA → Apple MPS → CPU

## Important

- **No test suite** — none configured; verify changes manually
- **No CI/CD** — no GitHub Actions or linting setup
- **Secrets**: API keys stored locally, never commit `~/.config/instasum/` or `.env`
- **Dependencies**: `requirements.txt` is the single source of truth (no pyproject.toml)
