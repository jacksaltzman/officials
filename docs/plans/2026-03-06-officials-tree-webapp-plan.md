# Officials Tree Visualization Webapp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a D3.js collapsible tree visualization of 623 Colorado elected officials, browsable by government hierarchy with click-to-expand details.

**Architecture:** Python script generates nested JSON from SQLite DB. Single HTML file uses D3.js v7 to render a collapsible top-down tree with zoom/pan, search, and a slide-in detail panel. No build step.

**Tech Stack:** D3.js v7 (CDN), vanilla HTML/CSS/JS, Python + sqlite3 (data generation), DM Sans + Oswald fonts (Google Fonts CDN)

---

## Task 1: Generate Tree Data (Python → JSON)

**Files:**
- Create: `code/generate_tree_data.py`

**Step 1: Write generate_tree_data.py**

This script reads all officials from the SQLite database, builds the nested hierarchy, and writes `webapp/data/tree.json`.

```python
# code/generate_tree_data.py
"""Generate nested JSON tree from officials database for the webapp visualization."""

import json
import logging
import re
import sqlite3
from pathlib import Path

from db import get_connection, BASE_DIR

log = logging.getLogger(__name__)

WEBAPP_DIR = BASE_DIR / "webapp"
DATA_DIR = WEBAPP_DIR / "data"


def _district_sort_key(district: str) -> int:
    """Extract numeric district number for sorting (e.g., 'SD-12' → 12)."""
    match = re.search(r'(\d+)', district or "")
    return int(match.group(1)) if match else 0


def _official_node(row: sqlite3.Row) -> dict:
    """Convert a DB row to a leaf node dict for the tree JSON."""
    return {
        "name": row["name"],
        "type": "official",
        "title": row["title"],
        "party": row["party"],
        "district": row["district"],
        "county": row["county"],
        "municipality": row["municipality"],
        "email": row["email"],
        "phone": row["phone"],
        "website": row["website"],
        "twitter_handle": row["twitter_handle"],
        "facebook_url": row["facebook_url"],
        "source": row["source"],
    }


def build_tree(conn: sqlite3.Connection) -> dict:
    """Build the full nested tree structure from the database."""
    conn.row_factory = sqlite3.Row

    # -- Statewide officials --
    statewide = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'statewide' ORDER BY title"
    ).fetchall()
    statewide_node = {
        "name": "Statewide Officials",
        "type": "category",
        "count": len(statewide),
        "children": [_official_node(r) for r in statewide],
    }

    # -- State Senate --
    senate = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'state_legislature' AND body = 'Senate' ORDER BY district"
    ).fetchall()
    senate_sorted = sorted(senate, key=lambda r: _district_sort_key(r["district"]))
    senate_node = {
        "name": "State Senate",
        "type": "category",
        "count": len(senate),
        "children": [_official_node(r) for r in senate_sorted],
    }

    # -- State House --
    house = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'state_legislature' AND body = 'House' ORDER BY district"
    ).fetchall()
    house_sorted = sorted(house, key=lambda r: _district_sort_key(r["district"]))
    house_node = {
        "name": "State House",
        "type": "category",
        "count": len(house),
        "children": [_official_node(r) for r in house_sorted],
    }

    # -- County officials (grouped by county) --
    counties = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'county' ORDER BY county, title"
    ).fetchall()
    county_groups = {}
    for r in counties:
        county_name = r["county"] or "Unknown County"
        if county_name not in county_groups:
            county_groups[county_name] = []
        county_groups[county_name].append(_official_node(r))

    county_children = []
    for county_name in sorted(county_groups.keys()):
        officials = county_groups[county_name]
        if len(officials) == 1:
            # Single official — don't nest, add county to name
            node = officials[0]
            node["_county_label"] = county_name
            county_children.append({
                "name": county_name,
                "type": "category",
                "count": 1,
                "children": officials,
            })
        else:
            county_children.append({
                "name": county_name,
                "type": "category",
                "count": len(officials),
                "children": officials,
            })

    county_node = {
        "name": "County Officials",
        "type": "category",
        "count": len(counties),
        "children": county_children,
    }

    # -- Municipal officials (grouped by municipality) --
    municipals = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'municipal' ORDER BY municipality, title"
    ).fetchall()
    muni_groups = {}
    for r in municipals:
        muni_name = r["municipality"] or "Unknown Municipality"
        if muni_name not in muni_groups:
            muni_groups[muni_name] = []
        muni_groups[muni_name].append(_official_node(r))

    muni_children = []
    for muni_name in sorted(muni_groups.keys()):
        officials = muni_groups[muni_name]
        muni_children.append({
            "name": muni_name,
            "type": "category",
            "count": len(officials),
            "children": officials,
        })

    municipal_node = {
        "name": "Municipal Officials",
        "type": "category",
        "count": len(municipals),
        "children": muni_children,
    }

    # -- Root --
    tree = {
        "name": "Colorado",
        "type": "category",
        "children": [
            statewide_node,
            senate_node,
            house_node,
            county_node,
            municipal_node,
        ],
    }

    return tree


def run() -> None:
    """Generate tree.json from the officials database."""
    log.info("=== Generating Tree Data ===")

    conn = get_connection()
    tree = build_tree(conn)
    conn.close()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "tree.json"
    output_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False))

    # Count nodes
    def count_nodes(node):
        if "children" in node:
            return 1 + sum(count_nodes(c) for c in node["children"])
        return 1

    total = count_nodes(tree)
    log.info(f"Wrote {output_path} ({total} nodes)")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
```

**Step 2: Run it**

Run: `cd code && python generate_tree_data.py`
Expected: `webapp/data/tree.json` created with ~1000+ nodes (623 officials + category nodes).

**Step 3: Verify JSON structure**

Run: `python -c "import json; t = json.load(open('../webapp/data/tree.json')); print(t['name']); print([c['name'] + ': ' + str(c.get('count', '')) for c in t['children']])"`
Expected: `Colorado` and 5 children with counts.

**Step 4: Commit**

```bash
git add code/generate_tree_data.py webapp/data/tree.json
git commit -m "feat: add tree data generator (SQLite → nested JSON)"
```

---

## Task 2: Build the Interactive Tree Webapp

**Files:**
- Create: `webapp/index.html`

**Step 1: Write index.html**

This is the core of the project — a single self-contained HTML file with embedded CSS and JS that loads `data/tree.json` and renders a D3.js collapsible tree.

The file must include:

**HTML structure:**
- Full-viewport layout
- Top bar with title "Colorado Officials", search input, Expand All / Collapse All buttons, zoom +/- buttons
- SVG area for the D3 tree (fills remaining viewport)
- Right slide-in detail panel (hidden by default, 350px wide)

**CSS (embedded `<style>`):**
- Google Fonts: DM Sans (body) + Oswald (headings)
- Background: `#FDFBF9`
- Category nodes: `#111111` bg, white text, rounded rect, child count badge
- Official nodes: white bg with `1px solid #E5E5E5` border, name + title text, party color dot
- Party dots: `#2563EB` (Democratic), `#DC2626` (Republican), `#9CA3AF` (default/nonpartisan)
- Connectors: `stroke: #4C6971`, curved paths (`d3.linkVertical()`)
- Detail panel: fixed right, white bg, slide-in animation via CSS transform
- Search bar styling
- Responsive: panel overlays on small screens

**JavaScript (embedded `<script>`):**

1. **Load data:** `fetch('data/tree.json')` on DOMContentLoaded

2. **D3 tree layout:**
   - Use `d3.tree()` with dynamic sizing based on node count
   - Each node starts with `_children` (collapsed) except root's direct children
   - `d3.zoom()` on the SVG for pan/zoom

3. **Render function `update(source)`:**
   - Compute tree layout from root
   - Enter/update/exit pattern for nodes and links
   - Nodes: `<g>` containing `<rect>` + `<text>` (category) or `<rect>` + `<circle>` party dot + `<text>` name + `<text>` title (official)
   - Links: `d3.linkVertical()` curved paths in teal
   - Smooth transitions (duration ~400ms) on expand/collapse

4. **Click handlers:**
   - Category node click → toggle `children`/`_children` (expand/collapse), call `update(d)`
   - Official node click → populate and show detail panel

5. **Detail panel:**
   - `showDetail(d)` — populate panel fields from node data, add `active` class to slide in
   - `hideDetail()` — remove `active` class
   - Clickable links for email (mailto:), website, Twitter (https://x.com/{handle}), Facebook
   - Show/hide fields based on what's available (skip null fields)

6. **Search:**
   - On input, filter all official nodes by name (case-insensitive substring match)
   - Expand branches containing matches
   - Highlight matching nodes (e.g., yellow border)
   - Clear highlights when search is empty

7. **Expand All / Collapse All:**
   - Recursively set all nodes' `children`/`_children` and call `update(root)`

8. **Zoom controls:**
   - +/- buttons call `d3.zoom().scaleBy()` on the SVG

**Key D3 patterns to use:**

```javascript
// Tree layout
const treeLayout = d3.tree().nodeSize([nodeWidth + gapX, nodeHeight + gapY]);

// Collapse function
function collapse(d) {
    if (d.children) {
        d._children = d.children;
        d._children.forEach(collapse);
        d.children = null;
    }
}

// Toggle on click
function toggle(d) {
    if (d.children) {
        d._children = d.children;
        d.children = null;
    } else {
        d.children = d._children;
        d._children = null;
    }
}

// Vertical links
const linkGenerator = d3.linkVertical()
    .x(d => d.x)
    .y(d => d.y);
```

**Step 2: Test locally**

Open `webapp/index.html` in a browser (or use a local server: `cd webapp && python -m http.server 8080`).

Verify:
- Tree renders with "Colorado" at the root and 5 collapsed branches
- Clicking a branch expands it with smooth animation
- Clicking an official opens the detail panel on the right
- Search filters and highlights officials
- Expand All / Collapse All work
- Zoom/pan works

**Step 3: Commit**

```bash
git add webapp/index.html
git commit -m "feat: add interactive D3.js tree visualization of Colorado officials"
```

---

## Task 3: Integration & Polish

**Files:**
- Modify: `code/pipeline.py` (add generate_tree_data to pipeline)

**Step 1: Add tree data generation to pipeline**

Add to the end of `pipeline.py`'s `main()` function, after the export step:

```python
# Generate tree visualization data
from generate_tree_data import run as run_tree_data
run_tree_data()
```

**Step 2: Run full pipeline**

Run: `cd code && python pipeline.py`
Expected: All phases run, tree.json regenerated.

**Step 3: Final verification**

Open `webapp/index.html` in browser. Confirm all data is present and interactions work.

**Step 4: Commit**

```bash
git add code/pipeline.py
git commit -m "feat: integrate tree data generation into main pipeline"
```
