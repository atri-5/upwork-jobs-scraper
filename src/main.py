thonimport argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from extractors.upwork_parser import UpworkJobScraper
from outputs.exporter import DataExporter

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_settings(config_path: Path) -> dict:
    try:
        return load_json(config_path)
    except Exception as exc:  # noqa: BLE001
        logging.error("Failed to load settings from %s: %s", config_path, exc)
        raise

def resolve_paths() -> dict:
    """
    Resolve all important project paths based on the main.py location.
    """
    script_dir = Path(__file__).resolve().parent
    root_dir = script_dir.parent

    return {
        "root": root_dir,
        "config": script_dir / "config" / "settings.example.json",
        "data_dir": root_dir / "data",
        "sample_output": root_dir / "data" / "sample_output.json",
    }

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upwork Jobs Scraper - scrape and export job listings from Upwork."
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to settings JSON file (defaults to src/config/settings.example.json).",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "csv", "excel", "xml"],
        help="Override export format (json, csv, excel, xml).",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help="Override maximum number of items to scrape.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Override maximum number of pages to scrape.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging.",
    )
    return parser.parse_args()

def build_scraper(settings: dict) -> UpworkJobScraper:
    upwork_cfg = settings.get("upwork", {})

    search_url_template = upwork_cfg.get("searchUrlTemplate")
    if not search_url_template:
        raise ValueError("settings.upwork.searchUrlTemplate must be provided in config.")

    max_items = int(upwork_cfg.get("maxItems", 100))
    delay = float(upwork_cfg.get("delaySeconds", 2.0))
    proxy = upwork_cfg.get("proxy")
    user_agent = upwork_cfg.get(
        "userAgent",
        "Mozilla/5.0 (compatible; UpworkJobsScraper/1.0; +https://bitbash.dev)",
    )

    scraper = UpworkJobScraper(
        search_url_template=search_url_template,
        max_items=max_items,
        delay_seconds=delay,
        proxy=proxy,
        user_agent=user_agent,
    )
    return scraper

def main() -> int:
    args = parse_args()
    setup_logging(verbose=args.verbose)

    paths = resolve_paths()

    config_path = Path(args.config) if args.config else paths["config"]
    logging.info("Using config file: %s", config_path)

    try:
        settings = load_settings(config_path)
    except Exception:
        return 1

    # Override settings from CLI if provided
    upwork_cfg = settings.setdefault("upwork", {})
    export_cfg = settings.setdefault("export", {})

    if args.max_items is not None:
        upwork_cfg["maxItems"] = args.max_items
    if args.max_pages is not None:
        upwork_cfg["maxPages"] = args.max_pages
    if args.format is not None:
        export_cfg["format"] = args.format

    scraper = build_scraper(settings)

    max_pages = int(upwork_cfg.get("maxPages", 1))
    logging.info(
        "Starting scrape: maxItems=%s, maxPages=%s",
        upwork_cfg.get("maxItems", 100),
        max_pages,
    )

    try:
        jobs = scraper.scrape(max_pages=max_pages)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Unexpected error during scraping: %s", exc)
        jobs = []

    if not jobs:
        logging.warning(
            "Scraping yielded no results. Attempting to fall back to sample_output.json"
        )
        sample_output_path = paths["sample_output"]
        if sample_output_path.exists():
            try:
                jobs = load_json(sample_output_path)
                logging.info(
                    "Loaded %d records from sample_output.json", len(jobs)  # type: ignore[arg-type]
                )
            except Exception as exc:  # noqa: BLE001
                logging.error("Failed to load sample_output.json: %s", exc)
                return 1
        else:
            logging.error(
                "No jobs scraped and sample_output.json does not exist. Nothing to export."
            )
            return 1

    export_format = export_cfg.get("format", "json").lower()
    output_dir_name = export_cfg.get("outputDir", "data")
    file_prefix = export_cfg.get("filePrefix", "upwork_jobs")

    output_dir = paths["root"] / output_dir_name
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_prefix_with_time = f"{file_prefix}_{timestamp}"

    exporter = DataExporter(output_dir=output_dir)
    try:
        output_path = exporter.export(
            data=jobs,
            fmt=export_format,
            file_prefix=file_prefix_with_time,
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Failed to export data: %s", exc)
        return 1

    logging.info("Export completed: %s", output_path)
    return 0

if __name__ == "__main__":
    sys.exit(main())