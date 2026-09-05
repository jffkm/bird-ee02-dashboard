#!/usr/bin/env python3
"""Publish one daily Inky Bird Frame plate for the 13.3-inch EE02 panel."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from build_dashboard import DEFAULT_TIMEZONE, USER_AGENT, quantize_for_ee02, selected_date


CATALOG_URL = (
    "https://raw.githubusercontent.com/veteranbv/inky-bird-frame/"
    "main/catalog/index.json"
)
CATALOG_RAW_BASE = (
    "https://raw.githubusercontent.com/veteranbv/inky-bird-frame/main/catalog/"
)
PANEL_SIZE = (1200, 1600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a daily EE02-ready JPEG from the public Inky Bird Frame catalog."
    )
    parser.add_argument("--out", default="public", help="GitHub Pages output directory.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA timezone for selection.")
    parser.add_argument("--date", help="Override the selection date as YYYY-MM-DD.")
    parser.add_argument("--seed", default="", help="Optional extra daily-selection seed.")
    parser.add_argument(
        "--slug",
        help="Publish one fixed species slug instead of rotating the plate daily.",
    )
    parser.add_argument("--catalog-url", default=CATALOG_URL, help=argparse.SUPPRESS)
    parser.add_argument("--catalog-raw-base", default=CATALOG_RAW_BASE, help=argparse.SUPPRESS)
    return parser.parse_args()


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_catalog(url: str) -> dict[str, Any]:
    try:
        catalog = json.loads(fetch_bytes(url))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not load the bird-plate catalog: {exc}") from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("species"), list):
        raise SystemExit("The bird-plate catalog does not contain a species list.")
    return catalog


def choose_plate(
    species: list[dict[str, Any]], date_text: str, seed: str, slug: str | None
) -> dict[str, Any]:
    usable = [
        plate
        for plate in species
        if isinstance(plate, dict)
        and plate.get("slug")
        and plate.get("portrait_path")
    ]
    if not usable:
        raise SystemExit("The bird-plate catalog has no usable portrait images.")

    if slug:
        normalized = slug.strip().lower()
        for plate in usable:
            if str(plate["slug"]).lower() == normalized:
                return plate
        raise SystemExit(f"Bird-plate slug not found: {slug}")

    digest = hashlib.sha256(f"{date_text}:{seed}:birdplate".encode("utf-8")).hexdigest()
    return usable[int(digest[:12], 16) % len(usable)]


def source_image_url(raw_base: str, portrait_path: str) -> str:
    base = raw_base.rstrip("/") + "/"
    path = urllib.parse.quote(portrait_path.lstrip("/"), safe="/")
    return urllib.parse.urljoin(base, path)


def load_plate(url: str) -> Image.Image:
    try:
        with Image.open(io.BytesIO(fetch_bytes(url))) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not load the selected bird plate: {exc}") from exc

    if image.size != PANEL_SIZE:
        raise SystemExit(
            f"Expected a {PANEL_SIZE[0]}x{PANEL_SIZE[1]} portrait plate, "
            f"got {image.width}x{image.height}."
        )
    return image


def write_outputs(
    out_dir: Path,
    image: Image.Image,
    plate: dict[str, Any],
    date_text: str,
    catalog: dict[str, Any],
    image_url: str,
    fixed_slug: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / "birdplate.jpg"
    metadata_path = out_dir / "birdplate.json"

    tmp_image = image_path.with_suffix(".jpg.tmp")
    image.save(
        tmp_image,
        format="JPEG",
        quality=90,
        subsampling=0,
        optimize=False,
        progressive=False,
    )
    os.replace(tmp_image, image_path)

    portrait_path = str(plate["portrait_path"])
    metadata = {
        "date": date_text,
        "selection": "fixed" if fixed_slug else "daily",
        "bird": {
            "common_name": plate.get("common_name"),
            "scientific_name": plate.get("scientific_name"),
            "slug": plate.get("slug"),
            "taxon_id": plate.get("taxon_id"),
        },
        "image": {
            "filename": image_path.name,
            "width": PANEL_SIZE[0],
            "height": PANEL_SIZE[1],
            "format": "JPEG",
            "palette": "seeed-ee02-six-color",
        },
        "source": {
            "catalog": CATALOG_URL,
            "catalog_generated_at": catalog.get("generated_at"),
            "portrait_image": image_url,
            "repository_file": (
                "https://github.com/veteranbv/inky-bird-frame/blob/main/catalog/"
                f"{urllib.parse.quote(portrait_path, safe='/')}"
            ),
            "license": "MIT",
        },
    }
    tmp_metadata = metadata_path.with_suffix(".json.tmp")
    tmp_metadata.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp_metadata, metadata_path)


def main() -> None:
    args = parse_args()
    date_text = selected_date(args.timezone, args.date)
    catalog = fetch_catalog(args.catalog_url)
    plate = choose_plate(catalog["species"], date_text, args.seed, args.slug)
    image_url = source_image_url(args.catalog_raw_base, str(plate["portrait_path"]))
    image = quantize_for_ee02(load_plate(image_url))
    write_outputs(
        Path(args.out), image, plate, date_text, catalog, image_url, bool(args.slug)
    )
    print(f"Rendered bird plate: {plate.get('common_name')} for {date_text}")
    print(f"Wrote {Path(args.out) / 'birdplate.jpg'}")


if __name__ == "__main__":
    main()
