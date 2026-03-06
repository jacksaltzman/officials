"""
Open States API v3 client — Colorado state legislators.

Pulls all Colorado state legislators from the Open States API and
upserts them into the local SQLite database via the ``db`` module.
"""

import logging
import time
from urllib.parse import urlparse

import requests

from db import (
    OPENSTATES_API_KEY,
    get_connection,
    upsert_official,
    count_officials,
    now_iso,
)

log = logging.getLogger(__name__)

BASE_URL = "https://v3.openstates.org"
PEOPLE_ENDPOINT = f"{BASE_URL}/people"


# ── Fetching ──────────────────────────────────────────────────────────────


def fetch_co_legislators() -> list[dict]:
    """Paginate through the Open States people endpoint for Colorado.

    Returns a list of raw person dicts from the API.
    Raises RuntimeError if no API key is configured.
    """
    if not OPENSTATES_API_KEY:
        raise RuntimeError(
            "OPENSTATES_API_KEY is not set.  "
            "Add it to Environment.txt in the project root."
        )

    headers = {"X-API-KEY": OPENSTATES_API_KEY}
    params: dict = {
        "jurisdiction": "Colorado",
        "per_page": 50,
        "include": ["offices", "links", "other_identifiers"],
    }

    all_people: list[dict] = []
    page = 1

    while True:
        params["page"] = page
        log.info("Fetching page %d from Open States ...", page)

        resp = requests.get(PEOPLE_ENDPOINT, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        all_people.extend(results)

        pagination = data.get("pagination", {})
        max_page = pagination.get("max_page", page)
        log.info(
            "  Page %d/%d — got %d people (total so far: %d)",
            page,
            max_page,
            len(results),
            len(all_people),
        )

        if page >= max_page:
            break

        page += 1
        time.sleep(0.5)

    log.info("Fetched %d legislators total from Open States.", len(all_people))
    return all_people


# ── Social-media extraction ───────────────────────────────────────────────

_TWITTER_DOMAINS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
_FACEBOOK_DOMAINS = {"facebook.com", "www.facebook.com", "m.facebook.com"}


def _handle_from_url(url: str, domains: set[str]) -> str | None:
    """Extract the path-based handle from a URL if the domain matches."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.hostname and parsed.hostname.lower() in domains:
        # Strip leading slash and any trailing query/fragment
        path = parsed.path.strip("/")
        # Take only the first path segment (the handle)
        handle = path.split("/")[0] if path else None
        return handle or None
    return None


def _extract_twitter(person: dict) -> str | None:
    """Return the Twitter/X handle as ``@handle``, or None.

    Checks ``other_identifiers`` for a twitter scheme first, then scans
    ``links`` for twitter.com / x.com URLs.
    """
    # 1. Check other_identifiers
    for oid in person.get("other_identifiers", []) or []:
        if (oid.get("scheme") or "").lower() == "twitter":
            raw = (oid.get("identifier") or "").strip().lstrip("@")
            if raw:
                return f"@{raw}"

    # 2. Fall back to links
    for link in person.get("links", []) or []:
        url = link.get("url", "")
        handle = _handle_from_url(url, _TWITTER_DOMAINS)
        if handle:
            return f"@{handle}"

    return None


def _extract_facebook(person: dict) -> str | None:
    """Return the Facebook URL or handle, or None.

    Checks ``other_identifiers`` for a facebook scheme first, then scans
    ``links`` for facebook.com URLs.
    """
    # 1. Check other_identifiers
    for oid in person.get("other_identifiers", []) or []:
        if (oid.get("scheme") or "").lower() == "facebook":
            raw = (oid.get("identifier") or "").strip()
            if raw:
                return raw

    # 2. Fall back to links
    for link in person.get("links", []) or []:
        url = link.get("url", "")
        handle = _handle_from_url(url, _FACEBOOK_DOMAINS)
        if handle:
            return url  # return full URL for Facebook
    return None


# ── Parsing ───────────────────────────────────────────────────────────────


def parse_legislator(person: dict) -> dict:
    """Convert an Open States person dict to our ``officials`` table schema."""
    ocd_id: str = person.get("id", "")
    last8 = ocd_id[-8:] if len(ocd_id) >= 8 else ocd_id

    current_role = person.get("current_role") or {}
    org_class = current_role.get("org_classification", "")
    district_num = current_role.get("district", "")

    is_senate = org_class == "upper"
    title = "State Senator" if is_senate else "State Representative"
    district = f"SD-{district_num}" if is_senate else f"HD-{district_num}"
    body = "Senate" if is_senate else "House"

    # -- Email: prefer top-level, fall back to offices
    email = person.get("email") or ""
    if not email:
        for office in person.get("offices", []) or []:
            if office.get("email"):
                email = office["email"]
                break

    # -- Phone: from offices
    phone = ""
    for office in person.get("offices", []) or []:
        if office.get("voice"):
            phone = office["voice"]
            break

    # -- Website: first non-social-media link
    website = ""
    social_domains = _TWITTER_DOMAINS | _FACEBOOK_DOMAINS
    for link in person.get("links", []) or []:
        url = link.get("url", "")
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
        if host.lower() not in social_domains and url:
            website = url
            break

    return {
        "id": f"CO-SL-{last8}",
        "name": person.get("name", ""),
        "first_name": person.get("given_name") or "",
        "last_name": person.get("family_name") or "",
        "title": title,
        "office_level": "state_legislature",
        "office_branch": "legislative",
        "body": body,
        "district": district,
        "party": person.get("party") or "",
        "state": "CO",
        "email": email,
        "phone": phone,
        "website": website,
        "twitter_handle": _extract_twitter(person),
        "facebook_url": _extract_facebook(person),
        "photo_url": person.get("image") or "",
        "source": "openstates",
        "source_id": ocd_id,
        "scraped_at": now_iso(),
    }


# ── Entry point ───────────────────────────────────────────────────────────


def run() -> None:
    """Fetch all Colorado state legislators and upsert into the database."""
    people = fetch_co_legislators()
    conn = get_connection()

    inserted = 0
    skipped = 0
    for person in people:
        # Only process actual legislators (upper=Senate, lower=House)
        role = (person.get("current_role") or {})
        org_class = role.get("org_classification", "")
        if org_class not in ("upper", "lower"):
            skipped += 1
            log.debug("Skipping non-legislator: %s (org=%s)", person.get("name"), org_class)
            continue

        record = parse_legislator(person)
        upsert_official(conn, record)
        inserted += 1

    if skipped:
        log.info("Skipped %d non-legislator records.", skipped)

    total = count_officials(conn, office_level="state_legislature")
    log.info(
        "Upserted %d legislators.  Total state_legislature rows: %d",
        inserted,
        total,
    )
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    run()
