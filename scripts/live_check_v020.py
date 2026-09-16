#!/usr/bin/env python3
"""Live Valladolid verification: v0.2.0 product data, today series, daily means."""

import asyncio
import datetime as dt
import logging
import os
import sys

# Add custom components to path
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

from client import AeronetClient  # noqa: E402

logging.basicConfig(level=logging.INFO)


async def test_valladolid_v020() -> None:
    """Test Valladolid site with all v0.2.0 products."""
    site = "Valladolid"
    email = ""
    client = AeronetClient()
    client.configure(email=email)

    results = {}

    # AOD all-points + today series
    try:
        aod_data = await client.fetch_all(site, level="1.5", days_back=7)
        results["aod"] = f"{len(aod_data.points)} points"
        if aod_data.points:
            latest = aod_data.points[-1]
            results["aod_latest"] = f"{latest.aod:.4f} @ {latest.time}"
        
        # Today series from same data
        today = dt.datetime.now(dt.timezone.utc).date()
        today_pts = [p for p in aod_data.points if p.time.date() == today]
        results["today_series_count"] = len(today_pts)
        if today_pts:
            results["today_first"] = f"{today_pts[0].time.strftime('%H:%M')} UTC"
            results["today_last"] = f"{today_pts[-1].time.strftime('%H:%M')} UTC"
    except Exception as e:
        results["aod"] = f"ERROR: {e}"

    # AOD daily averages
    try:
        daily_data = await client.fetch_daily(site, level="1.5", days_back=7)
        results["daily"] = f"{len(daily_data.points)} days"
        if daily_data.points:
            today_daily = [p for p in daily_data.points 
                          if p.time.date() == dt.date.today()]
            if today_daily:
                results["today_daily"] = f"{today_daily[0].aod:.4f} (partial)"
    except Exception as e:
        results["daily"] = f"ERROR: {e}"

    # SDA Fine/Coarse
    try:
        sda_data = await client.fetch_sda(site, level="1.5", days_back=7)
        sda_fine = sda_data.values.get("sda_fine", [])
        sda_coarse = sda_data.values.get("sda_coarse", [])
        results["sda_fine"] = f"{len(sda_fine)} points" if sda_fine else "empty"
        results["sda_coarse"] = f"{len(sda_coarse)} points" if sda_coarse else "empty"
        if sda_fine:
            results["sda_fine_latest"] = f"{sda_fine[-1].aod:.4f}"
        fmf = sda_data.meta.extras.get("fine_mode_fraction")
        if fmf:
            results["fine_mode_fraction"] = f"{len(fmf)} wavelengths"
    except Exception as e:
        results["sda"] = f"ERROR: {e}"

    # SSA inversion
    try:
        ssa_data = await client.fetch_ssa(site, level="1.5", days_back=7)
        ssa_pts = ssa_data.values.get("ssa", [])
        results["ssa"] = f"{len(ssa_pts)} points" if ssa_pts else "empty"
        if ssa_pts:
            results["ssa_latest"] = f"{ssa_pts[-1].aod:.4f} @ {ssa_pts[-1].wavelength}"
    except Exception as e:
        results["ssa"] = f"ERROR: {e}"

    # VOL inversion
    try:
        vol_data = await client.fetch_vol(site, level="1.5", days_back=7)
        vol_pts = vol_data.values.get("vol", [])
        results["vol"] = f"{len(vol_pts)} points" if vol_pts else "empty"
        if vol_pts:
            results["vol_latest"] = f"{vol_pts[-1].aod:.2f} µm³/cm³"
    except Exception as e:
        results["vol"] = f"ERROR: {e}"

    print(f"=== {site} v0.2.0 Live Check ===")
    for k, v in results.items():
        print(f"{k:20s}: {v}")


if __name__ == "__main__":
    asyncio.run(test_valladolid_v020())