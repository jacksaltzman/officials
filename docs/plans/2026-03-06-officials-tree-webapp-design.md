# Design: Colorado Officials Tree Visualization Webapp

**Date:** 2026-03-06
**Status:** Approved

## Goal

Build an interactive tree visualization of all 623 Colorado elected officials, organized by government level hierarchy. Internal tool for the Accountable team to browse and explore the officials database.

## Architecture

Single self-contained HTML file using D3.js for a collapsible top-down tree layout. Data generated from SQLite by a Python script into a nested JSON file. No build step — open `index.html` in a browser.

## Tech Stack

- D3.js v7 (CDN) — tree layout, collapsible nodes, zoom/pan
- Vanilla HTML/CSS/JS — no framework
- Python (data generation script)
- DM Sans + Oswald fonts (Google Fonts CDN)

## Tree Hierarchy

```
Colorado (root)
├─ Statewide Officials (5)
│  ├─ Governor: Jared Polis
│  ├─ Lt. Governor: Dianne Primavera
│  ├─ Attorney General: Phil Weiser
│  ├─ Secretary of State: Jena Griswold
│  └─ State Treasurer: Dave Young
├─ State Senate (35)
│  ├─ SD-1: Senator Name (D)
│  └─ ...
├─ State House (65)
│  ├─ HD-1: Representative Name (D)
│  └─ ...
├─ County Officials (64 counties)
│  ├─ Adams County
│  │  └─ Clerk: Name
│  └─ ...
└─ Municipal Officials (272 municipalities)
   ├─ City of Denver
   │  ├─ Mayor: Michael Johnston
   │  └─ Mayor Pro Tem: Name
   └─ ...
```

Tree starts collapsed — only 5 top-level categories visible. Users click to drill into any branch.

## UI Layout

### Tree Area

Full-viewport, tree centered, grows top-down. Pan and zoom enabled (scroll + drag).

### Node Types

**Category nodes** (e.g., "State Senate", "County Officials"):
- Dark background (`#111111`), white text
- Child count badge (e.g., "35")
- Click to expand/collapse

**Official nodes** (leaf nodes):
- White background, dark text
- Name + title displayed
- Party color indicator dot: blue (`#2563EB`) for D, red (`#DC2626`) for R, gray (`#9CA3AF`) for nonpartisan
- Click to open detail panel

### Detail Panel

Slide-in panel on the right (~350px), appears when clicking an official:
- Name (large)
- Title
- Party
- District (if applicable)
- County / Municipality (if applicable)
- Email (clickable mailto)
- Phone
- Website (clickable link)
- Twitter handle (clickable link to X profile)
- Facebook (clickable link)
- Source badge ("Open States", "CML Directory", etc.)

Close via X button or clicking outside.

### Controls

- **Search bar** (top) — type to filter/highlight officials, auto-expands matching branches
- **Expand All / Collapse All** buttons
- **Zoom controls** (+/- buttons)

### Branch Connectors

Curved SVG paths in brand teal (`#4C6971`), connecting parent to child nodes.

## Brand Compliance

- Background: `#FDFBF9` (paper)
- Category nodes: `#111111` bg, white text
- Official nodes: white bg, `#111111` text
- Connectors: `#4C6971` (brand teal)
- Party colors: `#2563EB` (D), `#DC2626` (R), `#9CA3AF` (nonpartisan)
- Typography: DM Sans (body), Oswald (headings/labels, uppercase + tracking)
- No shadows, flat aesthetic, rounded-lg cards

## Data Pipeline

### generate_tree_data.py

Reads `officials.db`, builds nested JSON hierarchy, writes to `webapp/data/tree.json`.

**JSON structure:**
```json
{
  "name": "Colorado",
  "children": [
    {
      "name": "Statewide Officials",
      "type": "category",
      "count": 5,
      "children": [
        {
          "name": "Jared Polis",
          "type": "official",
          "title": "Governor",
          "party": "Democratic",
          "district": null,
          "county": null,
          "municipality": null,
          "email": null,
          "phone": "303-866-2471",
          "website": "https://www.colorado.gov/governor/",
          "twitter_handle": "@GovofCO",
          "facebook_url": "https://www.facebook.com/GovernorPolis",
          "source": "manual"
        }
      ]
    },
    {
      "name": "State Senate",
      "type": "category",
      "count": 35,
      "children": [...]
    }
  ]
}
```

Category nodes have `type: "category"` and `children`. Official nodes have `type: "official"` and contact fields.

### Grouping Logic

- **Statewide:** All officials with `office_level = "statewide"`
- **State Senate:** Legislators with `body = "Senate"`, sorted by district number
- **State House:** Legislators with `body = "House"`, sorted by district number
- **County Officials:** Grouped by county name, each county is a sub-category
- **Municipal Officials:** Grouped by municipality name, each municipality is a sub-category

## File Structure

```
Officials/
  webapp/
    index.html              # The visualization app
    data/
      tree.json             # Generated hierarchy data
  code/
    generate_tree_data.py   # SQLite → nested JSON
```

## How It Loads

`index.html` fetches `data/tree.json` via relative path on page load. No server required — works as a static file opened in any browser.
