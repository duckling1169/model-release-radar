#!/usr/bin/env python3
"""Normalize source-faithful arXiv Atom pages for the production Silver layer."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime


ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}
ALLOWED_ARXIV_CATEGORIES = {"cs.AI", "cs.CL", "cs.LG"}
FIRST_ANNOUNCEMENTS = {"new", "cross"}
TRANSFORM_VERSION = "m5-v1"


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # bq --format=json renders TIMESTAMP values as UTC without an offset.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def arxiv_identity(raw_id: str) -> tuple[str, str, str]:
    # Feed IDs look like "oai:arXiv.org:2609.38181v1".
    article = raw_id.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    match = re.fullmatch(r"(.+?)(v\d+)", article)
    source_id, version = match.groups() if match else (article, "v1")
    return source_id, version, f"https://arxiv.org/abs/{source_id}"


def text_content(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def abstract(summary: str) -> str:
    # The feed prefixes each summary with "arXiv:<id> Announce Type: <type> Abstract:".
    return summary.split("Abstract:", 1)[-1].strip()


def arxiv_rows(bronze_pages: list[dict[str, object]], processed_at: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for page in bronze_pages:
        window_start = parse_timestamp(str(page["window_start"]))
        window_end = parse_timestamp(str(page["window_end"]))
        root = ET.fromstring(str(page["raw_body"]))
        for index, entry in enumerate(root.findall("atom:entry", ATOM_NS)):
            raw_id = entry.findtext("atom:id", namespaces=ATOM_NS)
            published = entry.findtext("atom:published", namespaces=ATOM_NS)
            announce_type = entry.findtext("arxiv:announce_type", namespaces=ATOM_NS)
            if not raw_id or not published or announce_type not in FIRST_ANNOUNCEMENTS:
                continue
            published_at = parse_timestamp(published)
            categories = [category.attrib["term"] for category in entry.findall("atom:category", ATOM_NS) if "term" in category.attrib]
            if not window_start <= published_at < window_end or not ALLOWED_ARXIV_CATEGORIES.intersection(categories):
                continue
            source_id, version, canonical_url = arxiv_identity(raw_id)
            creators = text_content(entry.find("dc:creator", ATOM_NS))
            rows.append(
                {
                    "source_id": source_id,
                    "arxiv_version": version,
                    "source_published_at": published_at.isoformat(),
                    "source_updated_at": published_at.isoformat(),
                    "observed_at": page["fetched_at"],
                    "title": text_content(entry.find("atom:title", ATOM_NS)),
                    "summary": abstract(text_content(entry.find("atom:summary", ATOM_NS))),
                    "authors_json": json.dumps([name.strip() for name in creators.split(",") if name.strip()]),
                    "categories_json": json.dumps(categories),
                    "canonical_url": canonical_url,
                    "source_metadata": json.dumps({"entry_xml": ET.tostring(entry, encoding="unicode")}),
                    "bronze_run_id": page["run_id"],
                    "bronze_page_number": page["page_number"],
                    "source_record_index": index,
                    "processed_at": processed_at,
                    "transform_version": TRANSFORM_VERSION,
                }
            )
    return rows
