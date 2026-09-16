"""Constants for the NASA AERONET integration."""
from __future__ import annotations

DOMAIN = "aeronet"

SITE_LIST_URL = "https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt"
WEB_SERVICE_URL = "https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_v3"

USER_AGENT = (
    "home-assistant-aeronet/1.0 "
    "(NASA AERONET custom integration; +https://github.com/home-assistant/core)"
)

CONF_EMAIL = "email"
CONF_LEVEL = "level"
CONF_INTERVAL_MIN = "interval_min"
CONF_SITE = "site"

LEVELS = {"1.0": "AOD10", "1.5": "AOD15", "2.0": "AOD20"}

DEFAULT_LEVEL = "1.5"
DEFAULT_INTERVAL_MIN = 60
# Used only as the initial station selection until the user changes it
# through the select entity.
DEFAULT_SITE = "Madrid"

SITES_REFRESH_DAYS = 7
DATA_WINDOW_DAYS = 7

# Preferred AOD wavelengths, in order (primary documented in README).
AOD_WAVELENGTHS = ("AOD_500nm", "AOD_551nm", "AOD_555nm", "AOD_560nm")

REQUEST_TIMEOUT_TOTAL = 60
REQUEST_TIMEOUT_CONNECT = 15
MAX_RETRIES = 2
RETRY_BACKOFF = 5
