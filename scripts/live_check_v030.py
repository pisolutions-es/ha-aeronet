#!/usr/bin/env python3
"""Live v0.3.0 check: active site list (v3921) + Valladolid widened fetch.

Stdlib-only (urllib), mirroring the real code paths: parse_site_list on the
live v3921 file, URL builders with days=7 and days=30, parse_data_csv with
the site-mismatch guard, and payload_is_empty semantics.
"""
import datetime as dt
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet")
)

import parsers, urls  # noqa: E402
from const import (  # noqa: E402
    DATA_WINDOW_WIDE_DAYS,
    SITE_LIST_URL,
    SITE_LIST_URL_ALL,
    USER_AGENT,
)

# coordinators.py needs Home Assistant installed; mirror its emptiness check.
def payload_is_empty(data) -> bool:
    if data is None:
        return True
    if data.points:
        return False
    return not any(series for series in data.values.values())


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    print("now:", now.isoformat())

    # 1. Active site list (v3921), the new default source.
    assert SITE_LIST_URL.endswith("aeronet_locations_v3921.txt"), SITE_LIST_URL
    sites = parsers.parse_site_list(fetch(SITE_LIST_URL))
    names = [s.name for s in sites]
    print("active stations:", len(sites))
    assert len(sites) > 400, len(sites)
    assert "Valladolid" in names, "Valladolid missing from active list"
    assert all(n == n.strip() and " " not in n for n in names), "bad names"
    display = parsers.dedupe_display_names(sites)
    print("display options:", len(display), "(<=600:", len(display) <= 600, ")")
    assert len(display) <= 600

    # Sanity: the *full* list is still fetchable and larger.
    all_sites = parsers.parse_site_list(fetch(SITE_LIST_URL_ALL))
    print("full list stations:", len(all_sites))
    assert len(all_sites) > len(sites)

    # 2. Valladolid 7-day window, same builder the coordinator uses.
    url7 = urls.build_data_url("Valladolid", now, level="1.5")
    data7 = parsers.parse_data_csv(url7 and fetch(url7), expected_site="Valladolid")
    p7 = parsers.latest_point(data7)
    empty7 = payload_is_empty(data7)
    print("7d: points:", len(data7.points), "empty:", empty7)
    if p7:
        print("latest:", p7.time.isoformat(), p7.wavelength, round(p7.aod, 4),
              "24h mean:", parsers.mean_last_24h(data7))

    # 3. Widened request path (what the coordinator does when 7d is empty).
    url30 = urls.build_data_url("Valladolid", now, level="1.5",
                                days=DATA_WINDOW_WIDE_DAYS)
    assert "202" in url30  # sanity: start-year param present
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url30).query)
    start = dt.date(int(q["year"][0]), int(q["month"][0]), int(q["day"][0]))
    assert (now.date() - start).days == DATA_WINDOW_WIDE_DAYS - 1, start
    data30 = parsers.parse_data_csv(fetch(url30), expected_site="Valladolid")
    print("30d: points:", len(data30.points),
          "empty:", payload_is_empty(data30))

    assert not empty7, "Valladolid 7d unexpectedly empty (widening would kick in)"
    assert len(data30.points) >= len(data7.points) > 0
    print("LIVE v0.3.0 OK")


if __name__ == "__main__":
    main()
