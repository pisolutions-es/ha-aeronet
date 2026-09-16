"""Generate test fixtures from the real NASA responses captured during
exploration (kept truncated for test speed). Run from repo root:
    python3 scripts/make_fixtures.py ../.scratch/madrid.csv
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
os.makedirs(FIX, exist_ok=True)

# Fixture 1: truncated site list (real header lines + a few rows).
SITE_LIST = (
    "AERONET_Database_Site_List,Num=6,Date_Generated=16:09:2026\n"
    "Site_Name,Longitude(decimal_degrees),Latitude(decimal_degrees),Elevation(meters)\n"
    "Cuiaba,-56.070214,-15.555244,234.000000\n"
    "Barcelona,2.112060,41.389250,125.000000\n"
    "Evora,-7.911500,38.567833,293.000000\n"
    "Granada,-3.605000,37.164000,680.000000\n"
    "Madrid,-3.723950,40.451900,680.000000\n"
    "Tenerife,-16.633333,28.033333,52.000000\n"
)
with open(os.path.join(FIX, "site_list.txt"), "w") as f:
    f.write(SITE_LIST)

# Fixture 2: real Madrid AOD L1.5 CSV (meta lines + header + rows).
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    lines = open(sys.argv[1]).read().splitlines()
    header_i = next(i for i, l in enumerate(lines) if l.startswith("AERONET_Site,Date("))
    kept = lines[:header_i + 1] + lines[header_i + 1: header_i + 30]
    with open(os.path.join(FIX, "data_madrid.csv"), "w") as f:
        f.write("\n".join(kept) + "\n")
    print(f"captured {len(kept)} lines of real Madrid CSV")
else:
    print("usage: make_fixtures.py <path-to-real-madrid.csv>", file=sys.stderr)
    sys.exit(1)

# Fixture 3: real help HTML (error page when params are invalid).
import urllib.request  # noqa: E402  (dev-only script)

req = urllib.request.Request(
    "https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_v3",
    headers={"User-Agent": "fixture-builder"},
)
try:
    body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    with open(os.path.join(FIX, "help_error.html"), "w") as f:
        f.write(body)
    print("captured help HTML")
except Exception as err:  # pragma: no cover
    print(f"could not capture help HTML: {err}", file=sys.stderr)
