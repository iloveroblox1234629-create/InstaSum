"""
Output layer for InstaSum-Image.
Generates Markdown notes with YAML frontmatter (Obsidian-compatible).
"""

import re
import logging
from datetime import datetime
from pathlib import Path

from .fetcher import PostData
from .processor import SummaryResult

logger = logging.getLogger(__name__)


def write_note(
    post: PostData,
    result: SummaryResult,
    output_dir: str,
) -> Path:
    """
    Persist the summarized note as a Markdown file.

    Returns the path to the written file.
    """
    out_path = Path(output_dir).expanduser()
    out_path.mkdir(parents=True, exist_ok=True)

    filename = _make_filename(post)
    file_path = out_path / filename

    # Avoid silently overwriting — append counter if file exists
    counter = 1
    stem = file_path.stem
    while file_path.exists():
        file_path = out_path / f"{stem}_{counter}.md"
        counter += 1

    content = _render_note(post, result)
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Note saved to: {file_path}")
    return file_path


def _make_filename(post: PostData) -> str:
    date_str = _format_date(post.upload_date)
    safe_title = re.sub(r"[^\w-]", "_", post.title)[:50].strip("_")
    return f"{date_str}_{safe_title}.md"


def _format_date(upload_date: str) -> str:
    """Convert YYYYMMDD → YYYY-MM-DD, gracefully."""
    try:
        return datetime.strptime(upload_date, "%Y%m%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.now().strftime("%Y-%m-%d")


def _render_note(post: PostData, result: SummaryResult) -> str:
    date_iso = _format_date(post.upload_date)
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    image_count = len(post.image_paths)
    post_type = "carousel" if image_count > 1 else "single"

    frontmatter = f"""---
title: "{post.title.replace('"', "'")}"
source: "{post.url}"
date: {date_iso}
processed_at: {now_iso}
provider: {result.provider}
model: {result.model}
post_type: {post_type}
image_count: {image_count}
tags:
  - instagram
  - instasum
---
"""

    caption_section = ""
    if post.caption:
        escaped_caption = post.caption.replace("```", "~~~")
        caption_section = f"""
## Original Caption

```
{escaped_caption}
```
"""

    body = f"""{frontmatter}
# {post.title}

> **Source:** [{post.url}]({post.url})
> **Date:** {date_iso}  |  **Images:** {image_count}  |  **Model:** {result.provider}/{result.model}
{caption_section}
---

## Summary

{result.synthesis}

---

## Raw OCR Output

<details>
<summary>Expand raw OCR text</summary>

{result.ocr_raw}

</details>
"""
    return body
