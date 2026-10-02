"""Behavior tests for integration constants (review m1).

The User-Agent is what NASA uses to identify clients: it must carry the
*installed* version and a repository URL the project actually owns.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

from custom_components.aeronet import const  # noqa: E402

COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "aeronet")


def _manifest() -> dict:
    with open(os.path.join(COMPONENT_DIR, "manifest.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


class TestUserAgent(unittest.TestCase):
    def test_version_matches_manifest(self):
        self.assertEqual(const.VERSION, _manifest()["version"])

    def test_user_agent_carries_manifest_version(self):
        self.assertIn(
            f"home-assistant-aeronet/{_manifest()['version']}",
            const.USER_AGENT,
        )

    def test_user_agent_points_at_the_project_repo(self):
        # v0.5.x advertised home-assistant/core: a URL the project does not
        # own, in an identification header NASA relies on.
        self.assertIn(const.REPO_URL, const.USER_AGENT)
        self.assertNotIn("home-assistant/core", const.USER_AGENT)

    def test_user_agent_is_a_single_header_safe_line(self):
        self.assertNotIn("\n", const.USER_AGENT)
        self.assertNotIn("\r", const.USER_AGENT)


if __name__ == "__main__":
    unittest.main()
