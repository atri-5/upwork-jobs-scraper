thonimport logging
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .utils_text import (
    clean_text,
    parse_budget,
    parse_client_reviews,
    parse_client_spent,
    parse_created_at,
    parse_job_type,
    parse_skills_list,
)

logger = logging.getLogger(__name__)

class UpworkJobScraper:
    """
    High–level scraper that fetches Upwork search result pages and extracts jobs.

    The scraper expects a search URL template with an optional `{page}` placeholder,
    for example:

        https://www.upwork.com/nx/search/jobs/?q=python%20developer&sort=recency&page={page}
    """

    def __init__(
        self,
        search_url_template: str,
        max_items: int = 100,
        delay_seconds: float = 2.0,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        if not search_url_template:
            raise ValueError("search_url_template must not be empty.")

        self.search_url_template = search_url_template
        self.max_items = max_items
        self.delay_seconds = delay_seconds
        self.proxy = proxy
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        if self.proxy:
            self.session.proxies.update(
                {
                    "http": self.proxy,
                    "https": self.proxy,
                }
            )

        logger.debug(
            "Initialized UpworkJobScraper: max_items=%s, delay=%.2fs",
            self.max_items,
            self.delay_seconds,
        )

    def _build_url(self, page: int) -> str:
        if "{page}" in self.search_url_template:
            return self.search_url_template.format(page=page)

        # Fallback: add or update a "page" query parameter manually.
        if "?" in self.search_url_template:
            if "page=" in self.search_url_template:
                # naive replace; good enough for this context
                base, _, _ = self.search_url_template.partition("page=")
                return f"{base}page={page}"
            return f"{self.search_url_template}&page={page}"
        return f"{self.search_url_template}?page={page}"

    def fetch_search_page(self, page: int) -> str:
        url = self._build_url(page)
        logger.info("Fetching Upwork search page %s: %s", page, url)
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            logger.debug("Fetched page %s with status %s", page, resp.status_code)
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Request for page %s failed: %s", page, exc)
            return ""

    def parse_jobs_from_html(self, html: str) -> List[Dict[str, Any]]:
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")

        # Try multiple selectors: Upwork changes its layout often.
        job_cards = soup.select('section.air-card') or soup.select(
            'div[data-test="job-tile"]'
        )
        if not job_cards:
            # Fallback to more generic container.
            job_cards = soup.select("section") or soup.select("article")

        jobs: List[Dict[str, Any]] = []
        for card in job_cards:
            try:
                job = self._parse_single_job(card)
                if job:
                    jobs.append(job)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to parse job card: %s", exc, exc_info=True)
        logger.info("Parsed %d jobs from page HTML", len(jobs))
        return jobs

    def _parse_single_job(self, card) -> Optional[Dict[str, Any]]:  # type: ignore[override]
        # Job ID – try data attributes or link URLs.
        job_id = None
        for attr in ("data-job-id", "data-ev-job-id", "data-test-job-id"):
            job_id = card.get(attr)
            if job_id:
                break

        if not job_id:
            link = card.select_one('a[href*="/jobs/"], a[href*="/job/"]')
            if link and link.has_attr("href"):
                href = link["href"]
                # Upwork job URLs often look like /jobs/~xxxxxxxxxxxxxxxxxx/
                if "~" in href:
                    job_id = href.split("~", 1)[-1].split("/", 1)[0].split("?")[0]
                else:
                    job_id = href.rstrip("/").split("/")[-1].split("?")[0]

        title_el = card.select_one('[data-test="job-title-link"], h4, h3, a')
        title = clean_text(title_el.get_text()) if title_el else ""

        desc_el = card.select_one(
            '[data-test="job-description-text"], div[class*="description"], p'
        )
        description = clean_text(desc_el.get_text()) if desc_el else ""

        # Created at: look for "Posted ..." snippets.
        created_text = ""
        created_el = card.select_one('[data-test="job-posted-on"]')
        if created_el:
            created_text = created_el.get_text()
        else:
            # fallback: search for "Posted" text
            for small in card.select("small, span"):
                text = small.get_text(strip=True)
                if text.lower().startswith("posted"):
                    created_text = text
                    break

        created_at = parse_created_at(created_text)

        # Job type & duration
        job_type = parse_job_type(card.get_text(" ", strip=True))
        duration_el = card.select_one('[data-test="job-duration"], span:contains("month")')  # type: ignore[arg-type]
        duration = clean_text(duration_el.get_text()) if duration_el else ""

        # Budget
        budget_el = card.select_one(
            '[data-test="job-budget"], [data-test="job-hourly-rate"], '
            'span:contains("$"), strong:contains("$")'  # type: ignore[arg-type]
        )
        budget_text = clean_text(budget_el.get_text()) if budget_el else ""
        budget = parse_budget(budget_text)

        # Client information
        location_el = card.select_one('[data-test="client-location"], span[aria-label*="location"]')  # type: ignore[arg-type]
        client_location = clean_text(location_el.get_text()) if location_el else ""

        client_payment_verification = "payment verified" in card.get_text(
            " ", strip=True
        ).lower()

        spent_el = card.select_one('[data-test="client-spent"]')
        spent_text = clean_text(spent_el.get_text()) if spent_el else ""
        client_spent = parse_client_spent(spent_text)

        reviews = parse_client_reviews(card.get_text(" ", strip=True))

        # Category
        category_el = card.select_one(
            '[data-test="job-category"], [data-test="job-subcategory"]'
        )
        category = clean_text(category_el.get_text()) if category_el else ""

        skills = parse_skills_list(
            [tag.get_text() for tag in card.select('[data-test="skill-chip"], a[class*="skill"]')]
        )

        if not (job_id or title or description):
            # Too empty, skip this card.
            return None

        job: Dict[str, Any] = {
            "jobId": job_id or "",
            "title": title,
            "description": description,
            "createdAt": created_at,
            "jobType": job_type,
            "duration": duration,
            "budget": budget,
            "clientLocation": client_location,
            "clientPaymentVerification": client_payment_verification,
            "clientSpent": client_spent,
            "clientReviews": reviews,
            "category": category,
            "skills": skills,
        }
        return job

    def scrape(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """
        Scrape one or more search pages until max_items is reached or pages are exhausted.
        """
        jobs: List[Dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            if len(jobs) >= self.max_items:
                logger.info("Reached max_items=%s; stopping.", self.max_items)
                break

            html = self.fetch_search_page(page)
            if not html:
                logger.warning("Empty HTML for page %s, stopping.", page)
                break

            page_jobs = self.parse_jobs_from_html(html)
            logger.info("Page %s yielded %d jobs", page, len(page_jobs))

            for job in page_jobs:
                jobs.append(job)
                if len(jobs) >= self.max_items:
                    break

            if page < max_pages and len(jobs) < self.max_items:
                logger.debug("Sleeping for %.2fs between pages", self.delay_seconds)
                time.sleep(self.delay_seconds)

        logger.info("Scraping finished with %d jobs total", len(jobs))
        return jobs