"""Config flow for the NASA AERONET integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .const import (
    CONF_CHANNELS,
    CONF_EMAIL,
    CONF_INTERVAL_MIN,
    CONF_LEVEL,
    CONF_PRODUCTS,
    CONF_SITE,
    CONF_SITE_LIST_URL,
    DEFAULT_INTERVAL_MIN,
    DEFAULT_LEVEL,
    DEFAULT_PRODUCTS,
    DEFAULT_SITE,
    DOMAIN,
    ENTRY_VERSION,
    LEVELS,
    PRODUCTS,
    SITE_LIST_URL,
    SITE_LIST_URL_OPTIONS,
)
from .coordinators import get_sites_coordinator, detected_channels
from .parsers import (
    _canonical_site,
    channel_label,
    dedupe_display_names,
    display_to_site_name,
)

_LOGGER = logging.getLogger(__name__)

# Sentinel option in the channels multi-select meaning "all channels
# detected in the data". Empty string can never collide with a channel id;
# it is normalized away on save (absent CONF_CHANNELS = all channels).
ALL_CHANNELS = ""
ALL_CHANNELS_LABEL = "All channels (default)"


def _channels_default(cur: dict) -> list[str]:
    """Selection the dialog opens with (v0.5.1, review M1).

    An entry with no explicit CONF_CHANNELS used to be prefilled with every
    channel detected in the current payload: saving untouched then FROZE the
    set (a wavelength the station starts reporting later would never get an
    entity) and tripped a reload + fetch burst. The sentinel keeps "absent =
    all" intact instead.
    """
    explicit = list(cur.get(CONF_CHANNELS) or [])
    return explicit or [ALL_CHANNELS]


def _channels_options(hass, entry) -> list[dict]:
    """Sentinel + channel ids currently fetched for this station."""
    return [{"value": ALL_CHANNELS, "label": ALL_CHANNELS_LABEL}] + \
        _channel_options(hass, entry)


def _normalize_saved(user_input: dict) -> dict:
    """Normalize saved options (v0.5.1, review M1).

    The untouched-sentinel selection (and an empty selection) is dropped so
    CONF_CHANNELS stays ABSENT: the update listener then compares [] against
    the setup snapshot [] and no-op saves never refetch, while "all" keeps
    tracking the channels the station reports over time.
    """
    saved = dict(user_input)
    channels = [c for c in saved.get(CONF_CHANNELS) or [] if c != ALL_CHANNELS]
    if not channels:
        saved.pop(CONF_CHANNELS, None)
    else:
        saved[CONF_CHANNELS] = channels
    return saved


def _site_options(hass, url: str = SITE_LIST_URL) -> list[str] | None:
    """Deduped station display names from the cache, or None if not loaded."""
    try:
        coord = get_sites_coordinator(hass, async_get_clientsession(hass),
                                       url=url)
        sites = coord.data
    except Exception:  # pragma: no cover - defensive
        return None
    if sites:
        return dedupe_display_names(sites)
    return None


def _unique_id_site(unique_id: str) -> str:
    """Station name encoded in an entry unique_id ("aeronet_<site>")."""
    prefix = "aeronet_"
    return unique_id[len(prefix):] if unique_id.startswith(prefix) else ""


def site_already_configured(hass, site: str) -> bool:
    """True when an existing entry already targets this station.

    v0.6.0 (review m6): AERONET station matching is case/underscore-
    insensitive (_canonical_site), yet the config flow used to store the
    raw cased name in the unique_id — `aeronet_Madrid` and `aeronet_MADRID`
    could both be created and would poll the identical station in
    parallel. Entries created before v0.6.0 keep their legacy cased
    unique_id (no migration needed: this check compares canonically, so
    the duplicate is still caught at flow time).
    """
    want = _canonical_site(site)
    try:
        entries = hass.config_entries.async_entries(DOMAIN)
    except AttributeError:  # flow scaffolding without a config_entries
        return False
    return any(
        bool(uid := getattr(entry, "unique_id", "") or "")
        and _canonical_site(_unique_id_site(uid)) == want
        for entry in entries
    )


class AeronetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = ENTRY_VERSION

    # v0.6.0 (review m3): the static ``async_migrate_entry`` delegation that
    # used to live here is gone — HA core only ever invokes the module-level
    # handler in __init__.py; a shadowing method on the flow class invited
    # edits to a handler that is never called.

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            # Display labels may carry a dedupe coordinate suffix; AERONET
            # only accepts the exact station name.
            site = display_to_site_name(user_input.get(CONF_SITE) or DEFAULT_SITE)
            user_input = {**user_input, CONF_SITE: site}
            if not user_input.get(CONF_PRODUCTS):
                user_input[CONF_PRODUCTS] = list(DEFAULT_PRODUCTS)
            await self.async_set_unique_id(f"aeronet_{_canonical_site(site)}")
            self._abort_if_unique_id_configured()
            # Legacy entries store the raw cased site in their unique_id;
            # compare canonically so aeronet_Madrid blocks aeronet_MADRID.
            if site_already_configured(self.hass, site):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(title=f"AERONET · {site}", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=self._user_schema(self.hass)
        )

    @staticmethod
    def _user_schema(hass) -> vol.Schema:
        options = _site_options(hass)
        site_field: Any
        if options:
            site_field = selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, sort=True, mode="dropdown")
            )
        else:
            # Site list not fetched yet: plain text (validated in options flow /
            # runtime; an unknown site shows as a parameter error on first poll).
            site_field = selector.TextSelector()
        return vol.Schema(
            {
                vol.Optional(CONF_SITE, default=DEFAULT_SITE): site_field,
                vol.Optional(CONF_EMAIL, default=""): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
                ),
                vol.Required(CONF_LEVEL, default=DEFAULT_LEVEL): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(LEVELS.keys()))
                ),
                vol.Required(CONF_INTERVAL_MIN, default=DEFAULT_INTERVAL_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=1440, step=10, unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_PRODUCTS, default=list(DEFAULT_PRODUCTS)): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(PRODUCTS),
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                ),
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AeronetOptionsFlow(config_entry)


class AeronetOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Tweak email/level/interval after setup (station changes via select).

    v0.6.0 (review m7): OptionsFlowWithConfigEntry replaces the deprecated
    ``OptionsFlow.__init__(config_entry)`` pattern (deprecated in HA
    2024.11); the entry is available as ``self.config_entry``.
    """

    async def async_step_init(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=_normalize_saved(user_input))
        cur = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EMAIL, default=cur.get(CONF_EMAIL, "")): str,
                    vol.Required(
                        CONF_LEVEL, default=cur.get(CONF_LEVEL, DEFAULT_LEVEL)
                    ): vol.In(list(LEVELS.keys())),
                    vol.Required(
                        CONF_INTERVAL_MIN,
                        default=cur.get(CONF_INTERVAL_MIN, DEFAULT_INTERVAL_MIN),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=1440)),
                    vol.Optional(
                        CONF_PRODUCTS,
                        default=list(cur.get(CONF_PRODUCTS) or DEFAULT_PRODUCTS),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(PRODUCTS),
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        CONF_CHANNELS,
                        # v0.5.1 (M1): do NOT prefill every detected channel
                        # when the entry has no explicit selection — that
                        # froze the set on first save and broke the no-op
                        # guarantee. The sentinel keeps "absent = all".
                        default=_channels_default(cur),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_channels_options(self.hass,
                                                      self.config_entry),
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        CONF_SITE_LIST_URL,
                        default=cur.get(CONF_SITE_LIST_URL, SITE_LIST_URL),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(SITE_LIST_URL_OPTIONS.keys()),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )


def _channel_options(hass, entry) -> list[dict]:
    """Channel ids currently fetched for this station (dynamic, from data).

    Before the first successful poll the list is empty; saving an empty
    selection means "all channels detected in the data" (documented in
    README), which is also the default for fresh and migrated entries.
    """
    try:
        store = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        data = store["data"].data if store else None
    except Exception:  # pragma: no cover - defensive
        return []
    if data is None:
        return []
    return [
        {"value": c, "label": channel_label(c)}
        for c in detected_channels(data)
    ]
