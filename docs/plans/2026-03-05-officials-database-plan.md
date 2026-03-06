# Colorado Officials Database Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a database of every sub-federal elected official in Colorado — state legislators, statewide officers, county, municipal, and school board — with key staff and social media handles.

**Architecture:** Python pipeline reading from Open States API (state legislators) + web scraping (local officials), storing in SQLite, exporting to CSV/XLSX. Phased: legislators first, then statewide, county, municipal, school board, then social media enrichment.

**Tech Stack:** Python 3.11+, requests, beautifulsoup4, httpx, sqlite3, pandas, openpyxl, pdfplumber

---

## Task 1: Project Scaffold & Database Layer

**Files:**
- Create: `code/db.py`
- Create: `code/requirements.txt`
- Create: `code/__init__.py`
- Create: `code/scrapers/__init__.py`

**Step 1: Create requirements.txt**

```
code/requirements.txt
```

```text
requests>=2.31
beautifulsoup4>=4.12
httpx>=0.27
pandas>=2.1
openpyxl>=3.1
pdfplumber>=0.11
lxml>=5.1
```

**Step 2: Install dependencies**

Run: `pip install -r code/requirements.txt`

**Step 3: Create empty __init__.py files**

```
code/__init__.py
code/scrapers/__init__.py
```

Both empty files.

**Step 4: Write db.py — SQLite schema and helpers**

```python
# code/db.py
"""SQLite database helpers for the Officials pipeline."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # Officials/
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "officials.db"

# Read Open States API key from Environment.txt
_env_path = BASE_DIR / "Environment.txt"
OPENSTATES_API_KEY = ""
if _env_path.exists():
    for line in _env_path.read_text().strip().splitlines():
        if line.startswith("OPENSTATES_API_KEY="):
            OPENSTATES_API_KEY = line.split("=", 1)[1].strip()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS officials (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    office_level TEXT NOT NULL,
    office_branch TEXT,
    body TEXT,
    district TEXT,
    party TEXT,
    state TEXT NOT NULL DEFAULT 'CO',
    county TEXT,
    municipality TEXT,
    email TEXT,
    phone TEXT,
    website TEXT,
    twitter_handle TEXT,
    twitter_verified INTEGER DEFAULT 0,
    facebook_url TEXT,
    photo_url TEXT,
    source TEXT NOT NULL,
    source_id TEXT,
    scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS key_staff (
    id TEXT PRIMARY KEY,
    official_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    twitter_handle TEXT,
    facebook_url TEXT,
    source TEXT NOT NULL,
    FOREIGN KEY (official_id) REFERENCES officials(id)
);
"""


def get_connection() -> sqlite3.Connection:
    """Return a connection to the officials database, creating it if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def upsert_official(conn: sqlite3.Connection, official: dict) -> None:
    """Insert or replace an official record."""
    cols = [
        "id", "name", "first_name", "last_name", "title",
        "office_level", "office_branch", "body", "district", "party",
        "state", "county", "municipality", "email", "phone", "website",
        "twitter_handle", "twitter_verified", "facebook_url", "photo_url",
        "source", "source_id", "scraped_at",
    ]
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    values = [official.get(c) for c in cols]
    conn.execute(
        f"INSERT OR REPLACE INTO officials ({col_str}) VALUES ({placeholders})",
        values,
    )


def upsert_staff(conn: sqlite3.Connection, staff: dict) -> None:
    """Insert or replace a key staff record."""
    cols = ["id", "official_id", "name", "role", "email",
            "twitter_handle", "facebook_url", "source"]
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    values = [staff.get(c) for c in cols]
    conn.execute(
        f"INSERT OR REPLACE INTO key_staff ({col_str}) VALUES ({placeholders})",
        values,
    )


def count_officials(conn: sqlite3.Connection, office_level: str | None = None) -> int:
    """Count officials, optionally filtered by office_level."""
    if office_level:
        row = conn.execute(
            "SELECT COUNT(*) FROM officials WHERE office_level = ?", (office_level,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM officials").fetchone()
    return row[0]
```

**Step 5: Commit**

```bash
git add code/
git commit -m "feat: scaffold project with SQLite schema and db helpers"
```

---

## Task 2: Open States API Client (Phase 1 — State Legislators)

**Files:**
- Create: `code/open_states.py`

**Step 1: Write open_states.py**

```python
# code/open_states.py
"""Phase 1: Pull Colorado state legislators from the Open States API v3."""

import logging
import time

import requests

from db import (
    OPENSTATES_API_KEY, get_connection, now_iso, upsert_official, count_officials,
)

log = logging.getLogger(__name__)

API_BASE = "https://v3.openstates.org"


def fetch_co_legislators() -> list[dict]:
    """Fetch all current Colorado state legislators from Open States.

    Returns a list of raw person dicts from the API.
    """
    if not OPENSTATES_API_KEY:
        raise RuntimeError("OPENSTATES_API_KEY not found in Environment.txt")

    headers = {"X-API-KEY": OPENSTATES_API_KEY}
    all_people = []
    page = 1

    while True:
        log.info(f"Fetching Open States page {page}...")
        resp = requests.get(
            f"{API_BASE}/people",
            headers=headers,
            params={
                "jurisdiction": "Colorado",
                "org_classification": "legislature",
                "per_page": 50,
                "page": page,
                "include": ["offices", "links", "other_identifiers"],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        all_people.extend(data["results"])
        log.info(f"  Got {len(data['results'])} results (total so far: {len(all_people)})")

        if page >= data["pagination"]["max_page"]:
            break
        page += 1
        time.sleep(0.5)  # Be polite to the API

    return all_people


def _extract_twitter(person: dict) -> str | None:
    """Try to extract a Twitter handle from Open States person data."""
    # Check other_identifiers for twitter scheme
    for oid in person.get("other_identifiers", []):
        scheme = oid.get("scheme", "").lower()
        if "twitter" in scheme:
            handle = oid["identifier"].lstrip("@")
            return f"@{handle}"

    # Check links for twitter.com or x.com URLs
    for link in person.get("links", []):
        url = link.get("url", "").lower()
        if "twitter.com/" in url or "x.com/" in url:
            # Extract handle from URL
            parts = url.rstrip("/").split("/")
            if parts:
                handle = parts[-1].lstrip("@")
                if handle and handle not in ("home", "explore", "search"):
                    return f"@{handle}"

    return None


def _extract_facebook(person: dict) -> str | None:
    """Try to extract a Facebook URL from Open States person data."""
    for oid in person.get("other_identifiers", []):
        scheme = oid.get("scheme", "").lower()
        if "facebook" in scheme:
            identifier = oid["identifier"]
            if identifier.startswith("http"):
                return identifier
            return f"https://facebook.com/{identifier}"

    for link in person.get("links", []):
        url = link.get("url", "").lower()
        if "facebook.com/" in url:
            return link["url"]

    return None


def parse_legislator(person: dict) -> dict:
    """Convert an Open States person dict to our officials table schema."""
    role = person.get("current_role", {})
    org_class = role.get("org_classification", "")

    if org_class == "upper":
        chamber = "Senate"
        title = "State Senator"
        district = f"SD-{role.get('district', '')}"
    elif org_class == "lower":
        chamber = "House"
        title = "State Representative"
        district = f"HD-{role.get('district', '')}"
    else:
        chamber = org_class
        title = role.get("title", "Legislator")
        district = role.get("district", "")

    # Extract contact info from offices
    email = person.get("email", "")
    phone = ""
    for office in person.get("offices", []):
        if not phone and office.get("voice"):
            phone = office["voice"]
        if not email and office.get("email"):
            email = office["email"]

    # Extract website from links
    website = ""
    for link in person.get("links", []):
        url = link.get("url", "")
        if "twitter" not in url.lower() and "facebook" not in url.lower() and "x.com" not in url.lower():
            website = url
            break

    twitter = _extract_twitter(person)
    facebook = _extract_facebook(person)

    return {
        "id": f"CO-SL-{person['id'][-8:]}",
        "name": person.get("name", ""),
        "first_name": person.get("given_name", ""),
        "last_name": person.get("family_name", ""),
        "title": title,
        "office_level": "state_legislature",
        "office_branch": "legislative",
        "body": chamber,
        "district": district,
        "party": person.get("party", ""),
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": email or None,
        "phone": phone or None,
        "website": website or None,
        "twitter_handle": twitter,
        "twitter_verified": 1 if twitter else 0,
        "facebook_url": facebook,
        "photo_url": person.get("image") or None,
        "source": "openstates",
        "source_id": person.get("id", ""),
        "scraped_at": now_iso(),
    }


def run() -> None:
    """Execute Phase 1: pull all CO legislators and store in SQLite."""
    log.info("=== Phase 1: Open States — Colorado Legislators ===")

    people = fetch_co_legislators()
    log.info(f"Fetched {len(people)} legislators from Open States")

    conn = get_connection()
    for person in people:
        official = parse_legislator(person)
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, "state_legislature")
    log.info(f"Stored {total} state legislators in database")
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python open_states.py`
Expected: Logs showing ~100 legislators fetched and stored.

**Step 3: Verify data**

Run: `python -c "import sqlite3; conn = sqlite3.connect('../data/officials.db'); print(conn.execute('SELECT COUNT(*) FROM officials').fetchone()); print(conn.execute('SELECT name, title, district, party, twitter_handle FROM officials LIMIT 5').fetchall())"`
Expected: Count ~100, sample rows with names, titles, districts.

**Step 4: Commit**

```bash
git add code/open_states.py data/officials.db
git commit -m "feat: add Open States client — pull 100 CO legislators"
```

---

## Task 3: Statewide Officials (Phase 2a)

**Files:**
- Create: `code/scrapers/statewide.py`

**Step 1: Write statewide.py — hardcoded statewide officials**

These ~8 officials are a tiny, stable set. Hardcoding is appropriate — they change only at elections.

```python
# code/scrapers/statewide.py
"""Phase 2a: Statewide elected officials — hardcoded (tiny, stable dataset)."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_connection, now_iso, upsert_official, count_officials

log = logging.getLogger(__name__)

# Current Colorado statewide officials (updated manually at election cycles)
STATEWIDE_OFFICIALS = [
    {
        "id": "CO-SW-GOV",
        "name": "Jared Polis",
        "first_name": "Jared",
        "last_name": "Polis",
        "title": "Governor",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-866-2471",
        "website": "https://www.colorado.gov/governor/",
        "twitter_handle": "@GovofCO",
        "twitter_verified": 1,
        "facebook_url": "https://www.facebook.com/GovernorPolis",
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-LTGOV",
        "name": "Dianne Primavera",
        "first_name": "Dianne",
        "last_name": "Primavera",
        "title": "Lieutenant Governor",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-866-2471",
        "website": "https://ltgovernor.colorado.gov/",
        "twitter_handle": "@LtGovPrimavera",
        "twitter_verified": 1,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-AG",
        "name": "Phil Weiser",
        "first_name": "Phil",
        "last_name": "Weiser",
        "title": "Attorney General",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "720-508-6000",
        "website": "https://coag.gov/",
        "twitter_handle": "@AGPhilWeiser",
        "twitter_verified": 1,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-SOS",
        "name": "Jena Griswold",
        "first_name": "Jena",
        "last_name": "Griswold",
        "title": "Secretary of State",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-894-2200",
        "website": "https://www.sos.state.co.us/",
        "twitter_handle": "@JenaGriswold",
        "twitter_verified": 1,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-TREAS",
        "name": "Dave Young",
        "first_name": "Dave",
        "last_name": "Young",
        "title": "State Treasurer",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-866-2441",
        "website": "https://www.colorado.gov/treasury",
        "twitter_handle": None,
        "twitter_verified": 0,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
]


def run() -> None:
    """Store statewide officials in the database."""
    log.info("=== Phase 2a: Statewide Officials ===")

    conn = get_connection()
    for official in STATEWIDE_OFFICIALS:
        official["scraped_at"] = now_iso()
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, "statewide")
    log.info(f"Stored {total} statewide officials")
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python -m scrapers.statewide`
Expected: 5 statewide officials stored.

**Step 3: Verify**

Run: `python -c "import sqlite3; conn = sqlite3.connect('../data/officials.db'); print(conn.execute('SELECT name, title, twitter_handle FROM officials WHERE office_level=\"statewide\"').fetchall())"`

**Step 4: Commit**

```bash
git add code/scrapers/statewide.py
git commit -m "feat: add statewide officials (governor, AG, SoS, treasurer, lt gov)"
```

---

## Task 4: County Officials Scraper (Phase 2b)

**Files:**
- Create: `code/scrapers/county.py`

This task scrapes the Colorado Secretary of State's County Clerks PDF as a seed list, then scrapes individual county websites for commissioners and other elected officials.

**Step 1: Write county.py**

```python
# code/scrapers/county.py
"""Phase 2b: County elected officials.

Strategy:
1. Download SoS County Clerks PDF for all 64 county clerks (seed list)
2. Scrape Colorado General Assembly's county info for commissioners
3. Scrape individual county websites for sheriffs, assessors, etc.

This is the most complex scraper — county websites vary wildly.
Start with the clerks PDF (structured, reliable), then expand.
"""

import logging
import re
import sys
from pathlib import Path

import httpx
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_connection, now_iso, upsert_official, count_officials, DATA_DIR

log = logging.getLogger(__name__)

CLERKS_PDF_URL = "https://www.sos.state.co.us/pubs/elections/Resources/files/CountyClerkRosterWebsite.pdf"


def download_clerks_pdf() -> Path:
    """Download the SoS County Clerks roster PDF."""
    pdf_path = DATA_DIR / "county_clerks_roster.pdf"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if pdf_path.exists():
        log.info(f"Using cached clerks PDF: {pdf_path}")
        return pdf_path

    log.info(f"Downloading clerks PDF from {CLERKS_PDF_URL}")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(CLERKS_PDF_URL)
        resp.raise_for_status()
    pdf_path.write_bytes(resp.content)
    log.info(f"Saved to {pdf_path} ({len(resp.content)} bytes)")
    return pdf_path


def parse_clerks_pdf(pdf_path: Path) -> list[dict]:
    """Parse county clerk records from the SoS PDF.

    The PDF has a table with columns: County, Contact Person, Email, Location.
    Returns a list of official dicts ready for upsert.
    """
    officials = []
    scraped_at = now_iso()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 3:
                        continue
                    county_name = (row[0] or "").strip()
                    contact = (row[1] or "").strip()
                    email = (row[2] or "").strip()

                    # Skip header rows
                    if not county_name or county_name.lower() in ("county", "county name"):
                        continue

                    # Clean county name
                    county_clean = county_name.title().strip()

                    # Parse name
                    parts = contact.split(",", 1) if "," in contact else contact.rsplit(" ", 1)
                    if len(parts) == 2 and "," in contact:
                        last_name = parts[0].strip()
                        first_name = parts[1].strip()
                    elif len(parts) == 2:
                        first_name = parts[0].strip()
                        last_name = parts[1].strip()
                    else:
                        first_name = contact
                        last_name = ""

                    # Normalize email
                    email_clean = email.strip().lower() if email and "@" in email else None

                    county_slug = re.sub(r'[^a-z]', '', county_clean.lower())
                    official_id = f"CO-CTY-{county_slug}-clerk"

                    officials.append({
                        "id": official_id,
                        "name": contact,
                        "first_name": first_name,
                        "last_name": last_name,
                        "title": "County Clerk and Recorder",
                        "office_level": "county",
                        "office_branch": "executive",
                        "body": None,
                        "district": None,
                        "party": None,
                        "state": "CO",
                        "county": county_clean,
                        "municipality": None,
                        "email": email_clean,
                        "phone": None,
                        "website": None,
                        "twitter_handle": None,
                        "twitter_verified": 0,
                        "facebook_url": None,
                        "photo_url": None,
                        "source": "sos_clerks_pdf",
                        "source_id": None,
                        "scraped_at": scraped_at,
                    })

    log.info(f"Parsed {len(officials)} county clerks from PDF")
    return officials


def run() -> None:
    """Execute Phase 2b: county officials."""
    log.info("=== Phase 2b: County Officials ===")

    # Step 1: County clerks from SoS PDF
    pdf_path = download_clerks_pdf()
    clerks = parse_clerks_pdf(pdf_path)

    conn = get_connection()
    for clerk in clerks:
        upsert_official(conn, clerk)
    conn.commit()

    total = count_officials(conn, "county")
    log.info(f"Total county officials in database: {total}")
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python -m scrapers.county`
Expected: ~64 county clerks parsed and stored.

**Step 3: Verify**

Run: `python -c "import sqlite3; conn = sqlite3.connect('../data/officials.db'); print('Count:', conn.execute('SELECT COUNT(*) FROM officials WHERE office_level=\"county\"').fetchone()); print(conn.execute('SELECT county, name, email FROM officials WHERE office_level=\"county\" LIMIT 5').fetchall())"`

**Step 4: Commit**

```bash
git add code/scrapers/county.py
git commit -m "feat: add county clerks scraper from SoS PDF (64 counties)"
```

**Note:** The county scraper starts with clerks only. Commissioners, sheriffs, and assessors require scraping individual county websites — that can be expanded incrementally as a follow-up task after the core pipeline is working.

---

## Task 5: Municipal Officials — CML Directory PDF (Phase 2c)

**Files:**
- Create: `code/scrapers/municipal.py`

**Step 1: Write municipal.py**

The CML Municipal Directory PDF (2025 edition) covers 271 municipalities. PDF parsing extracts mayors and key officials.

```python
# code/scrapers/municipal.py
"""Phase 2c: Municipal officials from CML Municipal Directory PDF.

The Colorado Municipal League publishes an annual directory covering
271 municipalities with mayors, council members, and key staff.
"""

import logging
import re
import sys
from pathlib import Path

import httpx
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_connection, now_iso, upsert_official, count_officials, DATA_DIR

log = logging.getLogger(__name__)

CML_PDF_URL = "https://www.cml.org/docs/default-source/municipal-directory/cml-municipal-directory-2025.pdf"


def download_cml_pdf() -> Path:
    """Download the CML Municipal Directory PDF."""
    pdf_path = DATA_DIR / "cml_municipal_directory_2025.pdf"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if pdf_path.exists():
        log.info(f"Using cached CML PDF: {pdf_path}")
        return pdf_path

    log.info(f"Downloading CML directory from {CML_PDF_URL}")
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(CML_PDF_URL)
        resp.raise_for_status()
    pdf_path.write_bytes(resp.content)
    log.info(f"Saved to {pdf_path} ({len(resp.content)} bytes)")
    return pdf_path


def parse_cml_pdf(pdf_path: Path) -> list[dict]:
    """Parse municipal officials from the CML directory PDF.

    The PDF structure varies — each municipality entry typically has:
    - Municipality name (bold/header)
    - Address, phone, fax
    - Mayor name
    - Council/trustee members
    - City/town manager/administrator

    This parser extracts what it can. Due to PDF formatting variability,
    some entries may be missed — that's expected for the pilot.
    """
    officials = []
    scraped_at = now_iso()

    with pdfplumber.open(pdf_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    # Split by municipality entries — look for patterns like
    # "CITY OF ..." or "TOWN OF ..." in uppercase
    # This is a best-effort parser; the exact format needs tuning
    # after examining the actual PDF structure.
    entries = re.split(r'\n(?=(?:CITY|TOWN|VILLAGE) OF [A-Z])', full_text)

    for entry in entries:
        lines = entry.strip().split("\n")
        if not lines:
            continue

        # Try to extract municipality name from first line
        first_line = lines[0].strip()
        muni_match = re.match(r'(CITY|TOWN|VILLAGE) OF (.+)', first_line, re.IGNORECASE)
        if not muni_match:
            continue

        muni_type = muni_match.group(1).title()
        muni_name = muni_match.group(2).strip().title()
        muni_slug = re.sub(r'[^a-z]', '', muni_name.lower())

        # Search for mayor line
        for line in lines:
            mayor_match = re.match(r'Mayor[:\s]+(.+)', line, re.IGNORECASE)
            if mayor_match:
                mayor_name = mayor_match.group(1).strip()
                if mayor_name and len(mayor_name) > 2:
                    officials.append({
                        "id": f"CO-MUN-{muni_slug}-mayor",
                        "name": mayor_name,
                        "first_name": mayor_name.split()[0] if " " in mayor_name else mayor_name,
                        "last_name": mayor_name.split()[-1] if " " in mayor_name else "",
                        "title": "Mayor",
                        "office_level": "municipal",
                        "office_branch": "executive",
                        "body": f"{muni_type} Council",
                        "district": None,
                        "party": None,
                        "state": "CO",
                        "county": None,
                        "municipality": muni_name,
                        "email": None,
                        "phone": None,
                        "website": None,
                        "twitter_handle": None,
                        "twitter_verified": 0,
                        "facebook_url": None,
                        "photo_url": None,
                        "source": "cml_directory",
                        "source_id": None,
                        "scraped_at": scraped_at,
                    })
                break

    log.info(f"Parsed {len(officials)} municipal officials from CML PDF")
    return officials


def run() -> None:
    """Execute Phase 2c: municipal officials."""
    log.info("=== Phase 2c: Municipal Officials ===")

    pdf_path = download_cml_pdf()
    officials = parse_cml_pdf(pdf_path)

    conn = get_connection()
    for official in officials:
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, "municipal")
    log.info(f"Total municipal officials in database: {total}")
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python -m scrapers.municipal`
Expected: Mayors extracted from CML PDF. Count will depend on PDF parsing accuracy — even getting 100+ mayors is a good start.

**Step 3: Review and tune**

After the first run, examine the PDF structure and adjust the parsing regex as needed. The parser is intentionally conservative — it extracts mayors first, and can be expanded to council members later.

**Step 4: Commit**

```bash
git add code/scrapers/municipal.py
git commit -m "feat: add municipal officials scraper from CML directory PDF"
```

---

## Task 6: School Board Members — CDE Data (Phase 2d)

**Files:**
- Create: `code/scrapers/school_board.py`

**Step 1: Write school_board.py**

The Colorado Department of Education publishes downloadable Excel files with school district contact information, updated weekly.

```python
# code/scrapers/school_board.py
"""Phase 2d: School board members from Colorado Dept of Education data.

CDE publishes district-level Excel files at:
https://www.cde.state.co.us/cdegen/educationdirectory

These include district superintendents and contact info. Board member
names may require scraping the CDE Data Pipeline or individual district sites.

This module starts with the CDE directory download for district-level coverage.
"""

import logging
import re
import sys
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_connection, now_iso, upsert_official, count_officials, DATA_DIR

log = logging.getLogger(__name__)

# CDE education directory — district contact info Excel
CDE_DIRECTORY_URL = "https://www.cde.state.co.us/cdegen/educationdirectory"


def download_cde_directory() -> Path | None:
    """Attempt to download the CDE district directory Excel file.

    The exact download URL may need to be discovered from the directory page.
    Returns the path to the downloaded file, or None if unavailable.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Try direct download URLs for the district directory
    # CDE publishes Excel files — exact URL may vary by year
    possible_urls = [
        "https://www.cde.state.co.us/cdereval/2024-25districtmailinglabels",
        "https://www.cde.state.co.us/cdereval/downloadablemailinglabels",
    ]

    for url in possible_urls:
        try:
            log.info(f"Trying CDE URL: {url}")
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "spreadsheet" in content_type or "excel" in content_type:
                        path = DATA_DIR / "cde_districts.xlsx"
                        path.write_bytes(resp.content)
                        log.info(f"Downloaded CDE directory to {path}")
                        return path
                    else:
                        log.info(f"  Got HTML page, not Excel — will need to parse for download link")
        except Exception as e:
            log.warning(f"  Failed: {e}")

    log.warning("Could not auto-download CDE directory. Manual download may be required.")
    log.warning(f"Visit {CDE_DIRECTORY_URL} and save the district Excel file to {DATA_DIR}/cde_districts.xlsx")
    return None


def parse_cde_directory(excel_path: Path) -> list[dict]:
    """Parse district superintendent/contact info from CDE Excel file.

    This gets us one official per school district (superintendent) as a starting point.
    Board members will need to be sourced from individual district websites.
    """
    officials = []
    scraped_at = now_iso()

    try:
        df = pd.read_excel(excel_path)
    except Exception as e:
        log.error(f"Failed to read Excel file: {e}")
        return officials

    log.info(f"CDE Excel has {len(df)} rows, columns: {list(df.columns)}")

    # The exact column names depend on the file format
    # Common columns: District Name, Superintendent, Address, Phone, Email
    # We'll map what we find
    for _, row in df.iterrows():
        # Try to find district name and superintendent columns
        district_name = None
        super_name = None
        email = None
        phone = None

        for col in df.columns:
            col_lower = str(col).lower()
            val = str(row[col]).strip() if pd.notna(row[col]) else ""
            if not val:
                continue

            if "district" in col_lower and "name" in col_lower:
                district_name = val
            elif "superintendent" in col_lower or "admin" in col_lower:
                super_name = val
            elif "email" in col_lower:
                email = val.lower()
            elif "phone" in col_lower:
                phone = val

        if district_name and super_name:
            slug = re.sub(r'[^a-z0-9]', '', district_name.lower())[:20]
            officials.append({
                "id": f"CO-SB-{slug}-super",
                "name": super_name,
                "first_name": super_name.split()[0] if " " in super_name else super_name,
                "last_name": super_name.split()[-1] if " " in super_name else "",
                "title": "Superintendent",
                "office_level": "school_board",
                "office_branch": "executive",
                "body": district_name,
                "district": None,
                "party": None,
                "state": "CO",
                "county": None,
                "municipality": None,
                "email": email if email and "@" in email else None,
                "phone": phone,
                "website": None,
                "twitter_handle": None,
                "twitter_verified": 0,
                "facebook_url": None,
                "photo_url": None,
                "source": "cde_directory",
                "source_id": None,
                "scraped_at": scraped_at,
            })

    log.info(f"Parsed {len(officials)} school district officials from CDE data")
    return officials


def run() -> None:
    """Execute Phase 2d: school board/district officials."""
    log.info("=== Phase 2d: School Board / District Officials ===")

    excel_path = DATA_DIR / "cde_districts.xlsx"

    if not excel_path.exists():
        downloaded = download_cde_directory()
        if not downloaded:
            log.warning("Skipping school board phase — CDE data not available")
            log.warning("Manual step: download district Excel from CDE website")
            return
        excel_path = downloaded

    officials = parse_cde_directory(excel_path)

    conn = get_connection()
    for official in officials:
        upsert_official(conn, official)
    conn.commit()

    total = count_officials(conn, "school_board")
    log.info(f"Total school district officials in database: {total}")
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python -m scrapers.school_board`
Expected: Either auto-downloads and parses CDE data, or prints a message to manually download.

**Step 3: Commit**

```bash
git add code/scrapers/school_board.py
git commit -m "feat: add school district officials scraper from CDE data"
```

---

## Task 7: Export Module (CSV/XLSX)

**Files:**
- Create: `code/export.py`

**Step 1: Write export.py**

```python
# code/export.py
"""Export officials and staff data to CSV/XLSX files."""

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from db import get_connection

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"


def export_officials() -> pd.DataFrame:
    """Export all officials to CSV and XLSX."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()

    df = pd.read_sql_query("SELECT * FROM officials ORDER BY office_level, name", conn)
    conn.close()

    if df.empty:
        log.warning("No officials found in database")
        return df

    csv_path = OUTPUT_DIR / "co_officials.csv"
    xlsx_path = OUTPUT_DIR / "co_officials.xlsx"

    df.to_csv(csv_path, index=False)
    log.info(f"CSV written: {csv_path} ({len(df)} rows)")

    df.to_excel(xlsx_path, index=False, sheet_name="CO Officials")
    log.info(f"XLSX written: {xlsx_path} ({len(df)} rows)")

    return df


def export_staff() -> pd.DataFrame:
    """Export all key staff to CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT s.*, o.name AS official_name, o.title AS official_title
        FROM key_staff s
        JOIN officials o ON s.official_id = o.id
        ORDER BY o.name, s.role
        """,
        conn,
    )
    conn.close()

    if df.empty:
        log.info("No staff records found")
        return df

    csv_path = OUTPUT_DIR / "co_key_staff.csv"
    df.to_csv(csv_path, index=False)
    log.info(f"Staff CSV written: {csv_path} ({len(df)} rows)")

    return df


def write_summary(officials_df: pd.DataFrame) -> None:
    """Write co_officials_summary.md with coverage stats."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT_DIR / "co_officials_summary.md"

    lines = []
    lines.append("# Colorado Officials Database — Summary\n")
    lines.append(f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d')}\n")

    # Overall stats
    total = len(officials_df)
    lines.append(f"## Overview\n")
    lines.append(f"- **Total officials in database:** {total}")

    # By level
    lines.append(f"\n## Officials by Level\n")
    lines.append("| Level | Count |")
    lines.append("|-------|-------|")
    level_counts = officials_df["office_level"].value_counts()
    for level, count in level_counts.items():
        lines.append(f"| {level} | {count} |")

    # Party breakdown
    lines.append(f"\n## Party Breakdown\n")
    lines.append("| Party | Count |")
    lines.append("|-------|-------|")
    party_counts = officials_df["party"].fillna("Unknown/Nonpartisan").value_counts()
    for party, count in party_counts.items():
        lines.append(f"| {party} | {count} |")

    # Social media coverage
    has_twitter = officials_df["twitter_handle"].notna().sum()
    has_email = officials_df["email"].notna().sum()
    lines.append(f"\n## Contact Coverage\n")
    lines.append(f"- **Officials with Twitter handle:** {has_twitter} ({has_twitter/total*100:.1f}%)")
    lines.append(f"- **Officials with email:** {has_email} ({has_email/total*100:.1f}%)")

    # Coverage by level with estimates
    lines.append(f"\n## Coverage Assessment\n")
    lines.append("| Level | Found | Estimated Total | Coverage |")
    lines.append("|-------|-------|-----------------|----------|")
    estimates = {
        "statewide": 8,
        "state_legislature": 100,
        "county": 400,
        "municipal": 2000,
        "school_board": 1200,
    }
    for level, estimate in estimates.items():
        found = level_counts.get(level, 0)
        pct = found / estimate * 100 if estimate else 0
        lines.append(f"| {level} | {found} | ~{estimate} | {pct:.0f}% |")

    lines.append("")
    summary_path.write_text("\n".join(lines))
    log.info(f"Summary written: {summary_path}")


def run() -> None:
    """Export all data."""
    log.info("=== Exporting Data ===")
    officials_df = export_officials()
    export_staff()
    if not officials_df.empty:
        write_summary(officials_df)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python export.py`
Expected: CSV, XLSX, and summary markdown generated in `output/`.

**Step 3: Commit**

```bash
git add code/export.py output/
git commit -m "feat: add CSV/XLSX export and summary markdown generation"
```

---

## Task 8: Main Pipeline Orchestrator

**Files:**
- Create: `code/pipeline.py`

**Step 1: Write pipeline.py**

```python
# code/pipeline.py
"""Main pipeline: orchestrate all phases of the Officials database build."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    """Run the full pipeline."""
    log.info("=" * 60)
    log.info("Colorado Officials Database Pipeline")
    log.info("=" * 60)

    # Phase 1: State legislators
    from open_states import run as run_open_states
    run_open_states()

    # Phase 2a: Statewide officials
    from scrapers.statewide import run as run_statewide
    run_statewide()

    # Phase 2b: County officials
    from scrapers.county import run as run_county
    run_county()

    # Phase 2c: Municipal officials
    from scrapers.municipal import run as run_municipal
    run_municipal()

    # Phase 2d: School board officials
    from scrapers.school_board import run as run_school_board
    run_school_board()

    # Export
    from export import run as run_export
    run_export()

    log.info("=" * 60)
    log.info("Pipeline complete!")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
```

**Step 2: Run the full pipeline**

Run: `cd code && python pipeline.py`
Expected: All phases run in sequence, database populated, exports generated.

**Step 3: Review output**

Run: `cat ../output/co_officials_summary.md`
Check: Coverage numbers make sense, all levels represented.

**Step 4: Commit**

```bash
git add code/pipeline.py
git commit -m "feat: add main pipeline orchestrator"
```

---

## Task 9: Social Media Enrichment (Phase 3 — Stub)

**Files:**
- Create: `code/enrich_social.py`

**Step 1: Write enrich_social.py — stub with manual enrichment support**

Phase 3 (automated social handle discovery via web search) is complex and depends on the base data being solid first. For now, create a stub that:
- Reports current social media coverage stats
- Provides a CLI for manual handle entry
- Leaves hooks for future automated enrichment

```python
# code/enrich_social.py
"""Phase 3: Social media enrichment.

Current capability: report coverage stats and support manual handle updates.
Future: automated X profile search, Google search, website scraping for handles.
"""

import logging
import sys
from pathlib import Path

import pandas as pd

from db import get_connection

log = logging.getLogger(__name__)


def report_coverage() -> None:
    """Print social media coverage stats."""
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM officials", conn)
    conn.close()

    total = len(df)
    if total == 0:
        log.warning("No officials in database")
        return

    has_twitter = df["twitter_handle"].notna().sum()
    has_facebook = df["facebook_url"].notna().sum()
    has_email = df["email"].notna().sum()

    log.info(f"Social media coverage for {total} officials:")
    log.info(f"  Twitter:  {has_twitter:>4} ({has_twitter/total*100:.1f}%)")
    log.info(f"  Facebook: {has_facebook:>4} ({has_facebook/total*100:.1f}%)")
    log.info(f"  Email:    {has_email:>4} ({has_email/total*100:.1f}%)")

    # By level
    for level in df["office_level"].unique():
        level_df = df[df["office_level"] == level]
        lt = len(level_df)
        tw = level_df["twitter_handle"].notna().sum()
        log.info(f"  {level}: {tw}/{lt} with Twitter ({tw/lt*100:.1f}%)")


def update_handle(official_id: str, twitter_handle: str, verified: bool = True) -> None:
    """Manually update a Twitter handle for an official."""
    conn = get_connection()
    conn.execute(
        "UPDATE officials SET twitter_handle = ?, twitter_verified = ? WHERE id = ?",
        (twitter_handle, 1 if verified else 0, official_id),
    )
    conn.commit()
    log.info(f"Updated {official_id} with Twitter handle {twitter_handle}")
    conn.close()


def run() -> None:
    """Report current social media coverage."""
    log.info("=== Phase 3: Social Media Enrichment ===")
    report_coverage()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python enrich_social.py`
Expected: Coverage stats printed showing how many officials have Twitter handles.

**Step 3: Commit**

```bash
git add code/enrich_social.py
git commit -m "feat: add social media enrichment stub with coverage reporting"
```

---

## Task 10: End-to-End Validation

**Files:** None new — validation of existing pipeline.

**Step 1: Clean run from scratch**

Run: `rm -f data/officials.db && cd code && python pipeline.py`
Expected: Full pipeline runs, database recreated, exports generated.

**Step 2: Validate database**

Run:
```bash
cd code && python -c "
import sqlite3
conn = sqlite3.connect('../data/officials.db')
print('=== OFFICIALS ===')
for row in conn.execute('SELECT office_level, COUNT(*) FROM officials GROUP BY office_level'):
    print(f'  {row[0]}: {row[1]}')
print(f'  TOTAL: {conn.execute(\"SELECT COUNT(*) FROM officials\").fetchone()[0]}')
print()
print('=== SAMPLE (first 3 per level) ===')
for level in ['statewide', 'state_legislature', 'county', 'municipal', 'school_board']:
    print(f'  --- {level} ---')
    for row in conn.execute('SELECT name, title, twitter_handle FROM officials WHERE office_level=? LIMIT 3', (level,)):
        print(f'    {row}')
"
```

**Step 3: Review exports**

Run: `ls -la ../output/`
Check: `co_officials.csv`, `co_officials.xlsx`, `co_officials_summary.md` all exist.

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete Colorado officials pipeline — Phase 1 & 2"
```

---

## Post-Pipeline Notes

### What's built
- Phase 1: 100 state legislators from Open States API
- Phase 2a: 5 statewide officials (hardcoded)
- Phase 2b: ~64 county clerks from SoS PDF
- Phase 2c: Mayors from CML directory PDF (count depends on parsing)
- Phase 2d: School district officials from CDE data (may need manual download)
- Export: CSV, XLSX, summary markdown
- Social enrichment: coverage reporting stub

### What's next (future tasks)
1. **Expand county scraper** — add commissioners, sheriffs, assessors by scraping individual county websites
2. **Expand municipal scraper** — add city council members from top 20 city websites
3. **Automated social media enrichment** — X profile search, Google search, website scraping
4. **Phase 4: Tweet collection** — requires X API subscription (~$200/mo)
5. **Scale to additional states** — parameterize pipeline with state argument

### Known limitations
- PDF parsers (CML, SoS) may need tuning after seeing actual PDF structure
- CDE data download may require manual step
- County coverage limited to clerks only (no commissioners yet)
- Municipal coverage limited to mayors (no council members yet)
