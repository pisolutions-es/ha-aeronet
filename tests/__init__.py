import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# v0.6.0 (review m2): the integration is imported as a package everywhere, so
# even the stdlib-only modules (parsers/urls/site_cache) pull in the package
# __init__ and need the HA stubs installed before any test module imports them.
# ha_stubs.install() is additive and idempotent; individual test files calling
# it again is harmless.
from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()
