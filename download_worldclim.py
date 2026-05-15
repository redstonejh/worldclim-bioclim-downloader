#!/usr/bin/env python3
"""Download and organize WorldClim v2.1 and representative CMIP6 datasets.

This script was written for building a reproducible GSP archive. It discovers
files from the official WorldClim pages, downloads only the requested dataset
groups, and records a manifest so the archive contents can be audited later.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests import Response, Session
from tqdm import tqdm


# Official WorldClim v2.1 current climate directory. This Apache directory
# listing contains all current ZIP files, including BioClim and elevation.
CURRENT_BASE_URL = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/"

# WorldClim publishes future CMIP6 data through one documentation page per
# resolution. The script reads these pages and filters to one model/scenario,
# instead of downloading every future climate projection.
CMIP6_PAGE_BY_RESOLUTION = {
    "10m": "https://www.worldclim.org/data/cmip6/cmip6_clim10m.html",
    "5m": "https://www.worldclim.org/data/cmip6/cmip6_clim5m.html",
    "2.5m": "https://www.worldclim.org/data/cmip6/cmip6_clim2.5m.html",
    "30s": "https://www.worldclim.org/data/cmip6/cmip6_clim30s.html",
}
RESOLUTIONS = ("10m", "5m", "2.5m", "30s")
DEFAULT_FUTURE_RESOLUTION = "2.5m"
MANIFEST_FIELDS = [
    "url",
    "local_path",
    "file_size",
    "dataset_type",
    "model",
    "scenario",
    "period",
    "download_status",
]


@dataclass
class DownloadItem:
    """One planned file download plus the metadata needed for the manifest."""

    url: str
    local_path: Path
    dataset_type: str
    file_size: int | None = None
    model: str = ""
    scenario: str = ""
    period: str = ""
    download_status: str = "pending"

    def manifest_row(self, archive_root: Path) -> dict[str, str | int]:
        """Return a CSV-safe row with a relative path for portability."""

        row = asdict(self)
        row["local_path"] = str(self.local_path.relative_to(archive_root.parent))
        row["file_size"] = self.file_size if self.file_size is not None else ""
        return row


def parse_args() -> argparse.Namespace:
    """Define the command-line interface for scripted or GUI use."""

    parser = argparse.ArgumentParser(
        description="Download WorldClim v2.1 current and representative CMIP6 future datasets."
    )
    group = parser.add_argument_group("dataset selection")
    group.add_argument("--all", action="store_true", help="Download current base, current BioClim, and future CMIP6 data.")
    group.add_argument("--current", action="store_true", help="Download current non-BioClim WorldClim v2.1 ZIPs.")
    group.add_argument("--bioclim", action="store_true", help="Download current BioClim ZIPs.")
    group.add_argument("--future", action="store_true", help="Download one representative future CMIP6 dataset.")

    parser.add_argument("--output", default="worldclim_archive", type=Path, help="Archive output directory.")
    parser.add_argument(
        "--resolution",
        default="all",
        choices=("all", *RESOLUTIONS),
        help="Resolution for current/BioClim downloads. For future, 'all' uses 2.5m.",
    )
    parser.add_argument("--model", default="MIROC6", help="Future CMIP6 GCM model.")
    parser.add_argument("--scenario", default="ssp245", help="Future CMIP6 scenario, such as ssp245.")
    parser.add_argument("--dry-run", action="store_true", help="Print and manifest planned downloads without downloading.")
    parser.add_argument("--retries", default=4, type=int, help="Retry attempts per file.")
    parser.add_argument("--timeout", default=60, type=int, help="HTTP timeout in seconds.")
    parser.add_argument("--chunk-size", default=1024 * 1024, type=int, help="Download chunk size in bytes.")
    parser.add_argument("--no-progress", action="store_true", help="Disable terminal progress bars.")
    return parser.parse_args()


def configure_logging(output_dir: Path) -> Path:
    """Write logs into the archive folder so each run leaves an audit trail."""

    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"worldclim_download_{timestamp()}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def make_session() -> Session:
    """Create a requests session with a clear user agent for the server logs."""

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "WorldClim-BioClim-GSP-Downloader/1.0 "
                "(https://www.worldclim.org/; reproducible archive script)"
            )
        }
    )
    return session


def get_soup(session: Session, url: str, timeout: int) -> BeautifulSoup:
    """Fetch an HTML listing/documentation page and parse it with BeautifulSoup."""

    logging.info("Reading listing: %s", url)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def discover_current_items(
    session: Session,
    output_dir: Path,
    resolution: str,
    include_base: bool,
    include_bioclim: bool,
    timeout: int,
) -> list[DownloadItem]:
    """Find current WorldClim ZIPs and split them into base and BioClim folders."""

    soup = get_soup(session, CURRENT_BASE_URL, timeout)
    selected_resolutions = set(RESOLUTIONS if resolution == "all" else (resolution,))
    items: list[DownloadItem] = []

    for href in sorted({a.get("href", "") for a in soup.find_all("a")}):
        if not href.endswith(".zip"):
            continue
        filename = Path(urlparse(href).path).name
        parsed = parse_current_filename(filename)
        if not parsed or parsed["resolution"] not in selected_resolutions:
            continue

        is_bioclim = parsed["variable"] == "bio"
        if is_bioclim and not include_bioclim:
            continue
        if not is_bioclim and not include_base:
            continue

        subdir = "bioclim" if is_bioclim else "base"
        items.append(
            DownloadItem(
                url=urljoin(CURRENT_BASE_URL, href),
                local_path=output_dir / "current" / subdir / filename,
                dataset_type="current_bioclim" if is_bioclim else "current_base",
            )
        )

    return items


def parse_current_filename(filename: str) -> dict[str, str] | None:
    """Parse current filenames such as wc2.1_2.5m_prec.zip."""

    match = re.match(r"^wc2\.1_(?P<resolution>30s|2\.5m|5m|10m)_(?P<variable>[a-z]+)\.zip$", filename)
    return match.groupdict() if match else None


def discover_future_items(
    session: Session,
    output_dir: Path,
    resolution: str,
    model: str,
    scenario: str,
    timeout: int,
) -> list[DownloadItem]:
    """Find one representative future CMIP6 set for a model/scenario/resolution."""

    future_resolution = DEFAULT_FUTURE_RESOLUTION if resolution == "all" else resolution
    page_url = CMIP6_PAGE_BY_RESOLUTION[future_resolution]
    soup = get_soup(session, page_url, timeout)
    model_norm = model.lower()
    scenario_norm = scenario.lower()
    items: list[DownloadItem] = []

    for href in sorted({a.get("href", "") for a in soup.find_all("a")}):
        if not href.endswith((".tif", ".zip")):
            continue
        filename = Path(urlparse(href).path).name
        parsed = parse_future_filename(filename)
        if not parsed:
            continue
        if parsed["resolution"] != future_resolution:
            continue
        if parsed["model"].lower() != model_norm or parsed["scenario"].lower() != scenario_norm:
            continue

        items.append(
            DownloadItem(
                url=urljoin(page_url, href),
                local_path=(
                    output_dir
                    / "future"
                    / "cmip6"
                    / future_resolution
                    / parsed["model"]
                    / parsed["scenario"]
                    / filename
                ),
                dataset_type="future_cmip6",
                model=parsed["model"],
                scenario=parsed["scenario"],
                period=parsed["period"],
            )
        )

    if not items:
        raise RuntimeError(
            f"No future files found for resolution={future_resolution}, model={model}, scenario={scenario}. "
            f"Check {page_url} for available combinations."
        )
    return items


def parse_future_filename(filename: str) -> dict[str, str] | None:
    """Parse CMIP6 names, including model, scenario, variable, and future period."""

    match = re.match(
        r"^wc2\.1_(?P<resolution>30s|2\.5m|5m|10m)_"
        r"(?P<variable>tmin|tmax|prec|bioc)_"
        r"(?P<model>.+?)_(?P<scenario>ssp\d{3})_"
        r"(?P<period>\d{4}-\d{4})\.(?:tif|zip)$",
        filename,
    )
    return match.groupdict() if match else None


def enrich_file_sizes(session: Session, items: Iterable[DownloadItem], timeout: int) -> None:
    """Use HEAD requests to record expected file sizes before downloading."""

    for item in items:
        try:
            item.file_size = remote_file_size(session, item.url, timeout)
        except requests.RequestException as exc:
            logging.warning("Could not read remote size for %s: %s", item.url, exc)


def remote_file_size(session: Session, url: str, timeout: int) -> int | None:
    """Read Content-Length from the remote server when it is available."""

    response = session.head(url, allow_redirects=True, timeout=timeout)
    response.raise_for_status()
    length = response.headers.get("Content-Length")
    return int(length) if length and length.isdigit() else None


def download_item(
    session: Session,
    item: DownloadItem,
    retries: int,
    timeout: int,
    chunk_size: int,
    show_progress: bool = True,
) -> None:
    """Download one file safely, resuming partial files when possible."""

    item.local_path.parent.mkdir(parents=True, exist_ok=True)

    remote_size = item.file_size or remote_file_size(session, item.url, timeout)
    item.file_size = remote_size
    existing_size = item.local_path.stat().st_size if item.local_path.exists() else 0

    if remote_size is not None and existing_size == remote_size:
        # Complete files are left untouched, which makes reruns safe.
        item.download_status = "skipped_existing"
        logging.info("Skipping existing complete file: %s", item.local_path)
        return

    if remote_size is not None and existing_size > remote_size:
        raise RuntimeError(f"Local file is larger than remote file: {item.local_path}")

    for attempt in range(1, retries + 1):
        try:
            resume_from = item.local_path.stat().st_size if item.local_path.exists() else 0
            # HTTP Range allows interrupted downloads to continue from the last
            # saved byte, which is important for multi-GB WorldClim files.
            headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
            mode = "ab" if resume_from else "wb"

            with session.get(item.url, headers=headers, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                if resume_from and response.status_code != 206:
                    # If the server ignores the Range request, restart cleanly
                    # rather than appending duplicate bytes to the partial file.
                    logging.warning("Server did not resume %s; restarting file.", item.url)
                    resume_from = 0
                    mode = "wb"

                total = remote_size or _content_total(response, resume_from)
                with tqdm(
                    total=total,
                    initial=resume_from,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=item.local_path.name,
                    disable=not show_progress,
                ) as progress:
                    with item.local_path.open(mode) as file_obj:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            progress.update(len(chunk))

            final_size = item.local_path.stat().st_size
            if remote_size is not None and final_size != remote_size:
                # Size validation catches truncated downloads before they are
                # marked as complete in the manifest.
                raise RuntimeError(f"Incomplete download for {item.local_path}: {final_size} of {remote_size} bytes")

            item.download_status = "downloaded" if existing_size == 0 else "resumed"
            logging.info("%s: %s", item.download_status, item.local_path)
            return

        except Exception as exc:
            item.download_status = "failed"
            if attempt >= retries:
                logging.exception("Failed after %s attempts: %s", retries, item.url)
                raise
            # Exponential backoff is gentler on both the local network and the
            # data host when there are temporary connection problems.
            delay = min(2 ** attempt, 60)
            logging.warning("Attempt %s/%s failed for %s: %s. Retrying in %ss.", attempt, retries, item.url, exc, delay)
            time.sleep(delay)


def _content_total(response: Response, resume_from: int) -> int | None:
    length = response.headers.get("Content-Length")
    if length and length.isdigit():
        return int(length) + resume_from
    return None


def write_manifest(output_dir: Path, items: Iterable[DownloadItem]) -> Path:
    """Write a timestamped CSV manifest for reproducibility and review."""

    manifests_dir = output_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"worldclim_manifest_{timestamp()}.csv"
    archive_root = output_dir.resolve()

    with manifest_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for item in items:
            writer.writerow(item.manifest_row(archive_root))
    return manifest_path


def print_plan(items: list[DownloadItem], output_dir: Path) -> None:
    """Print a human-readable summary before the download starts."""

    print(f"Planned files: {len(items)}")
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item.dataset_type] = by_type.get(item.dataset_type, 0) + 1
    for dataset_type, count in sorted(by_type.items()):
        print(f"  {dataset_type}: {count}")

    print()
    for item in items:
        size = format_bytes(item.file_size) if item.file_size is not None else "unknown size"
        rel_path = item.local_path.resolve().relative_to(output_dir.resolve().parent)
        print(f"{item.dataset_type:16} {size:>10}  {rel_path}")
        print(f"  {item.url}")


def format_bytes(size: int | None) -> str:
    if size is None:
        return "unknown"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def selected_modes(args: argparse.Namespace) -> tuple[bool, bool, bool]:
    """Convert CLI flags into booleans for the three supported dataset groups."""

    if not any((args.all, args.current, args.bioclim, args.future)):
        raise SystemExit("Choose at least one of --all, --current, --bioclim, or --future.")
    return (
        args.all or args.current,
        args.all or args.bioclim,
        args.all or args.future,
    )


def main() -> int:
    """Plan downloads, optionally dry-run, then download and write the manifest."""

    args = parse_args()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = configure_logging(output_dir)
    session = make_session()

    try:
        include_current, include_bioclim, include_future = selected_modes(args)
        items: list[DownloadItem] = []

        if include_current or include_bioclim:
            items.extend(
                discover_current_items(
                    session=session,
                    output_dir=output_dir,
                    resolution=args.resolution,
                    include_base=include_current,
                    include_bioclim=include_bioclim,
                    timeout=args.timeout,
                )
            )
        if include_future:
            items.extend(
                discover_future_items(
                    session=session,
                    output_dir=output_dir,
                    resolution=args.resolution,
                    model=args.model,
                    scenario=args.scenario,
                    timeout=args.timeout,
                )
            )

        if not items:
            raise RuntimeError("No files matched the requested selection.")

        logging.info("Discovered %s files.", len(items))
        enrich_file_sizes(session, items, args.timeout)
        print_plan(items, output_dir)

        if args.dry_run:
            for item in items:
                item.download_status = "dry_run"
            manifest_path = write_manifest(output_dir, items)
            logging.info("Dry run complete. Manifest: %s", manifest_path)
            return 0

        failures = 0
        for item in items:
            try:
                download_item(
                    session,
                    item,
                    args.retries,
                    args.timeout,
                    args.chunk_size,
                    show_progress=not args.no_progress,
                )
            except Exception as exc:
                failures += 1
                item.download_status = f"failed: {exc}"

        manifest_path = write_manifest(output_dir, items)
        logging.info("Manifest written: %s", manifest_path)
        logging.info("Log written: %s", log_path)

        if failures:
            logging.error("Completed with %s failed download(s). Re-run the same command to resume.", failures)
            return 1
        logging.info("All downloads completed successfully.")
        return 0

    except Exception as exc:
        logging.exception("Download planning failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
