"""
Municipal officials scraper for Colorado.

Downloads and parses the Colorado Municipal League (CML) municipal directory
PDF to extract mayors and other municipal officials.

Source: https://www.cml.org/docs/default-source/municipal-directory/cml-municipal-directory-2025.pdf
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

# ── Constants ─────────────────────────────────────────────────────────────

PDF_URL = (
    "https://www.cml.org/docs/default-source/municipal-directory/"
    "cml-municipal-directory-2025.pdf"
)
PDF_FILENAME = "cml_municipal_directory_2025.pdf"

# Regex to identify a municipality header line like "TOWN OF AGUILAR" or "CITY OF AURORA"
_MUNI_HEADER_RE = re.compile(
    r"^(CITY AND COUNTY|CITY|TOWN)\s+OF\s+(.+)$", re.IGNORECASE
)

# Titles we want to extract from the roster.
# The mayor is the primary target, but we also grab mayor pro tem.
_TITLE_PATTERNS = [
    # "Mayor Pro Tem" or "Mayor Pro Tempore" -- must come first
    (re.compile(r"\bMayor\s+Pro\s+Tem(?:pore)?\b", re.IGNORECASE), "Mayor Pro Tem"),
    (re.compile(r"\bMayor\b", re.IGNORECASE), "Mayor"),
]


# ── Download ──────────────────────────────────────────────────────────────


def download_cml_pdf() -> Path:
    """Download the CML municipal directory PDF.

    Returns the local path.  Skips the download if the file already exists.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = DATA_DIR / PDF_FILENAME

    if pdf_path.exists():
        log.info("PDF already cached at %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
        return pdf_path

    log.info("Downloading CML directory PDF from %s ...", PDF_URL)
    resp = httpx.get(PDF_URL, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    pdf_path.write_bytes(resp.content)
    log.info("Downloaded %d bytes to %s", len(resp.content), pdf_path)
    return pdf_path


# ── PDF Parsing ───────────────────────────────────────────────────────────


def _make_slug(name: str) -> str:
    """Turn a municipality name into a lowercase alpha-only slug.

    Examples:
        "Colorado Springs" -> "coloradosprings"
        "Mt. Crested Butte" -> "mtcrestedbutte"
    """
    return re.sub(r"[^a-z]", "", name.lower())


def _parse_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (first_name, last_name).

    Handles simple cases; for names with suffixes like 'Jr.' the suffix
    stays with the last name.
    """
    parts = full_name.strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def _extract_municipality_blocks(pdf_path: Path) -> list[dict]:
    """Extract municipality blocks from the PDF.

    Each block contains:
        - muni_type: "City" or "Town"
        - muni_name: e.g. "Aguilar"
        - county: from "County: X" line
        - phone: from "Phone: X" line
        - website: URL if found
        - roster_lines: list of lines from the Roster section
    """
    blocks: list[dict] = []
    current_block: dict | None = None
    in_roster = False

    log.info("Opening PDF: %s", pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        log.info("PDF has %d pages", total_pages)

        # Directory entries start at page 9 (index 8) and run through page 316 (index 315)
        # Page 317 (index 316) is "Nonmember Municipalities" -- skip it
        start_page = 8
        end_page = min(total_pages, 316)  # exclusive; pages 9..316 inclusive

        for page_idx in range(start_page, end_page):
            page = pdf.pages[page_idx]
            text = page.extract_text()
            if not text:
                continue

            lines = text.strip().split("\n")

            for line in lines:
                line_stripped = line.strip()

                # Skip the footer line
                if line_stripped.startswith("CML MUNICIPAL DIRECTORY"):
                    continue

                # Skip the "Colorado Municipal League" header
                if line_stripped == "Colorado Municipal League":
                    continue

                # Skip "Printed:" lines
                if line_stripped.startswith("Printed:"):
                    continue

                # Check for a municipality header
                m = _MUNI_HEADER_RE.match(line_stripped)
                if m:
                    # Save previous block if any
                    if current_block is not None:
                        blocks.append(current_block)

                    raw_type = m.group(1).strip()
                    # Normalize: "CITY AND COUNTY" -> "City", "CITY" -> "City", "TOWN" -> "Town"
                    if raw_type.upper().startswith("CITY"):
                        muni_type = "City"
                    else:
                        muni_type = "Town"
                    muni_name = m.group(2).strip()
                    # Normalize name to title case (PDF uses ALL CAPS)
                    muni_name = _normalize_muni_name(muni_name)

                    current_block = {
                        "muni_type": muni_type,
                        "muni_name": muni_name,
                        "county": None,
                        "phone": None,
                        "website": None,
                        "roster_lines": [],
                    }
                    in_roster = False
                    continue

                if current_block is None:
                    continue

                # Inside a block -- gather metadata
                if line_stripped == "Roster":
                    in_roster = True
                    continue

                if not in_roster:
                    # Parse county
                    if line_stripped.startswith("County:"):
                        current_block["county"] = line_stripped.split(":", 1)[1].strip()
                    # Parse phone
                    elif line_stripped.startswith("Phone:"):
                        current_block["phone"] = line_stripped.split(":", 1)[1].strip()
                    # Parse website (lines that look like URLs)
                    elif (
                        re.match(r"^(https?://|www\.|\w+\.\w+\.)", line_stripped)
                        and " " not in line_stripped
                    ):
                        url = line_stripped
                        if not url.startswith("http"):
                            url = "https://" + url
                        current_block["website"] = url
                else:
                    # We're in the roster section -- collect lines
                    if line_stripped:
                        current_block["roster_lines"].append(line_stripped)

        # Don't forget the last block
        if current_block is not None:
            blocks.append(current_block)

    log.info("Extracted %d municipality blocks from PDF", len(blocks))
    return blocks


def _normalize_muni_name(name: str) -> str:
    """Convert an ALL CAPS municipality name to proper title case.

    Handles special cases like 'MT.' and multi-word names.
    """
    # The PDF header is like "AGUILAR", "COLORADO SPRINGS", "MT. CRESTED BUTTE"
    words = name.split()
    result = []
    for word in words:
        if word.upper() == "MT.":
            result.append("Mt.")
        elif word.upper() == "DE":
            result.append("De")
        else:
            result.append(word.capitalize())
    return " ".join(result)


def _extract_official_from_roster_line(
    line: str,
    muni_name: str,
    muni_type: str,
    county: str | None,
    phone: str | None,
    website: str | None,
) -> dict | None:
    """Try to extract a mayor or mayor pro tem from a roster line.

    Roster lines look like:
        "Erlinda Encinias Mayor"
        "Gerald Baudino Mayor Pro Tem"
        "Lauren Simpson Mayor"

    Returns a dict suitable for upsert_official, or None if the line
    doesn't contain a target title.
    """
    for pattern, title in _TITLE_PATTERNS:
        m = pattern.search(line)
        if m:
            # The name is everything before the title match
            name_part = line[:m.start()].strip()
            if not name_part:
                return None

            # Handle compound titles like "Council President / Mayor"
            # where the name_part would be "Cody Kennedy Council President /"
            # Strip any trailing " Title / " or " Title /" from the name
            name_part = re.sub(
                r"\s+(?:Council\s+President|City\s+Council\s+President)\s*/?\s*$",
                "",
                name_part,
                flags=re.IGNORECASE,
            ).strip()

            # Clean up the name -- remove trailing commas, slashes, etc.
            name_part = name_part.rstrip(",/").strip()
            if not name_part:
                return None

            first_name, last_name = _parse_name(name_part)
            slug = _make_slug(muni_name)

            # Build ID
            title_slug = "mayor" if title == "Mayor" else "mayorprotem"
            official_id = f"CO-MUN-{slug}-{title_slug}"

            # Determine body name
            if muni_type == "City":
                body = "City Council"
            else:
                body = "Town Board"

            return {
                "id": official_id,
                "name": name_part,
                "first_name": first_name,
                "last_name": last_name,
                "title": title,
                "office_level": "municipal",
                "office_branch": "executive",
                "body": body,
                "district": None,
                "party": None,
                "state": "CO",
                "county": county,
                "municipality": muni_name,
                "email": None,
                "phone": phone,
                "website": website,
                "twitter_handle": None,
                "twitter_verified": 0,
                "facebook_url": None,
                "photo_url": None,
                "source": "cml_directory",
                "source_id": None,
                "scraped_at": now_iso(),
            }

    return None


def parse_cml_pdf(pdf_path: Path) -> list[dict]:
    """Parse the CML municipal directory PDF and extract officials.

    Returns a list of official dicts ready for upsert_official().
    """
    blocks = _extract_municipality_blocks(pdf_path)
    officials: list[dict] = []
    munis_with_mayor = 0
    munis_without_mayor = 0

    for block in blocks:
        muni_name = block["muni_name"]
        muni_type = block["muni_type"]
        county = block["county"]
        phone = block["phone"]
        website = block["website"]
        found_mayor = False

        for roster_line in block["roster_lines"]:
            try:
                official = _extract_official_from_roster_line(
                    roster_line, muni_name, muni_type, county, phone, website
                )
                if official:
                    officials.append(official)
                    if official["title"] == "Mayor":
                        found_mayor = True
            except Exception:
                log.warning(
                    "Could not parse roster line for %s: %r",
                    muni_name,
                    roster_line,
                    exc_info=True,
                )

        if found_mayor:
            munis_with_mayor += 1
        else:
            munis_without_mayor += 1
            log.debug("No mayor found for %s %s", muni_type, muni_name)

    log.info(
        "Parsed %d officials from %d municipalities "
        "(%d with mayor, %d without mayor)",
        len(officials),
        len(blocks),
        munis_with_mayor,
        munis_without_mayor,
    )
    return officials


# ── Entry point ───────────────────────────────────────────────────────────


def run() -> None:
    """Download the CML directory PDF, parse it, and upsert all officials."""
    pdf_path = download_cml_pdf()
    officials = parse_cml_pdf(pdf_path)

    if not officials:
        log.warning("No officials extracted from PDF — nothing to upsert.")
        return

    conn = get_connection()
    for official in officials:
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, office_level="municipal")
    log.info(
        "Upserted %d municipal officials.  Total municipal rows in DB: %d",
        len(officials),
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
