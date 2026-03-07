"""Canonical Colorado county list and normalization utilities."""

# All 64 Colorado counties in alphabetical order.
COLORADO_COUNTIES = [
    "Adams", "Alamosa", "Arapahoe", "Archuleta",
    "Baca", "Bent", "Boulder", "Broomfield",
    "Chaffee", "Cheyenne", "Clear Creek", "Conejos", "Costilla", "Crowley", "Custer",
    "Delta", "Denver", "Dolores", "Douglas",
    "Eagle", "El Paso", "Elbert",
    "Fremont",
    "Garfield", "Gilpin", "Grand", "Gunnison",
    "Hinsdale", "Huerfano",
    "Jackson", "Jefferson",
    "Kiowa", "Kit Carson",
    "La Plata", "Lake", "Larimer", "Las Animas", "Lincoln", "Logan",
    "Mesa", "Mineral", "Moffat", "Montezuma", "Montrose", "Morgan",
    "Otero", "Ouray",
    "Park", "Phillips", "Pitkin", "Prowers", "Pueblo",
    "Rio Blanco", "Rio Grande", "Routt",
    "Saguache", "San Juan", "San Miguel", "Sedgwick", "Summit",
    "Teller",
    "Washington", "Weld",
    "Yuma",
]

# Lookup map: lowercased canonical name -> canonical name
_COUNTY_LOOKUP: dict[str, str] = {name.lower(): name for name in COLORADO_COUNTIES}

# Values the LLM sometimes returns that are not real counties.
_JUNK_VALUES = frozenset({
    "n/a",
    "unknown",
    "none",
    "statewide",
    "colorado",
    "not primarily about colorado",
    "multiple",
    "various",
    "multiple/statewide",
    "n/a - national article",
    "not a colorado county",
})


def normalize_county(raw: str | None) -> str | None:
    """Normalize a raw county string to its canonical Colorado county name.

    Returns the canonical name (e.g. "Mesa") or None if the input is empty,
    junk, or does not match any known Colorado county.
    """
    if raw is None:
        return None

    cleaned = raw.strip()
    if not cleaned:
        return None

    lowered = cleaned.lower()

    if lowered in _JUNK_VALUES:
        return None

    # Strip " county" suffix if present
    if lowered.endswith(" county"):
        lowered = lowered[: -len(" county")]

    return _COUNTY_LOOKUP.get(lowered)
