"""US state centroids (lat, lon) for the frame map model."""

US_STATES = {
    "AL": ("Alabama", 32.8, -86.8), "AK": ("Alaska", 64.0, -152.0),
    "AZ": ("Arizona", 34.2, -111.7), "AR": ("Arkansas", 34.9, -92.4),
    "CA": ("California", 37.2, -119.5), "CO": ("Colorado", 39.0, -105.5),
    "CT": ("Connecticut", 41.6, -72.7), "DE": ("Delaware", 39.0, -75.5),
    "DC": ("District of Columbia", 38.9, -77.0), "FL": ("Florida", 28.6, -82.4),
    "GA": ("Georgia", 32.7, -83.4), "HI": ("Hawaii", 20.8, -156.3),
    "ID": ("Idaho", 44.4, -114.6), "IL": ("Illinois", 40.0, -89.2),
    "IN": ("Indiana", 39.9, -86.3), "IA": ("Iowa", 42.1, -93.5),
    "KS": ("Kansas", 38.5, -98.4), "KY": ("Kentucky", 37.5, -85.3),
    "LA": ("Louisiana", 31.1, -92.0), "ME": ("Maine", 45.4, -69.2),
    "MD": ("Maryland", 39.0, -76.8), "MA": ("Massachusetts", 42.3, -71.8),
    "MI": ("Michigan", 44.3, -85.4), "MN": ("Minnesota", 46.3, -94.3),
    "MS": ("Mississippi", 32.7, -89.7), "MO": ("Missouri", 38.4, -92.5),
    "MT": ("Montana", 47.0, -109.6), "NE": ("Nebraska", 41.5, -99.8),
    "NV": ("Nevada", 39.3, -116.6), "NH": ("New Hampshire", 43.7, -71.6),
    "NJ": ("New Jersey", 40.2, -74.7), "NM": ("New Mexico", 34.4, -106.1),
    "NY": ("New York", 42.9, -75.5), "NC": ("North Carolina", 35.6, -79.4),
    "ND": ("North Dakota", 47.5, -100.5), "OH": ("Ohio", 40.3, -82.8),
    "OK": ("Oklahoma", 35.6, -97.5), "OR": ("Oregon", 43.9, -120.6),
    "PA": ("Pennsylvania", 40.9, -77.8), "RI": ("Rhode Island", 41.7, -71.5),
    "SC": ("South Carolina", 33.9, -80.9), "SD": ("South Dakota", 44.4, -100.2),
    "TN": ("Tennessee", 35.9, -86.4), "TX": ("Texas", 31.5, -99.3),
    "UT": ("Utah", 39.3, -111.7), "VT": ("Vermont", 44.1, -72.7),
    "VA": ("Virginia", 37.5, -78.9), "WA": ("Washington", 47.4, -120.5),
    "WV": ("West Virginia", 38.6, -80.6), "WI": ("Wisconsin", 44.6, -89.9),
    "WY": ("Wyoming", 43.0, -107.6),
}

_BY_NAME = {v[0].lower(): k for k, v in US_STATES.items()}


def us_state(value) -> tuple | None:
    """State name or code -> (code, lat, lon)."""
    s = str(value or "").strip()
    code = s.upper() if s.upper() in US_STATES else _BY_NAME.get(s.lower())
    if not code:
        return None
    _, lat, lon = US_STATES[code]
    return code, lat, lon


def project(lat: float, lon: float, w: float, h: float) -> tuple:
    """Lower 48 equirectangular into a w x h box; Alaska and Hawaii as insets bottom left."""
    if lon < -140:
        x, y = 0.08 + (lon + 170) / 40 * 0.15, 0.80 + (71 - lat) / 20 * 0.15
    elif lat < 23:
        x, y = 0.26 + (lon + 160) / 6 * 0.08, 0.88 + (22.5 - lat) / 4 * 0.08
    else:
        x, y = (lon + 125) / 59, (50 - lat) / 26
    return 8 + x * (w - 16), 8 + y * (h - 16)
