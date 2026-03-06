"""
School district officials for Colorado — CDE directory data.

Attempts to download the Colorado Department of Education district directory
Excel file and parse superintendent information from it.  If the automatic
download fails (the CDE URLs sometimes serve HTML pages rather than direct
Excel downloads), the module gracefully falls back to looking for a manually
placed ``data/cde_districts.xlsx`` file.
"""

import logging
import re
import sys
from pathlib import Path

# Ensure the parent ``code/`` directory is on sys.path so we can
# ``import db`` regardless of how this module is invoked.
_CODE_DIR = str(Path(__file__).resolve().parent.parent)
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from db import get_connection, upsert_official, count_officials, now_iso, DATA_DIR  # noqa: E402

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

CDE_URLS = [
    # Direct CEDAR download (most reliable — returns .xlsx directly).
    "https://cedar.cde.state.co.us/edulibdir/District Addresses-en.xlsx",
    # Landing pages that *may* redirect to an Excel download.
    "https://www.cde.state.co.us/cdereval/2024-25districtmailinglabels",
    "https://www.cde.state.co.us/cdereval/downloadablemailinglabels",
]

EXCEL_PATH = DATA_DIR / "cde_districts.xlsx"

# Content-type prefixes that indicate a spreadsheet file.
_SPREADSHEET_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml",
    "application/vnd.ms-excel",
    "application/octet-stream",
)


# ── Download ──────────────────────────────────────────────────────────────


def download_cde_directory() -> Path | None:
    """Try to download the CDE district directory Excel file.

    Attempts each URL in ``CDE_URLS`` in order.  If the response appears to
    be an Excel/spreadsheet file (based on Content-Type), it is saved to
    ``data/cde_districts.xlsx`` and the path is returned.

    If the response is HTML (common — CDE pages sometimes serve a landing
    page instead of a direct download), a warning is logged and ``None`` is
    returned.

    Returns
    -------
    Path or None
        The path to the saved Excel file, or ``None`` if downloading failed.
    """
    import httpx

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for url in CDE_URLS:
        log.info("Trying CDE download: %s", url)
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
        except Exception:
            # Retry with SSL verification disabled (CDE certificates
            # sometimes fail local verification).
            try:
                log.info("Retrying %s with SSL verify=False", url)
                resp = httpx.get(
                    url, timeout=30, follow_redirects=True, verify=False,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("HTTP error fetching %s: %s", url, exc)
                continue

        content_type = resp.headers.get("content-type", "").lower()

        # Check if the response is HTML rather than a spreadsheet.
        if "text/html" in content_type:
            log.warning(
                "URL returned HTML instead of Excel: %s  "
                "(CDE may require manual download)",
                url,
            )
            continue

        # Accept known spreadsheet content types.
        if any(content_type.startswith(ct) for ct in _SPREADSHEET_CONTENT_TYPES):
            EXCEL_PATH.write_bytes(resp.content)
            log.info(
                "Downloaded CDE directory (%d bytes) -> %s",
                len(resp.content),
                EXCEL_PATH,
            )
            return EXCEL_PATH

        # Unknown content type — log and skip.
        log.warning(
            "Unexpected content-type from %s: %s",
            url,
            content_type,
        )

    log.warning("Could not auto-download CDE directory from any URL.")
    return None


# ── Parsing ───────────────────────────────────────────────────────────────


def _find_column(columns: list[str], *keywords: str) -> str | None:
    """Return the first column name that contains any of *keywords* (case-insensitive)."""
    for col in columns:
        col_lower = str(col).lower()
        for kw in keywords:
            if kw in col_lower:
                return col
    return None


def _make_slug(district_name: str) -> str:
    """Create a short slug from a district name for use in IDs."""
    alpha_only = re.sub(r"[^a-z]", "", district_name.lower())
    return alpha_only[:20]


def _parse_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (first_name, last_name).

    Handles simple "First Last" and "First Middle Last" patterns.
    """
    parts = full_name.strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[-1])


def _detect_header_row(excel_path: Path) -> int | None:
    """Scan the first 20 rows of the Excel file for the actual header row.

    The CDE district files typically have a decorative title block at the top
    (e.g. "Colorado Department of Education / District Addresses") followed
    by blank rows, then the real column header row containing keywords like
    "District Name", "Phone", etc.

    Returns the 0-based row index of the header, or ``None`` if not found.
    """
    import pandas as pd

    # Read without any header so we can inspect raw rows.
    try:
        df_raw = pd.read_excel(excel_path, engine="openpyxl", header=None, nrows=20)
    except Exception:
        return None

    for idx in range(len(df_raw)):
        row_values = [str(v).lower() for v in df_raw.iloc[idx] if pd.notna(v)]
        # A real header row should have multiple non-null cells (at least 4)
        # and contain typical header keywords.
        if len(row_values) < 4:
            continue
        row_text = " ".join(row_values)
        if "district" in row_text and ("phone" in row_text or "email" in row_text or "address" in row_text):
            return idx
    return None


def parse_cde_directory(excel_path: Path) -> list[dict]:
    """Read the CDE district directory Excel file and extract superintendent records.

    The exact column names depend on the file format published by CDE, so
    this function searches for columns containing relevant keywords like
    "district", "superintendent", "admin", "email", and "phone".

    The CDE "District Addresses" file includes district names, phone numbers,
    email domains, and county names but typically does **not** include
    superintendent names.  When a superintendent/admin column is present,
    named records are created; otherwise the module logs a warning.

    Parameters
    ----------
    excel_path : Path
        Path to the CDE district directory ``.xlsx`` file.

    Returns
    -------
    list[dict]
        A list of official dictionaries ready for ``upsert_official()``.
    """
    import pandas as pd

    log.info("Reading CDE Excel file: %s", excel_path)

    # Detect the real header row (CDE files have decorative title rows).
    header_row = _detect_header_row(excel_path)
    if header_row is not None:
        log.info("Detected header row at index %d", header_row)

    # Try reading the file — some CDE files have multiple sheets.
    try:
        df = pd.read_excel(
            excel_path,
            engine="openpyxl",
            header=header_row if header_row is not None else 0,
        )
    except Exception as exc:
        log.error("Failed to read Excel file %s: %s", excel_path, exc)
        return []

    columns = list(df.columns)
    log.info("Excel columns: %s", columns)

    # Locate relevant columns by keyword matching.
    # "District Name" is preferred over bare "District" columns like "District Code".
    district_col = _find_column(columns, "district name") or _find_column(columns, "district")
    super_col = _find_column(columns, "superintendent", "admin")
    email_col = _find_column(columns, "email")
    phone_col = _find_column(columns, "phone")
    county_col = _find_column(columns, "county name", "county")

    if district_col is None:
        log.warning("No 'district' column found in %s", excel_path)
        return []
    if super_col is None:
        log.warning(
            "No superintendent/admin column found in %s. "
            "Available columns: %s  "
            "(the CDE district-addresses file does not include superintendent "
            "names — a file with personnel data is required)",
            excel_path,
            columns,
        )
        return []

    log.info(
        "Matched columns — district: %r, superintendent: %r, email: %r, phone: %r, county: %r",
        district_col,
        super_col,
        email_col,
        phone_col,
        county_col,
    )

    scraped = now_iso()
    officials: list[dict] = []

    for _, row in df.iterrows():
        district_name = str(row.get(district_col, "")).strip()
        super_name = str(row.get(super_col, "")).strip()

        # Skip rows without a district or superintendent name.
        if not district_name or district_name.lower() in ("nan", ""):
            continue
        if not super_name or super_name.lower() in ("nan", ""):
            continue

        slug = _make_slug(district_name)
        if not slug:
            continue

        first_name, last_name = _parse_name(super_name)

        # Extract optional fields.
        email_val = None
        if email_col is not None:
            raw_email = str(row.get(email_col, "")).strip()
            if "@" in raw_email and raw_email.lower() != "nan":
                email_val = raw_email

        phone_val = None
        if phone_col is not None:
            raw_phone = str(row.get(phone_col, "")).strip()
            if raw_phone and raw_phone.lower() != "nan":
                phone_val = raw_phone

        county_val = None
        if county_col is not None:
            raw_county = str(row.get(county_col, "")).strip()
            if raw_county and raw_county.lower() != "nan":
                county_val = raw_county.title()

        official = {
            "id": f"CO-SB-{slug}-super",
            "name": super_name,
            "first_name": first_name,
            "last_name": last_name,
            "title": "Superintendent",
            "office_level": "school_board",
            "office_branch": "executive",
            "body": district_name,
            "district": None,
            "party": None,
            "state": "CO",
            "county": county_val,
            "municipality": None,
            "email": email_val,
            "phone": phone_val,
            "website": None,
            "twitter_handle": None,
            "twitter_verified": 0,
            "facebook_url": None,
            "photo_url": None,
            "source": "cde_directory",
            "source_id": None,
            "scraped_at": scraped,
        }
        officials.append(official)

    log.info("Parsed %d superintendent records from CDE directory.", len(officials))
    return officials


# ── Entry point ───────────────────────────────────────────────────────────


def run() -> None:
    """Download, parse, and upsert school district officials.

    If the automatic download fails, looks for a manually placed
    ``data/cde_districts.xlsx`` file.  If neither is available, logs
    instructions for manual download and returns gracefully.
    """
    # Step 1: Try automatic download.
    excel_path = download_cde_directory()

    # Step 2: Fall back to a manually placed file.
    if excel_path is None and EXCEL_PATH.exists():
        log.info("Using manually placed file: %s", EXCEL_PATH)
        excel_path = EXCEL_PATH

    # Step 3: If no file is available, provide instructions and exit.
    if excel_path is None:
        log.warning(
            "No CDE district directory file available.\n"
            "  To use this scraper, manually download the district directory:\n"
            "    1. Visit https://www.cde.state.co.us/cdereval/downloadablemailinglabels\n"
            "    2. Download the district mailing labels Excel file.\n"
            "    3. Save it as: %s\n"
            "    4. Re-run this scraper.",
            EXCEL_PATH,
        )
        return

    # Step 4: Parse and upsert.
    officials = parse_cde_directory(excel_path)
    if not officials:
        log.warning("No superintendent records found in %s", excel_path)
        return

    conn = get_connection()
    for official in officials:
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, office_level="school_board")
    log.info(
        "Upserted %d school district officials.  Total school_board rows: %d",
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
