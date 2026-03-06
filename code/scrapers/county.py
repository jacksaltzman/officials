"""
County Clerk & Recorder scraper for Colorado.

Downloads the Colorado Secretary of State's County Clerks Roster PDF
and parses it to extract all 64 county clerks.

Source:
    https://www.sos.state.co.us/pubs/elections/Resources/files/CountyClerkRosterWebsite.pdf
"""

import logging
import re
import sys
from pathlib import Path

import httpx
import pdfplumber

# Ensure the parent ``code/`` directory is on sys.path so we can
# ``import db`` regardless of how this module is invoked.
_CODE_DIR = str(Path(__file__).resolve().parent.parent)
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from db import get_connection, upsert_official, count_officials, now_iso, DATA_DIR  # noqa: E402

log = logging.getLogger(__name__)

PDF_URL = (
    "https://www.sos.state.co.us/pubs/elections/Resources/files/"
    "CountyClerkRosterWebsite.pdf"
)
PDF_PATH = DATA_DIR / "county_clerks_roster.pdf"

# All 64 Colorado county names in uppercase (used to split the PDF text
# into per-county blocks).
COLORADO_COUNTIES = [
    "ADAMS", "ALAMOSA", "ARAPAHOE", "ARCHULETA", "BACA", "BENT",
    "BOULDER", "BROOMFIELD", "CHAFFEE", "CHEYENNE", "CLEAR CREEK",
    "CONEJOS", "COSTILLA", "CROWLEY", "CUSTER", "DELTA", "DENVER",
    "DOLORES", "DOUGLAS", "EAGLE", "EL PASO", "ELBERT", "FREMONT",
    "GARFIELD", "GILPIN", "GRAND", "GUNNISON", "HINSDALE", "HUERFANO",
    "JACKSON", "JEFFERSON", "KIOWA", "KIT CARSON", "LA PLATA", "LAKE",
    "LARIMER", "LAS ANIMAS", "LINCOLN", "LOGAN", "MESA", "MINERAL",
    "MOFFAT", "MONTEZUMA", "MONTROSE", "MORGAN", "OTERO", "OURAY",
    "PARK", "PHILLIPS", "PITKIN", "PROWERS", "PUEBLO", "RIO BLANCO",
    "RIO GRANDE", "ROUTT", "SAGUACHE", "SAN JUAN", "SAN MIGUEL",
    "SEDGWICK", "SUMMIT", "TELLER", "WASHINGTON", "WELD", "YUMA",
]


# ── Download ─────────────────────────────────────────────────────────────


def download_clerks_pdf() -> Path:
    """Download the County Clerks Roster PDF from the CO SoS website.

    The file is saved to ``data/county_clerks_roster.pdf``.  If the file
    already exists locally it is returned immediately (cache hit).

    Returns
    -------
    Path
        The local path to the downloaded PDF.
    """
    if PDF_PATH.exists():
        log.info("Clerks PDF already cached at %s", PDF_PATH)
        return PDF_PATH

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Downloading county clerks PDF from %s …", PDF_URL)

    # The CO SoS server blocks requests without a browser-like User-Agent
    # and may have SSL certificate issues, so we use verify=False as a
    # fallback when the default verification fails.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = httpx.get(
            PDF_URL, timeout=30, follow_redirects=True, headers=headers,
        )
        resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.ConnectError):
        log.warning("Retrying PDF download with SSL verification disabled")
        resp = httpx.get(
            PDF_URL, timeout=30, follow_redirects=True,
            headers=headers, verify=False,
        )
        resp.raise_for_status()

    PDF_PATH.write_bytes(resp.content)
    log.info("Saved %d bytes → %s", len(resp.content), PDF_PATH)
    return PDF_PATH


# ── Parsing ──────────────────────────────────────────────────────────────


def _county_slug(county_name: str) -> str:
    """Convert a county name to a lowercase alpha-only slug.

    Examples
    --------
    >>> _county_slug("EL PASO")
    'elpaso'
    >>> _county_slug("Clear Creek")
    'clearcreek'
    """
    return re.sub(r"[^a-z]", "", county_name.lower())


def _parse_name(raw_name: str) -> tuple[str, str, str]:
    """Parse a clerk name into (full_name, first_name, last_name).

    Handles both ``"Last, First"`` and ``"First Last"`` formats.
    Strips nicknames in quotes and middle initials for first/last split.
    """
    raw_name = raw_name.strip()

    if "," in raw_name:
        # "Last, First"
        parts = [p.strip() for p in raw_name.split(",", 1)]
        last_name = parts[0]
        first_name = parts[1]
    else:
        # "First [Middle] Last" — take first token as first, last token as last
        tokens = raw_name.split()
        first_name = tokens[0] if tokens else raw_name
        last_name = tokens[-1] if len(tokens) > 1 else ""

    # Clean up nicknames in quotes: Melinda "Mindy" Carter -> keep the full name
    # but extract clean first/last
    first_name = re.sub(r'["\u201C\u201D].*?["\u201C\u201D]', "", first_name).strip()
    # Remove single-char middle initials with period
    first_name = re.sub(r"\b[A-Z]\.\s*$", "", first_name).strip()

    full_name = raw_name
    return full_name, first_name, last_name


def _extract_email(block: str) -> str | None:
    """Extract the first email address from a text block."""
    # First try a straightforward match on the raw block.
    match = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", block)
    if match:
        return match.group(0).lower()

    # The PDF sometimes hyphenates long email addresses across lines
    # (e.g. "najondine.placek@costillacounty-\n<other text> co.gov").
    # Look for a partial email ending with "-" at end of line, then find
    # the domain continuation on a subsequent line.
    lines = block.split("\n")
    for i, line in enumerate(lines):
        partial = re.search(r"([\w.\-+]+@[\w.\-]+)-\s*$", line)
        if partial:
            for j in range(i + 1, min(i + 4, len(lines))):
                cont = re.search(r"\b([a-z][\w.\-]*\.[a-z]{2,})", lines[j])
                if cont:
                    return (partial.group(1) + "-" + cont.group(1)).lower()

    return None


def _split_into_county_blocks(full_text: str) -> list[tuple[str, str]]:
    """Split the concatenated PDF text into (county_name, block) tuples.

    Each county entry starts with the county name in uppercase at the
    beginning of a line, followed by address/phone/email data.
    """
    # Build a regex that matches any county name at the start of a line.
    # Sort by length descending so "CLEAR CREEK" matches before "CREEK", etc.
    sorted_counties = sorted(COLORADO_COUNTIES, key=len, reverse=True)
    county_pattern = "|".join(re.escape(c) for c in sorted_counties)
    pattern = re.compile(
        rf"^({county_pattern})\s",
        re.MULTILINE,
    )

    matches = list(pattern.finditer(full_text))
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        county_name = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        block_text = full_text[start:end]
        blocks.append((county_name, block_text))

    return blocks


def _extract_clerk_name(county_name: str, block: str) -> str | None:
    """Extract the clerk's name from a county block.

    The clerk name appears either as a standalone line or combined with
    ``Fax:`` info on the same line (e.g. ``"Josh Zygielbaum Fax: (720) ..."``).
    We strip the Fax portion first, then check whether the remainder looks
    like a person name.
    """
    lines = block.strip().splitlines()

    # Patterns for lines/fragments to skip entirely (after Fax stripping)
    skip_patterns = [
        re.compile(r"^\s*$"),                                  # blank
        re.compile(r"^" + re.escape(county_name), re.I),       # county header line
        re.compile(r"^\d+\s"),                                 # starts with number (address)
        re.compile(r"\(\d{3}\)"),                              # phone number
        re.compile(r"@"),                                      # email
        re.compile(r"PO Box", re.I),                           # PO Box
        re.compile(r",\s*CO\s+\d{5}", re.I),                  # city, CO ZIP
        re.compile(r"^\w+,\s*Co\s+\d{5}", re.I),              # city, Co ZIP (lowercase variant)
        re.compile(r"Revised on", re.I),                       # page footer
        re.compile(r"^\d+$"),                                  # just an ID number
        re.compile(r"^Ste\.", re.I),                           # suite continuation
        re.compile(r"^Rm\.", re.I),                            # room continuation
        re.compile(r"^Suite\b", re.I),                         # suite line
        re.compile(r"^Page\s+\d", re.I),                      # page marker
        re.compile(r"^STATE OF", re.I),                        # title header
        re.compile(r"^COUNTY CLERK", re.I),                    # title header
        re.compile(r"^ELECTIONS DIV", re.I),                   # title header
        re.compile(r"^COUNTY/CLERK", re.I),                    # column header
        re.compile(r"^\w+\s+\d{5}"),                           # city + ZIP without comma
        re.compile(r"^Fax\s*:", re.I),                         # standalone fax line
    ]

    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue

        # Strip "Fax: ..." and everything after it from the line
        candidate = re.split(r"\s*Fax\s*:\s*", candidate, flags=re.I)[0].strip()

        if not candidate:
            continue

        # Skip lines matching any of the known non-name patterns
        if any(p.search(candidate) for p in skip_patterns):
            continue

        # A name candidate should contain mostly letters, spaces, periods,
        # quotes, hyphens, and accented characters (e.g. López).
        if re.match(r'^[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F\s.\-\'\"\u2018\u2019\u201C\u201D]+$', candidate):
            # Must have at least 2 word-tokens to be a plausible name
            tokens = candidate.split()
            if len(tokens) >= 2:
                return candidate

    return None


def parse_clerks_pdf(pdf_path: Path) -> list[dict]:
    """Parse the County Clerks Roster PDF and return a list of official dicts.

    Parameters
    ----------
    pdf_path : Path
        Path to the downloaded PDF file.

    Returns
    -------
    list[dict]
        One dict per county clerk, ready for ``upsert_official()``.
    """
    pdf = pdfplumber.open(str(pdf_path))

    # Concatenate all page text
    full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    pdf.close()

    blocks = _split_into_county_blocks(full_text)
    scraped_at = now_iso()
    officials: list[dict] = []

    for county_name, block in blocks:
        clerk_name_raw = _extract_clerk_name(county_name, block)
        if not clerk_name_raw:
            log.warning("Could not find clerk name for %s", county_name)
            continue

        full_name, first_name, last_name = _parse_name(clerk_name_raw)
        email = _extract_email(block)
        county_title = county_name.title()
        slug = _county_slug(county_name)

        official = {
            "id": f"CO-CTY-{slug}-clerk",
            "name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "title": "County Clerk and Recorder",
            "office_level": "county",
            "office_branch": "executive",
            "body": None,
            "district": None,
            "party": None,
            "state": "CO",
            "county": county_title,
            "municipality": None,
            "email": email if email and "@" in email else None,
            "phone": None,
            "website": None,
            "twitter_handle": None,
            "twitter_verified": 0,
            "facebook_url": None,
            "photo_url": None,
            "source": "sos_clerks_pdf",
            "source_id": None,
            "scraped_at": scraped_at,
        }
        officials.append(official)

    return officials


# ── Entry point ──────────────────────────────────────────────────────────


def run() -> None:
    """Download the clerks PDF, parse it, and upsert all records."""
    pdf_path = download_clerks_pdf()
    officials = parse_clerks_pdf(pdf_path)

    conn = get_connection()
    for official in officials:
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, office_level="county")
    log.info(
        "Upserted %d county clerks.  Total county-level rows: %d",
        len(officials), total,
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
