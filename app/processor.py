"""
AI processing layer for InstaSum-Image.
Handles multi-stage VLM prompting for OCR + summarization.
Supports OpenAI (gpt-4o) and Google Gemini (gemini-2.5-flash-lite).
Local EasyOCR runs first and feeds extracted text into the VLM Stage 1 prompt.
"""

import base64
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EasyOCR — hardware-aware reader + extraction helpers
# ---------------------------------------------------------------------------

def get_optimized_reader():
    """Return an easyocr.Reader using the best available hardware backend."""
    try:
        import torch
    except ImportError:
        raise ImportError("torch is not installed")
    try:
        import easyocr
    except ImportError:
        raise ImportError("easyocr is not installed")

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    logger.info("EasyOCR running on: %s", device)
    return easyocr.Reader(["en", "es"], gpu=(device != "cpu"))


def run_easyocr(image_paths: list[str], log_cb: Callable[[str], None]) -> str:
    """
    Run EasyOCR on every image and return a formatted string, one block per image.
    Falls back gracefully if easyocr / torch are not installed.
    """
    try:
        reader = get_optimized_reader()
    except (ImportError, Exception) as exc:
        log_cb(f"  [EasyOCR] Skipping local OCR pre-pass: {exc}")
        return ""

    blocks: list[str] = []
    for i, path in enumerate(image_paths, start=1):
        log_cb(f"  [EasyOCR] Scanning Image {i}…")
        results = reader.readtext(path, detail=0, paragraph=True)
        text = "\n".join(results).strip()
        blocks.append(f"=== Image {i} (local OCR) ===\n{text if text else '(no text detected)'}")

    return "\n\n".join(blocks)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert knowledge extractor and summarizer.
You will be given one or more images from an Instagram post, plus the post caption.
Your job is to extract all valuable information and produce a clean, structured summary.
Be precise. Do not hallucinate content that is not present in the images or caption."""

STAGE1_OCR_PROMPT_BASE = """Stage 1 — OCR & Raw Extraction

{easyocr_section}Look at every image carefully. Extract ALL text you can see, including:
- Headings, titles, bullet points
- Body text, callouts, quotes
- Numbers, statistics, dates
- Author names, source attributions

Return a structured list of everything visible. Label each image as Image 1, Image 2, etc."""

_EASYOCR_PREAMBLE = """A local OCR pass has already extracted the following raw text from the images.
Use it as a starting reference, but verify against the images directly — it may contain errors.

{easyocr_text}

---

"""


def _build_stage1_prompt(easyocr_text: str) -> str:
    if easyocr_text.strip():
        section = _EASYOCR_PREAMBLE.format(easyocr_text=easyocr_text)
    else:
        section = ""
    return STAGE1_OCR_PROMPT_BASE.format(easyocr_section=section)

STAGE2_SYNTHESIS_PROMPT = """Stage 2 — Synthesis & Deduplication

You now have:
- The raw OCR text from each image (above)
- The post caption: {caption}

Cross-reference both sources and:
1. Remove duplicate information that appears in both the caption and the images.
2. Identify the main topic or thesis of this post.
3. List the key insights or takeaways (max 7 bullet points).
4. Note any actionable advice, frameworks, or named concepts.

Return your synthesis in this exact format:

### Main Topic
<one sentence>

### Key Insights
- <insight 1>
- <insight 2>
...

### Actionable Takeaways
- <takeaway 1>
...

### Named Concepts / Frameworks
- <concept> — <brief explanation>
(omit section if none)

### Source Details
- Caption author claim: <any author/source named>
- Post date context: <any dates mentioned>"""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SummaryResult:
    ocr_raw: str
    synthesis: str
    provider: str
    model: str


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def summarize(
    image_paths: list[str],
    caption: str,
    provider: str,
    api_key: str,
    model: str | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> SummaryResult:
    """
    Run two-stage VLM summarization on the given images + caption.

    provider: "openai" | "gemini"
    """
    def _log(msg: str):
        logger.info(msg)
        if log_cb:
            log_cb(msg)

    _log(f"Starting AI processing with {provider}…")

    _log("  Running local EasyOCR pre-pass…")
    easyocr_text = run_easyocr(image_paths, _log)
    stage1_prompt = _build_stage1_prompt(easyocr_text)

    if provider == "openai":
        return _process_openai(image_paths, caption, api_key, model or "gpt-4o", _log, stage1_prompt)
    elif provider == "gemini":
        return _process_gemini(image_paths, caption, api_key, model or "gemini-2.5-flash-lite", _log, stage1_prompt)
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------

def _encode_image_b64(path: str) -> tuple[str, str]:
    """Return (base64_data, mime_type)."""
    suffix = Path(path).suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}
    mime = mime_map.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, mime


def _build_openai_image_messages(image_paths: list[str]) -> list[dict]:
    parts = []
    for i, path in enumerate(image_paths):
        data, mime = _encode_image_b64(path)
        parts.append({"type": "text", "text": f"Image {i + 1}:"})
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{data}", "detail": "high"},
        })
    return parts


def _process_openai(
    image_paths: list[str],
    caption: str,
    api_key: str,
    model: str,
    log_cb,
    stage1_prompt: str,
) -> SummaryResult:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    # --- Stage 1: OCR ---
    log_cb("  Stage 1: OCR extraction…")
    image_parts = _build_openai_image_messages(image_paths)
    ocr_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": image_parts + [{"type": "text", "text": stage1_prompt}],
        },
    ]
    ocr_response = client.chat.completions.create(
        model=model,
        messages=ocr_messages,
        max_tokens=4096,
    )
    ocr_raw = ocr_response.choices[0].message.content.strip()
    log_cb("  Stage 1 complete.")

    # --- Stage 2: Synthesis ---
    log_cb("  Stage 2: Synthesis & summarization…")
    synthesis_prompt = STAGE2_SYNTHESIS_PROMPT.format(caption=caption or "(no caption)")
    synthesis_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": image_parts + [{"type": "text", "text": stage1_prompt}],
        },
        {"role": "assistant", "content": ocr_raw},
        {"role": "user", "content": synthesis_prompt},
    ]
    synth_response = client.chat.completions.create(
        model=model,
        messages=synthesis_messages,
        max_tokens=4096,
    )
    synthesis = synth_response.choices[0].message.content.strip()
    log_cb("  Stage 2 complete.")

    return SummaryResult(ocr_raw=ocr_raw, synthesis=synthesis, provider="openai", model=model)


# ---------------------------------------------------------------------------
# Gemini implementation  (uses google-genai >= 1.0, the current SDK)
# ---------------------------------------------------------------------------

def _gemini_image_part(path: str):
    """Return a google.genai types.Part built from a local image file."""
    from google.genai import types

    suffix = Path(path).suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}
    mime = mime_map.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        raw = f.read()
    return types.Part.from_bytes(data=raw, mime_type=mime)


def _process_gemini(
    image_paths: list[str],
    caption: str,
    api_key: str,
    model: str,
    log_cb,
    stage1_prompt: str,
) -> SummaryResult:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    gen_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
    )

    # Build the image parts list once (reused in both stages).
    image_parts: list = []
    for i, path in enumerate(image_paths):
        image_parts.append(types.Part.from_text(text=f"Image {i + 1}:"))
        image_parts.append(_gemini_image_part(path))

    # --- Stage 1: OCR ---
    log_cb("  Stage 1: OCR extraction…")
    stage1_user_parts = image_parts + [types.Part.from_text(text=stage1_prompt)]

    ocr_response = client.models.generate_content(
        model=model,
        config=gen_config,
        contents=[types.Content(role="user", parts=stage1_user_parts)],
    )
    ocr_raw = ocr_response.text.strip()
    log_cb("  Stage 1 complete.")

    # --- Stage 2: Synthesis (multi-turn conversation) ---
    log_cb("  Stage 2: Synthesis & summarization…")
    synthesis_prompt = STAGE2_SYNTHESIS_PROMPT.format(caption=caption or "(no caption)")

    stage2_contents = [
        types.Content(role="user",  parts=stage1_user_parts),
        types.Content(role="model", parts=[types.Part.from_text(text=ocr_raw)]),
        types.Content(role="user",  parts=[types.Part.from_text(text=synthesis_prompt)]),
    ]

    synth_response = client.models.generate_content(
        model=model,
        config=gen_config,
        contents=stage2_contents,
    )
    synthesis = synth_response.text.strip()
    log_cb("  Stage 2 complete.")

    return SummaryResult(ocr_raw=ocr_raw, synthesis=synthesis, provider="gemini", model=model)
