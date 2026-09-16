import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"))
import parsers

d = parsers.parse_data_csv(open(os.path.join(os.path.dirname(__file__), "..", "tests/fixtures/data_madrid.csv")).read())
p = parsers.latest_point(d)
print("latest:", p.time.isoformat(), p.wavelength, p.aod)
print("24h mean:", parsers.mean_last_24h(d, now=p.time))
print("daily:", parsers.daily_series(d))
print("meta:", d.meta.name, d.meta.latitude, d.meta.longitude, d.meta.elevation)
print("points:", len(d.points), "| recent24:", len(parsers.recent_points(d, 24)))
