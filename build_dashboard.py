#!/usr/bin/env python3
"""
Render a daily bird dashboard image for an e-ink display.

Expected input: birds.json
Expected output directory: public/

Example:
    python build_dashboard.py --width 600 --height 448 --out public
    python build_dashboard.py --width 1200 --height 1600 --out public \
        --image-format jpeg --ee02-palette
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import random
import re
import sys
import textwrap
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


DEFAULT_TIMEZONE = "America/Los_Angeles"
BIRDNET_API_BASE = "https://birdnet.cornell.edu/taxonomy/api"
WIKIPEDIA_SUMMARY_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"
USER_AGENT = "bird-inky-dashboard/1.0 (+https://github.com/)"

BLACK = (20, 24, 27)
WHITE = (255, 255, 252)
PAPER = (248, 246, 236)
RED = (194, 48, 47)
YELLOW = (238, 194, 72)
BLUE = (55, 104, 146)
GREEN = (65, 132, 92)
LIGHT_GRAY = (222, 220, 207)
MID_GRAY = (105, 108, 105)


@dataclass
class Bird:
    common_name: str
    scientific_name: str
    facts: list[str]
    image_url: str | None = None
    image_path: str | None = None
    image_credit: str | None = None
    image_license: str | None = None
    source_url: str | None = None
    status: str | None = None
    habitat: str | None = None
    range: str | None = None
    description: str | None = None
    source_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bird":
        facts = data.get("facts") or []
        if isinstance(facts, str):
            facts = [facts]

        return cls(
            common_name=str(data.get("common_name") or data.get("name") or "").strip(),
            scientific_name=str(data.get("scientific_name") or data.get("sci_name") or "").strip(),
            facts=[str(f).strip() for f in facts if str(f).strip()],
            image_url=clean_optional(data.get("image_url")),
            image_path=clean_optional(data.get("image_path")),
            image_credit=clean_optional(data.get("image_credit") or data.get("credit")),
            image_license=clean_optional(data.get("image_license") or data.get("license")),
            source_url=clean_optional(data.get("source_url") or data.get("url")),
            status=clean_optional(data.get("status")),
            habitat=clean_optional(data.get("habitat")),
            range=clean_optional(data.get("range")),
            description=clean_optional(data.get("description")),
            source_name=clean_optional(data.get("source_name")),
        )


def clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build today's e-ink bird dashboard.")
    parser.add_argument("--birds", default="birds.json", help="Path to the bird list JSON.")
    parser.add_argument("--out", default="public", help="Output directory for GitHub Pages.")
    parser.add_argument("--width", type=int, default=600, help="Display width in pixels.")
    parser.add_argument("--height", type=int, default=448, help="Display height in pixels.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA timezone for date selection.")
    parser.add_argument("--date", help="Override date as YYYY-MM-DD. Useful for testing.")
    parser.add_argument("--seed", help="Optional extra seed string for bird selection.")
    parser.add_argument("--saturation", type=float, default=0.95, help="Photo color saturation multiplier.")
    parser.add_argument(
        "--image-format",
        default="png",
        choices=["png", "jpeg"],
        help="Dashboard image format. JPEG is published as today.jpg.",
    )
    parser.add_argument(
        "--ee02-palette",
        action="store_true",
        help="Dither the output to the EE02 panel's six-color palette.",
    )
    parser.add_argument("--birdnet-size", default="medium", choices=["thumb", "medium"], help="BirdNET image size.")
    parser.add_argument("--no-birdnet", action="store_true", help="Do not enrich entries from BirdNET.")
    parser.add_argument("--no-wikipedia", action="store_true", help="Do not enrich entries from Wikipedia summaries.")
    parser.add_argument("--require-image", action="store_true", help="Fail instead of rendering a placeholder.")
    return parser.parse_args()


def load_birds(path: Path) -> list[Bird]:
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Create it with an array of birds containing "
            "common_name, scientific_name, facts, image_url, and attribution fields."
        )

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise SystemExit(f"{path} must contain a JSON array.")

    birds = [Bird.from_dict(item) for item in raw if isinstance(item, dict)]
    birds = [b for b in birds if b.scientific_name or b.common_name]

    if not birds:
        raise SystemExit(f"{path} did not contain any usable birds.")

    return birds


def selected_date(tz_name: str, override: str | None) -> str:
    if override:
        datetime.strptime(override, "%Y-%m-%d")
        return override

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    return datetime.now(tz).date().isoformat()


def choose_bird(birds: list[Bird], date_text: str, seed: str | None) -> Bird:
    material = f"{date_text}:{seed or ''}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    index = int(digest[:12], 16) % len(birds)
    return birds[index]


def birdnet_species_url(scientific_name: str) -> str:
    encoded = urllib.parse.quote(scientific_name, safe="")
    return f"{BIRDNET_API_BASE}/species/{encoded}"


def birdnet_image_url(scientific_name: str, size: str) -> str:
    encoded = urllib.parse.quote(scientific_name, safe="")
    query = urllib.parse.urlencode({"size": size})
    return f"{BIRDNET_API_BASE}/image/{encoded}?{query}"


def wikipedia_summary_url(title: str) -> str:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    return f"{WIKIPEDIA_SUMMARY_BASE}/{encoded}"


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def enrich_from_birdnet(bird: Bird, image_size: str) -> tuple[Bird, list[str]]:
    warnings: list[str] = []
    if not bird.scientific_name:
        warnings.append("BirdNET enrichment skipped because scientific_name is missing.")
        return bird, warnings

    if not bird.image_url and not bird.image_path:
        bird.image_url = birdnet_image_url(bird.scientific_name, image_size)

    needs_species = not bird.common_name or not bird.facts or not bird.status or not bird.range or not bird.source_url
    if not needs_species:
        return bird, warnings

    try:
        record = fetch_json(birdnet_species_url(bird.scientific_name))
    except Exception as exc:  # noqa: BLE001 - the dashboard can still render with local fields.
        warnings.append(f"BirdNET species lookup failed: {exc}")
        return bird, warnings

    if "species" in record and isinstance(record["species"], dict):
        record = record["species"]

    bird.common_name = bird.common_name or first_text_deep(
        record,
        "common_name",
        "commonName",
        "english_common_name",
        "name",
    ) or bird.scientific_name
    bird.description = bird.description or first_text_deep(record, "description", "summary", "extract")
    bird.status = bird.status or first_text_deep(record, "conservation_status", "status")
    bird.range = bird.range or first_text_deep(record, "range", "distribution")
    bird.habitat = bird.habitat or first_text_deep(record, "habitat")
    bird.source_url = bird.source_url or first_text_deep(record, "wikipedia_url", "source_url")
    bird.source_name = bird.source_name or "BirdNET+ Taxonomy"

    if not bird.image_credit:
        bird.image_credit = first_text_deep(record, "image_credit", "image_attribution", "photo_credit", "photographer")
    if not bird.image_license:
        bird.image_license = first_text_deep(record, "image_license", "license")

    if not bird.facts:
        bird.facts = facts_from_species_record(bird, record)

    return bird, warnings


def enrich_from_wikipedia(bird: Bird) -> tuple[Bird, list[str]]:
    warnings: list[str] = []
    titles = wikipedia_title_candidates(bird)

    for title in titles:
        try:
            record = fetch_json(wikipedia_summary_url(title))
        except Exception as exc:  # noqa: BLE001 - fallback source only.
            warnings.append(f"Wikipedia summary lookup failed for {title}: {exc}")
            continue

        if record.get("type") == "disambiguation":
            warnings.append(f"Wikipedia summary for {title} was a disambiguation page.")
            continue

        extract = clean_optional(record.get("extract"))
        if not extract:
            warnings.append(f"Wikipedia summary for {title} did not include an extract.")
            continue

        if not bird.image_url and not bird.image_path:
            bird.image_url = wikipedia_image_url(record)

        bird.description = choose_better_description(bird.description, extract)
        bird.source_url = bird.source_url or wikipedia_page_url(record)
        bird.source_name = bird.source_name or "Wikipedia"
        bird.facts = merge_facts(bird.facts, facts_from_overview(bird, extract), limit=6)
        return bird, warnings

    return bird, warnings


def wikipedia_title_candidates(bird: Bird) -> list[str]:
    candidates: list[str] = []

    if bird.source_url and "wikipedia.org/wiki/" in bird.source_url:
        title = bird.source_url.rsplit("/wiki/", 1)[-1]
        title = urllib.parse.unquote(title).replace("_", " ")
        candidates.append(title)

    for value in [bird.common_name, bird.scientific_name]:
        if value:
            candidates.append(value)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        key = candidate.casefold()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def wikipedia_page_url(record: dict[str, Any]) -> str | None:
    urls = record.get("content_urls")
    if isinstance(urls, dict):
        desktop = urls.get("desktop")
        if isinstance(desktop, dict):
            page = desktop.get("page")
            if isinstance(page, str) and page.strip():
                return page.strip()
    return None


def wikipedia_image_url(record: dict[str, Any]) -> str | None:
    # The summary API's thumbnail is already a web-friendly raster and is
    # normally large enough for the e-ink photo panel. Fall back to the
    # original image when a page does not provide a thumbnail.
    for key in ["thumbnail", "originalimage"]:
        image = record.get(key)
        if isinstance(image, dict):
            source = clean_optional(image.get("source"))
            if source:
                return source
    return None


def choose_better_description(current: str | None, candidate: str) -> str:
    if not current:
        return candidate
    if "BirdNET recognizes this species" in current:
        return candidate
    if len(candidate) > len(current) * 1.4:
        return candidate
    return current


def first_text(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def first_text_deep(data: Any, *keys: str) -> str | None:
    wanted = {normalize_key(key) for key in keys}

    def walk(value: Any) -> str | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if normalize_key(str(key)) in wanted:
                    text = coerce_text(item)
                    if text:
                        return text
                found = walk(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = walk(item)
                if found:
                    return found
        return None

    return walk(data)


def first_value_deep(data: Any, *keys: str) -> Any:
    wanted = {normalize_key(key) for key in keys}

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            for key, item in value.items():
                if normalize_key(str(key)) in wanted:
                    return item
                found = walk(item)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = walk(item)
                if found is not None:
                    return found
        return None

    return walk(data)


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_optional(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ["en", "text", "plain", "value", "label", "description", "name"]:
            text = coerce_text(value.get(key))
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = coerce_text(item)
            if text:
                return text
    return None


def facts_from_species_record(bird: Bird, record: dict[str, Any]) -> list[str]:
    facts: list[str] = []

    if bird.description:
        facts.extend(facts_from_overview(bird, bird.description))

    if bird.range and len(facts) < 4:
        facts.append(f"Typically found: {bird.range}")

    if bird.habitat and len(facts) < 4:
        facts.append(f"Habitat: {bird.habitat}")

    if bird.status and len(facts) < 4:
        facts.append(f"Conservation status: {expanded_status(bird.status)}")

    observation_count = first_value_deep(record, "observations", "inat_observations", "observation_count")
    if observation_count and len(facts) < 4:
        facts.append(f"BirdNET taxonomy lists {format_count(observation_count)} iNaturalist observations.")

    if not facts:
        facts.append(f"Scientific name: {bird.scientific_name}.")

    return facts[:4]


def facts_from_overview(bird: Bird, overview: str) -> list[str]:
    facts = sentences_from_text(overview, limit=4)
    useful: list[str] = []

    for sentence in facts:
        lower = sentence.casefold()
        if lower.startswith(bird.scientific_name.casefold()):
            continue
        useful.append(sentence)

    if bird.range:
        useful.append(f"Typically found: {bird.range}")
    if bird.habitat:
        useful.append(f"Habitat: {bird.habitat}")
    if bird.status:
        useful.append(f"Conservation status: {expanded_status(bird.status)}")

    return merge_facts([], useful, limit=6)


def merge_facts(existing: list[str], additions: list[str], limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for fact in existing + additions:
        if not fact or "BirdNET recognizes this species" in fact:
            continue
        clean = re.sub(r"\s+", " ", fact).strip()
        key = clean.casefold()
        if clean and key not in seen:
            merged.append(clean)
            seen.add(key)
        if len(merged) >= limit:
            break

    return merged


def expanded_status(status: str) -> str:
    codes = {
        "LC": "Least Concern",
        "NT": "Near Threatened",
        "VU": "Vulnerable",
        "EN": "Endangered",
        "CR": "Critically Endangered",
        "EW": "Extinct in the Wild",
        "EX": "Extinct",
        "DD": "Data Deficient",
        "NE": "Not Evaluated",
    }
    stripped = status.strip()
    return f"{codes[stripped]} ({stripped})" if stripped in codes else stripped


def format_count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def sentences_from_text(text: str, limit: int) -> list[str]:
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [part.strip() for part in parts if part.strip()]
    return sentences[:limit]


def font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.ImageFont:
    names = []
    if bold and italic:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-BoldItalic.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
        ]
    elif bold:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ]
    elif italic:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
            "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        ]
    else:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]

    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)

    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_pixels(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_size(draw, candidate, fnt)[0] <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        if text_size(draw, word, fnt)[0] <= max_width:
            current = word
        else:
            lines.extend(split_long_word(draw, word, fnt, max_width))

    if current:
        lines.append(current)

    return lines or [""]


def summarize_fact_for_panel(
    draw: ImageDraw.ImageDraw,
    fact: str,
    fnt: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 3,
) -> str:
    """Return the longest complete, concise version that fits the bullet area."""
    candidates = fact_summary_candidates(fact)
    for candidate in candidates:
        if len(wrap_pixels(draw, candidate, fnt, max_width)) <= max_lines:
            return candidate
    return candidates[-1]


def fact_summary_candidates(fact: str) -> list[str]:
    """Build extractive summaries without chopping a sentence mid-word or mid-clause."""
    clean = re.sub(r"\s+", " ", fact).strip()
    if not clean:
        return [""]

    candidates = [clean]
    first_sentence = sentences_from_text(clean, limit=1)
    if first_sentence and first_sentence[0] != clean:
        candidates.append(first_sentence[0])

    simplified = re.sub(r"\s*\([^)]*\)", "", candidates[-1])
    simplified = re.sub(
        r",\s*(?:(?:also|sometimes)\s+)?(?:known|called|referred to)\b.*?,\s*(?=(?:is|are|was|were)\b)",
        " ",
        simplified,
        flags=re.IGNORECASE,
    )
    simplified = re.sub(r"\s+", " ", simplified).strip()
    candidates.append(simplified)

    # These boundaries usually introduce supporting detail. Keeping the text
    # before them produces a short, grammatical fact rather than an ellipsis.
    boundary_pattern = re.compile(
        r";|\s+[—–]\s+|,\s+(?=(?:which|where|while|although|though|because|"
        r"including|especially|with|more than|making|giving|allowing|through)\b)",
        flags=re.IGNORECASE,
    )
    for base in list(candidates):
        matches = list(boundary_pattern.finditer(base))
        for match in reversed(matches):
            prefix = complete_fact_sentence(base[: match.start()])
            if looks_like_complete_fact(prefix):
                candidates.append(prefix)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = complete_fact_sentence(candidate)
        key = candidate.casefold()
        if candidate and key not in seen:
            unique.append(candidate)
            seen.add(key)

    # The renderer tries longest summaries first, preserving as much useful
    # detail as the allocated space permits.
    return sorted(unique, key=len, reverse=True)


def complete_fact_sentence(text: str) -> str:
    text = text.strip().rstrip(" ,;:—–-")
    if text and text[-1] not in ".!?":
        text += "."
    return text


def looks_like_complete_fact(text: str) -> bool:
    words = re.findall(r"[A-Za-z']+", text.casefold())
    if len(words) < 4:
        return False
    verbs = {
        "am",
        "are",
        "can",
        "contains",
        "feeds",
        "flies",
        "has",
        "have",
        "hunts",
        "includes",
        "is",
        "lives",
        "migrates",
        "nests",
        "occurs",
        "prefers",
        "ranges",
        "uses",
        "was",
        "were",
    }
    return any(word in verbs or word.endswith(("ed", "ing")) for word in words)


def split_long_word(draw: ImageDraw.ImageDraw, word: str, fnt: ImageFont.ImageFont, max_width: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if text_size(draw, candidate, fnt)[0] <= max_width:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = char
    if current:
        parts.append(current)
    return parts


def ellipsize(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_width: int) -> str:
    if text_size(draw, text, fnt)[0] <= max_width:
        return text
    suffix = "..."
    while text and text_size(draw, text + suffix, fnt)[0] > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def load_bird_image(
    bird: Bird,
    target: tuple[int, int],
    saturation: float,
) -> tuple[Image.Image, str | None, dict[str, Any]]:
    warning = None
    source: Image.Image | None = None
    details: dict[str, Any] = {
        "loaded": False,
        "url": bird.image_url,
        "path": bird.image_path,
        "content_type": None,
        "content_length": None,
        "format": None,
    }

    try:
        if bird.image_path:
            source = Image.open(bird.image_path)
            details["format"] = source.format
        elif bird.image_url:
            request = urllib.request.Request(
                bird.image_url,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                headers = response.info()
                details["content_type"] = headers.get("Content-Type")
                details["content_length"] = headers.get("Content-Length")
                source = Image.open(io.BytesIO(response.read()))
                details["format"] = source.format
        else:
            warning = "No image_url or image_path was provided."
    except Exception as exc:  # noqa: BLE001 - warning is written to metadata.
        warning = f"Could not load image from {bird.image_url or bird.image_path or 'no source'}: {exc}"

    if source is None:
        return placeholder_image(target, bird), warning, details

    source = ImageOps.exif_transpose(source).convert("RGB")
    if saturation != 1.0:
        source = ImageEnhance.Color(source).enhance(max(0.0, saturation))

    details["loaded"] = True
    return cover_crop(source, target), warning, details


def cover_crop(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    target_w, target_h = target
    scale = max(target_w / img.width, target_h / img.height)
    resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)

    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def placeholder_image(target: tuple[int, int], bird: Bird) -> Image.Image:
    img = Image.new("RGB", target, PAPER)
    draw = ImageDraw.Draw(img)
    w, h = target

    rng = random.Random(bird.common_name)
    colors = [LIGHT_GRAY, (230, 221, 190), (220, 230, 218), (225, 213, 210)]
    step = max(18, min(w, h) // 10)

    for y in range(-step, h + step, step):
        for x in range(-step, w + step, step):
            color = rng.choice(colors)
            draw.ellipse((x, y, x + step * 2, y + step * 2), outline=color, width=2)

    title_font = font(max(22, min(w, h) // 11), bold=True)
    sub_font = font(max(14, min(w, h) // 18), italic=True)

    title_lines = wrap_pixels(draw, bird.common_name, title_font, int(w * 0.8))
    line_height = text_size(draw, "Ag", title_font)[1] + 8
    total_h = len(title_lines) * line_height + text_size(draw, bird.scientific_name, sub_font)[1] + 10
    y = (h - total_h) // 2

    for line in title_lines:
        tw, th = text_size(draw, line, title_font)
        draw.text(((w - tw) // 2, y), line, fill=BLACK, font=title_font)
        y += line_height

    sci = ellipsize(draw, bird.scientific_name, sub_font, int(w * 0.85))
    tw, _ = text_size(draw, sci, sub_font)
    draw.text(((w - tw) // 2, y), sci, fill=MID_GRAY, font=sub_font)
    return img


def draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    radius: int = 8,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def render_dashboard(
    bird: Bird,
    date_text: str,
    width: int,
    height: int,
    saturation: float,
) -> tuple[Image.Image, dict[str, Any]]:
    canvas = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)

    margin = max(14, round(min(width, height) * 0.04))
    gutter = max(12, round(min(width, height) * 0.03))
    stacked = width < 520 or height > width * 0.9

    if stacked:
        photo_box = (margin, margin, width - margin, round(height * 0.52))
        text_box = (margin, photo_box[3] + gutter, width - margin, height - margin)
    else:
        photo_w = round(width * 0.54)
        photo_box = (margin, margin, photo_w, height - margin)
        text_box = (photo_box[2] + gutter, margin, width - margin, height - margin)

    photo_target = (photo_box[2] - photo_box[0], photo_box[3] - photo_box[1])
    photo, image_warning, image_details = load_bird_image(bird, photo_target, saturation)
    canvas.paste(photo, photo_box[:2])
    draw.rectangle(photo_box, outline=BLACK, width=max(2, width // 360))

    draw_date_badge(draw, photo_box, date_text, width, height)
    draw_text_panel(draw, text_box, bird, date_text, width, height)

    metadata = {
        "date": date_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "screen": {"width": width, "height": height},
        "bird": {
            "common_name": bird.common_name,
            "scientific_name": bird.scientific_name,
            "facts": bird.facts,
            "status": bird.status,
            "habitat": bird.habitat,
            "range": bird.range,
            "description": bird.description,
            "image_url": bird.image_url,
            "image_credit": bird.image_credit,
            "image_license": bird.image_license,
            "source_url": bird.source_url,
            "source_name": bird.source_name,
        },
        "image": image_details,
        "warnings": [image_warning] if image_warning else [],
    }

    return canvas, metadata


def draw_date_badge(
    draw: ImageDraw.ImageDraw,
    photo_box: tuple[int, int, int, int],
    date_text: str,
    width: int,
    height: int,
) -> None:
    label_font = font(max(12, min(width, height) // 34), bold=True)
    date_obj = datetime.strptime(date_text, "%Y-%m-%d")
    label = date_obj.strftime("%b %-d").upper() if sys.platform != "win32" else date_obj.strftime("%b %#d").upper()

    tw, th = text_size(draw, label, label_font)
    pad_x = max(8, width // 80)
    pad_y = max(5, height // 100)
    x1 = photo_box[0] + max(8, width // 90)
    y1 = photo_box[1] + max(8, height // 90)
    box = (x1, y1, x1 + tw + pad_x * 2, y1 + th + pad_y * 2)

    draw_rounded_rect(draw, box, fill=YELLOW, outline=BLACK, radius=6, width=1)
    draw.text((x1 + pad_x, y1 + pad_y - 1), label, fill=BLACK, font=label_font)


def draw_text_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    bird: Bird,
    date_text: str,
    width: int,
    height: int,
) -> None:
    x1, y1, x2, y2 = box
    panel_w = x2 - x1
    panel_h = y2 - y1

    preferred_title_size = max(25, min(44, round(min(width, height) * 0.09)))
    preferred_fact_size = max(15, min(24, round(min(width, height) * 0.045)))
    meta_size = max(11, min(16, round(min(width, height) * 0.03)))

    meta_font = font(meta_size)
    small_bold = font(meta_size, bold=True)

    meta_parts = []
    if bird.status:
        meta_parts.append(f"Status: {bird.status}")
    if bird.habitat:
        meta_parts.append(f"Habitat: {bird.habitat}")
    if bird.range:
        meta_parts.append(f"Range: {bird.range}")

    attribution = " | ".join(
        item for item in [bird.image_credit, bird.image_license] if item
    )

    footer_lines = []
    if meta_parts:
        footer_lines.extend(wrap_pixels(draw, "  ".join(meta_parts), meta_font, panel_w))
    if attribution:
        footer_lines.extend(wrap_pixels(draw, f"Image: {attribution}", meta_font, panel_w))
    footer_lines = footer_lines[-3:]

    eyebrow = "BIRD OF THE DAY"
    eyebrow_step = text_line_step(draw, small_bold, 1.0)
    eyebrow_gap = max(8, height // 70)
    title_sci_gap = max(2, height // 160)
    facts_top_gap = max(12, height // 35)
    fact_gap = max(5, height // 100)
    bullet_w = max(10, width // 55)
    footer_step = text_line_step(draw, meta_font, 1.15)
    footer_height = len(footer_lines) * footer_step
    footer_separator_space = 12 if footer_lines else 0

    # Fit complete facts into the panel. Prefer up to four facts at a readable
    # size; if they do not all fit, show fewer complete facts instead of
    # clipping a sentence after an arbitrary number of wrapped lines.
    source_facts = bird.facts[:4]
    title_min = max(24, preferred_title_size - 16)
    fact_min = max(13, preferred_fact_size - 6)
    layout = None

    for fact_count in range(len(source_facts), 0, -1):
        best_for_count = None
        for summary_level, max_fact_lines in enumerate((None, 3, 2)):
            for fact_size in range(preferred_fact_size, fact_min - 1, -1):
                candidate_fact_font = font(fact_size)
                candidate_fact_step = text_line_step(draw, candidate_fact_font, 1.25)
                candidate_facts = source_facts[:fact_count]
                if max_fact_lines is not None:
                    candidate_facts = [
                        summarize_fact_for_panel(
                            draw,
                            fact,
                            candidate_fact_font,
                            panel_w - bullet_w,
                            max_lines=max_fact_lines,
                        )
                        for fact in candidate_facts
                    ]
                candidate_fact_blocks = [
                    wrap_pixels(draw, fact, candidate_fact_font, panel_w - bullet_w)
                    for fact in candidate_facts
                ]
                facts_height = sum(len(lines) * candidate_fact_step for lines in candidate_fact_blocks)
                facts_height += max(0, fact_count - 1) * fact_gap

                for title_size in range(preferred_title_size, title_min - 1, -2):
                    candidate_title_font = font(title_size, bold=True)
                    candidate_sci_font = font(max(12, round(title_size * 0.45)), italic=True)
                    candidate_title_lines = wrap_pixels(draw, bird.common_name, candidate_title_font, panel_w)
                    candidate_sci_lines = wrap_pixels(draw, bird.scientific_name, candidate_sci_font, panel_w)
                    candidate_title_step = text_line_step(draw, candidate_title_font, 1.08)
                    candidate_sci_step = text_line_step(draw, candidate_sci_font, 1.25)

                    needed = eyebrow_step + eyebrow_gap
                    needed += len(candidate_title_lines) * candidate_title_step
                    needed += title_sci_gap + len(candidate_sci_lines) * candidate_sci_step
                    needed += facts_top_gap + facts_height
                    needed += footer_separator_space + footer_height

                    if needed <= panel_h:
                        candidate = {
                            "title_size": title_size,
                            "fact_size": fact_size,
                            "title_font": candidate_title_font,
                            "sci_font": candidate_sci_font,
                            "fact_font": candidate_fact_font,
                            "title_lines": candidate_title_lines,
                            "sci_lines": candidate_sci_lines,
                            "fact_blocks": candidate_fact_blocks,
                            "title_step": candidate_title_step,
                            "sci_step": candidate_sci_step,
                            "fact_step": candidate_fact_step,
                        }
                        # Prefer readable type and title, then less
                        # summarization. The outer loop still makes retaining
                        # higher-priority bullets the first consideration.
                        key = (fact_size, title_size, -summary_level)
                        if best_for_count is None or key > best_for_count[0]:
                            best_for_count = (key, candidate)

        if best_for_count is not None:
            layout = best_for_count[1]
            break

    # Bird facts are normally short sentences, so the regular fitting pass
    # should always find a layout. This fallback still guarantees no overflow
    # for unexpectedly long source text by omitting facts rather than drawing
    # a partial sentence.
    if layout is None:
        fallback_title_font = font(title_min, bold=True)
        fallback_sci_font = font(max(12, round(title_min * 0.45)), italic=True)
        layout = {
            "title_size": title_min,
            "fact_size": fact_min,
            "title_font": fallback_title_font,
            "sci_font": fallback_sci_font,
            "fact_font": font(fact_min),
            "title_lines": wrap_pixels(draw, bird.common_name, fallback_title_font, panel_w),
            "sci_lines": wrap_pixels(draw, bird.scientific_name, fallback_sci_font, panel_w),
            "fact_blocks": [],
            "title_step": text_line_step(draw, fallback_title_font, 1.08),
            "sci_step": text_line_step(draw, fallback_sci_font, 1.25),
            "fact_step": text_line_step(draw, font(fact_min), 1.25),
        }

    title_font = layout["title_font"]
    sci_font = layout["sci_font"]
    fact_font = layout["fact_font"]

    y = y1

    draw.text((x1, y), eyebrow, fill=RED, font=small_bold)
    y += eyebrow_step + eyebrow_gap

    for line in layout["title_lines"]:
        draw.text((x1, y), line, fill=BLACK, font=title_font)
        y += layout["title_step"]

    y += title_sci_gap
    for line in layout["sci_lines"]:
        draw.text((x1, y), line, fill=BLUE, font=sci_font)
        y += layout["sci_step"]

    y += facts_top_gap

    for fact_index, lines in enumerate(layout["fact_blocks"]):
        draw.ellipse((x1, y + 5, x1 + 7, y + 12), fill=GREEN)
        for line in lines:
            draw.text((x1 + bullet_w, y), line, fill=BLACK, font=fact_font)
            y += layout["fact_step"]
        if fact_index < len(layout["fact_blocks"]) - 1:
            y += fact_gap

    if not footer_lines:
        return

    footer_y = y2 - footer_height
    draw.line((x1, footer_y - 8, x2, footer_y - 8), fill=LIGHT_GRAY, width=1)
    for line in footer_lines:
        draw.text((x1, footer_y), ellipsize(draw, line, meta_font, panel_w), fill=MID_GRAY, font=meta_font)
        footer_y += footer_step


def text_line_step(draw: ImageDraw.ImageDraw, fnt: ImageFont.ImageFont, multiplier: float) -> int:
    return max(1, round(text_size(draw, "Ag", fnt)[1] * multiplier))


def quantize_for_ee02(image: Image.Image) -> Image.Image:
    """Convert an RGB dashboard to the six colors supported by the EE02 panel."""
    palette_colors = [
        (255, 255, 255),  # white
        (29, 185, 84),  # green
        (229, 57, 53),  # red
        (255, 216, 0),  # yellow
        (0, 76, 255),  # blue
        (0, 0, 0),  # black
    ]
    palette = Image.new("P", (1, 1))
    flat_palette = [channel for color in palette_colors for channel in color]
    palette.putpalette(flat_palette + [0] * (768 - len(flat_palette)))
    return image.quantize(
        palette=palette,
        dither=Image.Dither.FLOYDSTEINBERG,
    ).convert("RGB")


def write_outputs(
    out_dir: Path,
    image: Image.Image,
    metadata: dict[str, Any],
    image_format: str = "png",
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    image_filename = "today.jpg" if image_format == "jpeg" else "today.png"
    image_path = out_dir / image_filename
    json_path = out_dir / "today.json"
    index_path = out_dir / "index.html"
    metadata["dashboard_image"] = image_filename

    tmp_image = image_path.with_suffix(image_path.suffix + ".tmp")
    if image_format == "jpeg":
        image.save(
            tmp_image,
            format="JPEG",
            quality=90,
            subsampling=0,
            optimize=True,
            progressive=False,
        )
    else:
        image.save(tmp_image, format="PNG", optimize=True)
    os.replace(tmp_image, image_path)

    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_json.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_json, json_path)

    index_path.write_text(render_index(metadata), encoding="utf-8")


def render_index(metadata: dict[str, Any]) -> str:
    bird = metadata["bird"]
    title = html.escape(bird["common_name"])
    sci = html.escape(bird["scientific_name"])
    date_text = html.escape(metadata["date"])
    overview = html.escape(bird.get("description") or "No overview is available yet.")
    facts = "\n".join(f"<li>{html.escape(f)}</li>" for f in bird.get("facts", []))
    facts = facts or "<li>No extra facts are available yet.</li>"
    range_text = html.escape(bird.get("range") or "Not available yet.")
    habitat_text = html.escape(bird.get("habitat") or "Not available yet.")
    status_text = html.escape(expanded_status(bird["status"]) if bird.get("status") else "Not available yet.")
    source_name = html.escape(bird.get("source_name") or "Source")
    source = bird.get("source_url")
    source_link = f'<a href="{html.escape(source)}">{source_name}</a>' if source else source_name
    image_credit = html.escape(" | ".join(item for item in [bird.get("image_credit"), bird.get("image_license")] if item))
    image_credit_html = f"<p>{image_credit}</p>" if image_credit else ""
    dashboard_image = html.escape(metadata.get("dashboard_image") or "today.png")

    return textwrap.dedent(
        f"""\
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{title} - Bird Dashboard</title>
          <style>
            body {{
              margin: 0;
              font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              background: #f4f1e8;
              color: #14181b;
            }}
            main {{
              max-width: 1040px;
              margin: 0 auto;
              padding: 24px;
            }}
            img {{
              width: 100%;
              height: auto;
              border: 1px solid #14181b;
              background: white;
            }}
            h1 {{
              margin: 18px 0 4px;
              font-size: clamp(2rem, 4vw, 3.75rem);
              line-height: 1;
            }}
            h2 {{
              margin: 0 0 12px;
              font-size: 1rem;
              text-transform: uppercase;
              color: #6b2e2d;
            }}
            section {{
              margin-top: 28px;
            }}
            .scientific {{
              color: #386892;
              font-size: 1.25rem;
            }}
            .grid {{
              display: grid;
              grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
              gap: 18px;
            }}
            .detail {{
              border-top: 1px solid #cfccbd;
              padding-top: 12px;
            }}
            .label {{
              display: block;
              margin-bottom: 4px;
              color: #62645e;
              font-size: 0.82rem;
              font-weight: 700;
              text-transform: uppercase;
            }}
            li {{
              margin: 0.45rem 0;
            }}
            a {{
              color: #386892;
            }}
          </style>
        </head>
        <body>
          <main>
            <img src="{dashboard_image}" alt="Bird dashboard for {title}">
            <h1>{title}</h1>
            <div class="scientific"><em>{sci}</em></div>

            <section>
              <h2>{date_text}</h2>
              <p>{overview}</p>
            </section>

            <section>
              <h2>Fast Facts</h2>
              <ul>{facts}</ul>
            </section>

            <section class="grid">
              <div class="detail">
                <span class="label">Typically Found</span>
                <p>{range_text}</p>
              </div>
              <div class="detail">
                <span class="label">Habitat</span>
                <p>{habitat_text}</p>
              </div>
              <div class="detail">
                <span class="label">Conservation</span>
                <p>{status_text}</p>
              </div>
            </section>

            <section>
              <h2>Sources</h2>
              <p>{source_link}</p>
              {image_credit_html}
            </section>
          </main>
        </body>
        </html>
        """
    )


def main() -> None:
    args = parse_args()

    if args.width < 240 or args.height < 160:
        raise SystemExit("Width and height are too small for a readable dashboard.")

    birds = load_birds(Path(args.birds))
    date_text = selected_date(args.timezone, args.date)
    bird = choose_bird(birds, date_text, args.seed)
    enrichment_warnings: list[str] = []
    if not args.no_wikipedia:
        bird, wikipedia_warnings = enrich_from_wikipedia(bird)
        enrichment_warnings.extend(wikipedia_warnings)
    if not args.no_birdnet:
        bird, birdnet_warnings = enrich_from_birdnet(bird, args.birdnet_size)
        enrichment_warnings.extend(birdnet_warnings)
    image, metadata = render_dashboard(bird, date_text, args.width, args.height, args.saturation)
    if args.ee02_palette:
        image = quantize_for_ee02(image)
        metadata["palette"] = "seeed-ee02-six-color"
    metadata["warnings"] = enrichment_warnings + metadata.get("warnings", [])
    if args.require_image and not metadata["image"]["loaded"]:
        warnings = "; ".join(metadata["warnings"]) or "unknown image loading failure"
        raise SystemExit(
            "Refusing to publish placeholder image. "
            f"Attempted: {metadata['image']['url'] or metadata['image']['path']}. "
            f"Reason: {warnings}"
        )
    write_outputs(Path(args.out), image, metadata, args.image_format)

    print(f"Rendered {bird.common_name} for {date_text}")
    image_filename = "today.jpg" if args.image_format == "jpeg" else "today.png"
    print(f"Wrote {Path(args.out) / image_filename}")


if __name__ == "__main__":
    main()
