"""Live regression check for the trailing-space site bug (v0.1.1).

Requests data for 'Valladolid ' (WITH a trailing space, simulating the
production bug) through the same code path the integration uses
(build_data_url -> fetch -> parse_data_csv with expected_site) and confirms:
  * the outgoing URL carries the clean 'Valladolid' (no %20/+),
  * the payload validates as site=Valladolid,
  * coordinates match Valladolid (~41.66, -4.70), not Tucson.
"""
import sys, os, urllib.request, datetime as dt
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"))
import urls, parsers
from const import USER_AGENT

dirty_site = "Valladolid "
now = dt.datetime.now(dt.timezone.utc)

# Mirror client.AeronetClient.fetch_data: strip, build URL, fetch, validate.
site = dirty_site.strip()
url = urls.build_data_url(dirty_site, now, level="1.5")  # dirty input on purpose
query_site = parse_qs(urlparse(url).query)["site"][0]
print("requested (dirty):", repr(dirty_site))
print("site param sent  :", repr(query_site))
assert query_site == "Valladolid", f"URL still carries a dirty site: {url}"
assert "%20" not in url and "+" not in url.split("?", 1)[1], f"URL has encoded space: {url}"

req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
body = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
data = parsers.parse_data_csv(body, expected_site=site)  # raises on mismatch/multi-site
print("parsed site      :", data.meta.name)
print("lat/lon          :", round(data.meta.latitude, 4), round(data.meta.longitude, 4))
print("point_count      :", len(data.points))
assert data.meta.name == "Valladolid", f"wrong site returned: {data.meta.name!r}"
assert 40 < data.meta.latitude < 43 and -6 < data.meta.longitude < -3, "coordinates are not Valladolid"
assert len(data.points) < 5000, f"absurd point_count: {len(data.points)}"

# And confirm the guard actually fires on the old (buggy) request shape:
# same URL but with the trailing space left in the site parameter.
bad_url = url.replace("site=Valladolid&", "site=Valladolid%20&")
req = urllib.request.Request(bad_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
bad_body = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
try:
    parsers.parse_data_csv(bad_body, expected_site="Valladolid")
    print("WARNING: guard did NOT fire on the raw spaced request")
except (parsers.AeronetSiteMismatchError, parsers.AeronetParamError) as err:
    print(f"guard on raw spaced request: raised {type(err).__name__} -> {str(err)[:70]}")

print("LIVE OK")
