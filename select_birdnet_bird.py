#!/usr/bin/env python3
"""Select one daily bird from BirdNET's live, image-backed catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "America/Los_Angeles"
BIRDNET_API_BASE = "https://birdnet.cornell.edu/taxonomy/api"
BIRDNET_WEB_BASE = "https://birdnet.cornell.edu/taxonomy/species"
USER_AGENT = "bird-inky-dashboard/1.0 (+https://github.com/jffkm/bird-ee02-dashboard)"
MAX_PER_PAGE = 500

# The dashboard resizes and dithers its source photo, so NoDerivatives images
# are deliberately excluded. Attribution and the original license are retained
# in today.json and on the companion GitHub Pages page.
DERIVATIVE_FRIENDLY_LICENSES = {
    "cc0",
    "cc-by",
    "cc-by-sa",
    "cc-by-nc",
    "cc-by-nc-sa",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Choose a non-repeating daily bird from BirdNET's live catalog."
    )
    parser.add_argument("--out", default="work/selected-bird.json")
    parser.add_argument("--date", help="Override date as YYYY-MM-DD.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--seed", default="")
    parser.add_argument("--min-observations", type=int, default=10_000)
    parser.add_argument("--api-base", default=BIRDNET_API_BASE, help=argparse.SUPPRESS)
    return parser.parse_args()


def selected_date(timezone_name: str, override: str | None) -> datetime:
    if override:
        return datetime.strptime(override, "%Y-%m-%d")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone)


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": USER_AGENT,
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("BirdNET returned a non-object JSON response")
            return value
        except (OSError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Could not fetch BirdNET catalog: {last_error}")


def page_url(api_base: str, page: int, min_observations: int) -> str:
    query = urllib.parse.urlencode(
        {
            "group": "Aves",
            "has_image": "true",
            "has_description": "true",
            "min_observations": min_observations,
            "fields": "scientific_name,common_name,observations_count,image",
            "page": page,
            "per_page": MAX_PER_PAGE,
        }
    )
    return f"{api_base.rstrip('/')}/species?{query}"


def fetch_catalog(api_base: str, min_observations: int) -> tuple[str, list[dict[str, Any]]]:
    first = fetch_json(page_url(api_base, 1, min_observations))
    taxonomy_version = str(first.get("taxonomy_version") or "").strip()
    total = int(first.get("total") or 0)
    first_results = first.get("results")
    if not taxonomy_version or total < 1 or not isinstance(first_results, list):
        raise RuntimeError("BirdNET catalog response is missing version, total, or results")

    results = [item for item in first_results if isinstance(item, dict)]
    page_count = (total + MAX_PER_PAGE - 1) // MAX_PER_PAGE
    for page in range(2, page_count + 1):
        payload = fetch_json(page_url(api_base, page, min_observations))
        if payload.get("taxonomy_version") != taxonomy_version:
            raise RuntimeError("BirdNET taxonomy version changed during pagination")
        page_results = payload.get("results")
        if not isinstance(page_results, list):
            raise RuntimeError(f"BirdNET catalog page {page} has no results array")
        results.extend(item for item in page_results if isinstance(item, dict))
    return taxonomy_version, results


def normalized_license(value: Any) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def eligible_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for record in records:
        scientific_name = str(record.get("scientific_name") or "").strip()
        common_name = str(record.get("common_name") or "").strip()
        image = record.get("image")
        if not scientific_name or not common_name or not isinstance(image, dict):
            continue
        image_url = str(image.get("src") or "").strip()
        author = str(image.get("author") or "").strip()
        license_name = normalized_license(image.get("license"))
        if (
            not image_url.startswith("https://")
            or not author
            or license_name not in DERIVATIVE_FRIENDLY_LICENSES
        ):
            continue
        eligible.append(record)
    return eligible


def choose_candidate(
    candidates: list[dict[str, Any]], date: datetime, seed: str, taxonomy_version: str
) -> tuple[dict[str, Any], int]:
    if not candidates:
        raise RuntimeError("BirdNET returned no suitably licensed bird images")

    ordered = sorted(
        candidates,
        key=lambda item: (
            str(item["scientific_name"]).casefold(),
            str(item["common_name"]).casefold(),
        ),
    )
    month = date.strftime("%Y-%m")
    material = f"{month}:{seed}:{taxonomy_version}:birdnet-monthly-order".encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
    rng.shuffle(ordered)
    index = (date.day - 1) % len(ordered)
    return ordered[index], index


def selected_bird_record(
    selected: dict[str, Any], date: datetime, taxonomy_version: str, pool_size: int, index: int
) -> dict[str, Any]:
    scientific_name = str(selected["scientific_name"]).strip()
    image = selected["image"]
    species_path = urllib.parse.quote(scientific_name, safe="")
    return {
        "common_name": str(selected["common_name"]).strip(),
        "scientific_name": scientific_name,
        "image_url": str(image["src"]).strip(),
        "image_credit": str(image["author"]).strip(),
        "image_license": normalized_license(image.get("license")),
        "source_url": f"{BIRDNET_WEB_BASE}/{species_path}",
        "source_name": "BirdNET+ Taxonomy",
        "birdnet_selection": {
            "date": date.strftime("%Y-%m-%d"),
            "taxonomy_version": taxonomy_version,
            "qualified_pool_size": pool_size,
            "monthly_index": index,
            "observations_count": selected.get("observations_count"),
            "image_source": image.get("source"),
        },
    }


def main() -> None:
    args = parse_args()
    date = selected_date(args.timezone, args.date)
    taxonomy_version, records = fetch_catalog(args.api_base, args.min_observations)
    candidates = eligible_candidates(records)
    selected, index = choose_candidate(candidates, date, args.seed, taxonomy_version)
    bird = selected_bird_record(selected, date, taxonomy_version, len(candidates), index)

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(output.suffix + ".tmp")
    tmp_output.write_text(
        json.dumps([bird], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp_output.replace(output)
    print(
        f"Selected {bird['common_name']} for {date:%Y-%m-%d} from "
        f"{len(candidates)} qualified BirdNET birds ({taxonomy_version})"
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
