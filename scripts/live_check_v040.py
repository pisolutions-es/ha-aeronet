#!/usr/bin/env python3
"""Live v0.4.0 check: multispectral channels for Valladolid (real NASA data).

Stdlib-only (urllib), mirroring the real code paths: fetch_data-equivalent
URL + parse_data_csv with channel_families=("aod",), then prints the
detected channels with the last value and the 7-day mean of each, and
sanity-checks the means against the official AERONET Valladolid September
AOD(λ) plot (approx 0.105/0.096/0.086/0.077/0.058/0.049/0.041/0.030 at
340/380/440/500/675/870/1020/1640 nm).
"""
import datetime as dt
import os
import sys
import urllib.request

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet")
)

import parsers, urls  # noqa: E402
from const import DATA_WINDOW_DAYS, USER_AGENT  # noqa: E402

# Official AERONET Valladolid Level 1.5 September climatology (approx.,
# from the NASA AERONET site browse plot; used only as a loose sanity band).
OFFICIAL_7D_MEANS = {
    340: 0.105, 380: 0.096, 440: 0.086, 500: 0.077,
    675: 0.058, 870: 0.049, 1020: 0.041, 1640: 0.030,
}
# Loose band: recent days can sit well below a monthly climatology.
SANITY_RATIO_MIN, SANITY_RATIO_MAX = 0.15, 2.5


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    print("now:", now.isoformat())

    url = urls.build_data_url("Valladolid", now, level="1.5",
                              days=DATA_WINDOW_DAYS)
    data = parsers.parse_data_csv(
        fetch(url),
        expected_site="Valladolid",
        column_sets={"aod": parsers.AOD_COLUMNS},
        channel_families=("aod",),
    )
    channels = parsers.detect_channels(data)
    print(f"points: {len(data.points)}  channels detected: {len(channels)}")
    print("main channel (existing sensor):",
          data.meta.extras.get("main_channel_aod"))

    print(f"\n{'channel':>12} {'n':>5} {'last':>9} {'7d mean':>9} "
          f"{'official':>9}  ratio")
    ok_sanity = True
    for ch in channels:
        series = data.values[ch]
        last = series[-1].aod
        mean = sum(p.aod for p in series) / len(series)
        nm = parsers.channel_nm(ch)
        official = OFFICIAL_7D_MEANS.get(nm)
        if official is None:
            print(f"{parsers.channel_label(ch):>12} {len(series):>5} "
                  f"{last:>9.4f} {mean:>9.4f}")
            continue
        ratio = mean / official
        flag = "" if SANITY_RATIO_MIN <= ratio <= SANITY_RATIO_MAX else " <-- OUT OF BAND"
        if flag:
            ok_sanity = False
        print(f"{parsers.channel_label(ch):>12} {len(series):>5} "
              f"{last:>9.4f} {mean:>9.4f} {official:>9.3f}  {ratio:>5.2f}{flag}")

    # Cross-checks
    assert channels and channels[0] == "aod_340nm", channels
    assert "aod_1640nm" in channels, channels
    assert parsers.channel_nm("aod_500nm") == 500
    mains = {data.meta.extras.get("main_channel_aod")}
    active = parsers.active_channels(channels, None)
    exposed = [c for c in active if c not in mains]
    assert "aod_500nm" not in exposed, "main channel must not duplicate"
    print(f"\nchannel sensors created: {len(exposed)} (500nm excluded: "
          f"it stays the main 'AOD' sensor)")
    assert all(p.aod >= 0 for s in data.values.values() for p in s)
    print("sanity vs official Sept means:", "OK" if ok_sanity else "SEE FLAGS")
    print("LIVE OK" if ok_sanity else "LIVE CHECK: channels fine, means flagged")


if __name__ == "__main__":
    main()
