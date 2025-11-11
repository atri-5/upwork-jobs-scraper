thonimport logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")

def clean_text(text: str) -> str:
    """
    Normalize whitespace and trim a string.
    """
    if text is None:
        return ""
    text = _WHITESPACE_RE.sub(" ", str(text))
    return text.strip()

def parse_created_at(text: str) -> str:
    """
    Convert Upwork-style "Posted X time ago" snippets into ISO 8601 timestamps.

    Examples of supported formats:
        "Posted 3 hours ago"
        "Posted 2 days ago"
        "Posted 1 minute ago"
        "Jan 10, 2025"
        "2025-01-10"

    If parsing fails, the cleaned original text is returned.
    """
    text_clean = clean_text(text).lower()
    if not text_clean:
        return ""

    # Strip leading "posted"
    if text_clean.startswith("posted"):
        text_clean = text_clean.replace("posted", "", 1).strip(" ,-")

    now = datetime.now(timezone.utc)

    # Relative patterns: "3 hours ago", "2 days ago", etc.
    m = re.match(r"(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks)\s+ago", text_clean)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        delta_kwargs: dict[str, Any] = {}
        if "minute" in unit:
            delta_kwargs["minutes"] = value
        elif "hour" in unit:
            delta_kwargs["hours"] = value
        elif "day" in unit:
            delta_kwargs["days"] = value
        elif "week" in unit:
            delta_kwargs["weeks"] = value

        created = now - timedelta(**delta_kwargs)
        return created.isoformat()

    # Simple words
    if text_clean in {"yesterday"}:
        created = now - timedelta(days=1)
        return created.isoformat()

    # Try direct date parsing
    try:
        dt = date_parser.parse(text_clean)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:  # noqa: BLE001
        logger.debug("Could not parse created_at from '%s'", text)
        return clean_text(text)

def parse_budget(text: str) -> str:
    """
    Return budget string as-is, just cleaned.

    Upwork expresses budgets in many formats ("$25/hr", "$500 fixed price").
    Normalizing that fully is beyond this example; we keep the value human-readable.
    """
    return clean_text(text)

def parse_client_spent(text: str) -> str:
    """
    Normalize client spent figures like "$15,000+".
    """
    return clean_text(text)

def parse_client_reviews(text: str) -> int:
    """
    Extract an approximate number of reviews from a block of client-related text.

    We look for patterns like "48 reviews" or just the first standalone number.
    """
    text_clean = clean_text(text).lower()
    # Prefer "... 48 reviews"
    m = re.search(r"(\d+)\s+reviews", text_clean)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Fallback: any reasonable number in text, but avoid huge numbers (spent, etc.)
    numbers = [int(n) for n in re.findall(r"\d+", text_clean) if n.isdigit()]
    for n in numbers:
        if 0 < n < 10000:
            return n
    return 0

def parse_job_type(text: str) -> str:
    """
    Determine whether the job is Hourly or Fixed, based on the card text.
    """
    text_clean = clean_text(text).lower()
    if "hourly" in text_clean:
        return "Hourly"
    if "fixed-price" in text_clean or "fixed price" in text_clean or "fixed-price" in text_clean:
        return "Fixed"
    # Default: unknown
    return ""

def parse_skills_list(skills_raw: Sequence[str]) -> List[str]:
    """
    Clean and deduplicate a sequence of skill names.
    """
    cleaned: List[str] = []
    seen = set()
    for raw in skills_raw:
        skill = clean_text(raw)
        if not skill:
            continue
        key = skill.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(skill)
    return cleaned

def safe_get(data: dict, key: str, default: Optional[Any] = "") -> Any:
    """
    Simple dictionary accessor with a default value.
    """
    return data.get(key, default)