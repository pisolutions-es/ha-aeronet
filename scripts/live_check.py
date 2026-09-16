"""Live end-to-end check: build URL the same way the client does, fetch, parse."""
import sys, os, urllib.request, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"))
import urls, parsers
from const import USER_AGENT

now = dt.datetime.now(dt.timezone.utc)
url = urls.build_data_url("Madrid", now, level="1.5")
print("URL:", url)
req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
body = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
data = parsers.parse_data_csv(body)
p = parsers.latest_point(data)
print("points:", len(data.points))
print("meta:", data.meta.name, data.meta.latitude, data.meta.longitude, data.meta.elevation)
print("latest:", p.time.isoformat(), p.wavelength, round(p.aod, 4))
print("24h mean:", parsers.mean_last_24h(data))
print("daily:", parsers.daily_series(data))
print("recent24:", len(parsers.recent_points(data, 24)))
assert len(data.points) > 0 and p.wavelength == "AOD_500nm"
print("LIVE OK")
