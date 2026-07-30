#!/usr/bin/env python3
"""Collect source-faithful Hugging Face and arXiv response pages for production.

The collector deliberately stops at the raw-capture boundary. It does not
normalize records, load BigQuery, or make any product-quality decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, urlopen


HUGGINGFACE_URL = "https://huggingface.co/api/models"
ARXIV_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "model-release-radar/0.1 (+https://github.com/duckling1169/model-release-radar)"
DEFAULT_OUTPUT_DIR = Path("data/raw")
SYSTEM_CA_BUNDLE = Path("/etc/ssl/cert.pem")
DEFAULT_MAX_PAGES = 1_000
RECENT_WINDOW_LIMIT = timedelta(hours=48)
MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 30
ARXIV_REQUEST_DELAY_SECONDS = 3
HUGGINGFACE_PAGE_SIZE = 100
ARXIV_PAGE_SIZE = 100

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class CollectionError(RuntimeError):
    """A source could not be collected completely."""


class SafetyLimitError(CollectionError):
    """The explicit page safety limit was reached before window coverage."""


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    headers: Message
    body: bytes


@dataclass(frozen=True)
class RunWindow:
    start: datetime
    end: datetime


def parse_utc(value: str) -> datetime:
    """Parse a strict RFC 3339 timestamp that is explicitly in UTC."""
    if not value.endswith("Z"):
        raise argparse.ArgumentTypeError("timestamps must use a trailing Z (UTC)")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid RFC 3339 timestamp: {value}") from exc
    if parsed.tzinfo != UTC:
        raise argparse.ArgumentTypeError("timestamps must use UTC")
    return parsed


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_source_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"source timestamp has no timezone: {value}")
    return parsed.astimezone(UTC)


def in_window(value: datetime, window: RunWindow) -> bool:
    return window.start <= value < window.end


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def ensure_recent_window(window: RunWindow, now: datetime) -> None:
    if window.end > now + timedelta(minutes=5):
        raise ValueError("end must not be more than five minutes in the future")
    if now - window.end > RECENT_WINDOW_LIMIT:
        raise ValueError(
            "M1 supports windows ending within 48 hours of execution; "
            "historical backfill is intentionally deferred"
        )


def request_url(url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> HttpResponse:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    context = ssl.create_default_context()
    # Some macOS Python.org installations have no configured OpenSSL CA file,
    # while the OS-managed bundle remains available at this conventional path.
    if ssl.get_default_verify_paths().cafile is None and SYSTEM_CA_BUNDLE.is_file():
        context.load_verify_locations(cafile=str(SYSTEM_CA_BUNDLE))
    with urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 - fixed public source URLs
        return HttpResponse(
            url=response.geturl(),
            status=response.status,
            headers=response.headers,
            body=response.read(),
        )


def fetch_with_retry(
    url: str,
    fetcher: Callable[[str], HttpResponse],
    sleep_fn: Callable[[float], None],
) -> HttpResponse:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = fetcher(url)
            if 200 <= response.status < 300:
                return response
            if response.status not in {429, 500, 502, 503, 504}:
                raise CollectionError(f"HTTP {response.status} for {url}")
            last_error = CollectionError(f"transient HTTP {response.status} for {url}")
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                raise CollectionError(f"HTTP {exc.code} for {url}") from exc
            last_error = exc
        except (TimeoutError, URLError) as exc:
            last_error = exc

        if attempt < MAX_RETRIES - 1:
            sleep_fn(2**attempt)

    raise CollectionError(f"request failed after {MAX_RETRIES} attempts: {url}: {last_error}")


def next_link(headers: Message) -> str | None:
    link_header = headers.get("Link")
    if not link_header:
        return None
    match = re.search(r"<([^>]+)>;\s*rel=\"?next\"?", link_header)
    return match.group(1) if match else None


def huggingface_page_stats(body: bytes, window: RunWindow) -> tuple[int, int, datetime | None]:
    rows = json.loads(body)
    if not isinstance(rows, list):
        raise CollectionError("Hugging Face response was not a JSON list")
    timestamps: list[datetime] = []
    window_count = 0
    for row in rows:
        if not isinstance(row, dict) or not row.get("createdAt"):
            raise CollectionError("Hugging Face response had a record without createdAt")
        created_at = parse_source_timestamp(str(row["createdAt"]))
        timestamps.append(created_at)
        if in_window(created_at, window):
            window_count += 1
    return len(rows), window_count, min(timestamps) if timestamps else None


def arxiv_page_stats(body: bytes, window: RunWindow) -> tuple[int, int, datetime | None]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise CollectionError("arXiv response was not valid Atom XML") from exc
    entries = root.findall("atom:entry", ATOM_NS)
    timestamps: list[datetime] = []
    window_count = 0
    for entry in entries:
        published = entry.findtext("atom:published", namespaces=ATOM_NS)
        if not published:
            raise CollectionError("arXiv entry had no published timestamp")
        published_at = parse_source_timestamp(published)
        timestamps.append(published_at)
        if in_window(published_at, window):
            window_count += 1
    return len(entries), window_count, min(timestamps) if timestamps else None


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def page_manifest(
    page_number: int,
    response: HttpResponse,
    filename: str,
    response_count: int,
    window_count: int,
    fetched_at: datetime,
) -> dict[str, object]:
    return {
        "page_number": page_number,
        "filename": filename,
        "request_url": response.url,
        "request_parameters": dict(parse_qsl(urlsplit(response.url).query, keep_blank_values=True)),
        "http_status": response.status,
        "content_type": response.headers.get("Content-Type", ""),
        "fetched_at": isoformat_z(fetched_at),
        "response_bytes": len(response.body),
        "sha256": sha256(response.body),
        "response_record_count": response_count,
        "window_record_count": window_count,
    }


def collect_huggingface(
    source_dir: Path,
    window: RunWindow,
    max_pages: int,
    fetcher: Callable[[str], HttpResponse],
    sleep_fn: Callable[[float], None],
    clock: Callable[[], datetime],
) -> dict[str, object]:
    pages_dir = source_dir / "pages"
    pages_dir.mkdir(parents=True)
    url = f"{HUGGINGFACE_URL}?{urlencode({'sort': 'createdAt', 'direction': '-1', 'limit': HUGGINGFACE_PAGE_SIZE, 'full': 'true'})}"
    pages: list[dict[str, object]] = []
    response_records = 0
    window_records = 0

    while url:
        if len(pages) >= max_pages:
            raise SafetyLimitError(f"Hugging Face reached --max-pages={max_pages} before covering the window")
        response = fetch_with_retry(url, fetcher, sleep_fn)
        filename = f"{len(pages) + 1:04d}.json"
        (pages_dir / filename).write_bytes(response.body)
        count, matched_count, oldest = huggingface_page_stats(response.body, window)
        pages.append(page_manifest(len(pages) + 1, response, f"pages/{filename}", count, matched_count, clock()))
        response_records += count
        window_records += matched_count
        if not oldest or oldest < window.start:
            break
        url = next_link(response.headers)
        if not url:
            break

    manifest = {
        "source": "huggingface",
        "status": "succeeded",
        "response_record_count": response_records,
        "window_record_count": window_records,
        "pages": pages,
    }
    write_json(source_dir / "manifest.json", manifest)
    return manifest


def arxiv_query_url(start: int) -> str:
    params = {
        "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
        "start": start,
        "max_results": ARXIV_PAGE_SIZE,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_URL}?{urlencode(params)}"


def collect_arxiv(
    source_dir: Path,
    window: RunWindow,
    max_pages: int,
    fetcher: Callable[[str], HttpResponse],
    sleep_fn: Callable[[float], None],
    clock: Callable[[], datetime],
) -> dict[str, object]:
    pages_dir = source_dir / "pages"
    pages_dir.mkdir(parents=True)
    pages: list[dict[str, object]] = []
    response_records = 0
    window_records = 0
    start = 0

    while True:
        if len(pages) >= max_pages:
            raise SafetyLimitError(f"arXiv reached --max-pages={max_pages} before covering the window")
        if pages:
            sleep_fn(ARXIV_REQUEST_DELAY_SECONDS)
        response = fetch_with_retry(arxiv_query_url(start), fetcher, sleep_fn)
        filename = f"{len(pages) + 1:04d}.xml"
        (pages_dir / filename).write_bytes(response.body)
        count, matched_count, oldest = arxiv_page_stats(response.body, window)
        pages.append(page_manifest(len(pages) + 1, response, f"pages/{filename}", count, matched_count, clock()))
        response_records += count
        window_records += matched_count
        if count == 0 or not oldest or oldest < window.start:
            break
        start += ARXIV_PAGE_SIZE

    manifest = {
        "source": "arxiv",
        "status": "succeeded",
        "response_record_count": response_records,
        "window_record_count": window_records,
        "pages": pages,
    }
    write_json(source_dir / "manifest.json", manifest)
    return manifest


def failed_manifest(source: str, error: Exception) -> dict[str, object]:
    return {"source": source, "status": "failed", "error": str(error), "pages": []}


def collect_run(
    output_dir: Path,
    window: RunWindow,
    selected_sources: Iterable[str],
    max_pages: int,
    fetcher: Callable[[str], HttpResponse] = request_url,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
    run_id: str | None = None,
) -> tuple[Path, dict[str, object]]:
    if max_pages < 1:
        raise ValueError("--max-pages must be at least 1")
    ensure_recent_window(window, clock())
    run_id = run_id or f"{clock().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    collectors = {"huggingface": collect_huggingface, "arxiv": collect_arxiv}
    started_at = clock()
    source_results: dict[str, dict[str, object]] = {}
    for source in selected_sources:
        try:
            source_dir = run_dir / source
            source_dir.mkdir()
            source_results[source] = collectors[source](source_dir, window, max_pages, fetcher, sleep_fn, clock)
        except Exception as exc:  # retain all other source results and record this source failure
            source_dir = run_dir / source
            source_dir.mkdir(exist_ok=True)
            source_results[source] = failed_manifest(source, exc)
            write_json(source_dir / "manifest.json", source_results[source])

    complete = all(result["status"] == "succeeded" for result in source_results.values())
    manifest = {
        "run_id": run_id,
        "status": "succeeded" if complete else "incomplete",
        "window": {"start": isoformat_z(window.start), "end": isoformat_z(window.end)},
        "started_at": isoformat_z(started_at),
        "finished_at": isoformat_z(clock()),
        "sources": source_results,
    }
    write_json(run_dir / "run_manifest.json", manifest)
    return run_dir, manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=parse_utc, help="inclusive RFC 3339 UTC timestamp")
    parser.add_argument("--end", required=True, type=parse_utc, help="exclusive RFC 3339 UTC timestamp")
    parser.add_argument("--source", choices=("all", "huggingface", "arxiv"), default="all")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.start >= args.end:
        print("error: --start must be earlier than --end", file=sys.stderr)
        return 2
    sources = ("huggingface", "arxiv") if args.source == "all" else (args.source,)
    try:
        run_dir, manifest = collect_run(args.output_dir, RunWindow(args.start, args.end), sources, args.max_pages)
    except (CollectionError, SafetyLimitError, ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{manifest['status']}: {run_dir}")
    return 0 if manifest["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
