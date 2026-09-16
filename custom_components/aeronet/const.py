"""Constants for the NASA AERONET integration."""
from __future__ import annotations

DOMAIN = "aeronet"

SITE_LIST_URL = "https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt"
WEB_SERVICE_URL = "https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_v3"
INVERSION_WEB_SERVICE_URL = (
    "https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_inv_v3"
)

USER_AGENT = (
    "home-assistant-aeronet/1.0 "
    "(NASA AERONET custom integration; +https://github.com/home-assistant/core)"
)

CONF_EMAIL = "email"
CONF_LEVEL = "level"
CONF_INTERVAL_MIN = "interval_min"
CONF_SITE = "site"
CONF_PRODUCTS = "products"

LEVELS = {"1.0": "AOD10", "1.5": "AOD15", "2.0": "AOD20"}

# Inversion web-service retrieval type per data level. AERONET publishes V3
# inversions only at Level 1.5 (ALM15) and 2.0 (ALM20); Level 1.0 requests use
# ALM15 (there is no Level 1.0 inversion product).
INVERSION_LEVELS = {"1.0": "ALM15", "1.5": "ALM15", "2.0": "ALM20"}

# Selectable AERONET products (config flow multiselect, default ["AOD"]).
# Direct-sun data types per level (verified against the web service help page;
# note products CANNOT be combined in one direct-sun request — each family
# needs its own GET): https://aeronet.gsfc.nasa.gov/print_web_data_help_v3_new.html
# SSA/VOL are inversion products requested from print_web_data_inv_v3 with
# product=SSA|VOL: https://aeronet.gsfc.nasa.gov/print_web_data_help_v3_inv_new.html
PRODUCT_AOD = "AOD"
PRODUCT_SDA = "SDA"
PRODUCT_SSA = "SSA"
PRODUCT_VOL = "VOL"
PRODUCTS = (PRODUCT_AOD, PRODUCT_SDA, PRODUCT_SSA, PRODUCT_VOL)
PRODUCTS_INVERSION = (PRODUCT_SSA, PRODUCT_VOL)
DEFAULT_PRODUCTS = [PRODUCT_AOD]

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
