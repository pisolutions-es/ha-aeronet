"""Tests for the HTTP retry/backoff behaviour of AeronetClient.

The host test environment has no aiohttp, so a minimal sys.modules stub
stands in: a scripted session whose responses/errors are popped per GET,
and an asyncio.sleep spy that records the backoff schedule.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest


# --- minimal aiohttp stub (installed before importing client) -------------
class _StubClientError(Exception):
    pass


class _StubResp:
    def __init__(self, status=200, body="", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise _StubClientError(f"HTTP {self.status}")

    async def text(self, errors="replace"):
        return self._body


class _StubSession:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def get(self, url, timeout=None, headers=None):
        self.requests.append(url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _install_stub():
    mod = types.ModuleType("aiohttp")
    mod.ClientError = _StubClientError
    mod.ClientSession = _StubSession
    mod.ClientTimeout = lambda **kw: None
    sys.modules["aiohttp"] = mod


_install_stub()

import os
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

import client as client_mod  # noqa: E402
from client import AeronetClient, _retry_after_seconds  # noqa: E402
from const import MAX_RETRIES, RETRY_AFTER_MAX  # noqa: E402
from parsers import AeronetError  # noqa: E402


class RetrySpy:
    """asyncio.sleep replacement recording requested delays."""

    def __init__(self):
        self.delays = []

    async def __call__(self, delay):
        self.delays.append(delay)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ClientRetryTests(unittest.TestCase):
    def setUp(self):
        self._real_sleep = asyncio.sleep
        self.spy = RetrySpy()
        asyncio.sleep = self.spy
        client_mod.random.random = lambda: 0.5  # deterministic jitter

    def tearDown(self):
        asyncio.sleep = self._real_sleep

    def _client(self, script):
        return AeronetClient(_StubSession(script))

    def test_success_first_try_no_sleep(self):
        c = self._client([_StubResp(body="ok")])
        out = _run(c._get_text("http://x"))
        self.assertEqual(out, "ok")
        self.assertEqual(self.spy.delays, [])

    def test_transient_error_uses_exponential_backoff_with_jitter(self):
        c = self._client([
            _StubClientError("boom"),
            _StubClientError("boom"),
            _StubResp(body="ok"),
        ])
        out = _run(c._get_text("http://x"))
        self.assertEqual(out, "ok")
        # RETRY_BACKOFF=5: 5*2^0+0.5, 5*2^1+0.5
        self.assertEqual(self.spy.delays, [5.5, 10.5])

    def test_retries_bounded(self):
        c = self._client([
            _StubClientError("boom"),
            _StubClientError("boom"),
            _StubClientError("boom"),
        ])
        with self.assertRaises(AeronetError):
            _run(c._get_text("http://x"))
        self.assertEqual(len(c._session.requests), MAX_RETRIES + 1)

    def test_429_honors_retry_after_seconds(self):
        c = self._client([
            _StubResp(status=429, headers={"Retry-After": "42"}),
            _StubResp(body="ok"),
        ])
        out = _run(c._get_text("http://x"))
        self.assertEqual(out, "ok")
        self.assertEqual(self.spy.delays, [42.0])

    def test_429_retry_after_is_clamped(self):
        c = self._client([
            _StubResp(status=429, headers={"Retry-After": "99999"}),
            _StubResp(body="ok"),
        ])
        _run(c._get_text("http://x"))
        self.assertEqual(self.spy.delays, [float(RETRY_AFTER_MAX)])

    def test_429_without_retry_after_falls_back_to_schedule(self):
        c = self._client([
            _StubResp(status=429),
            _StubResp(body="ok"),
        ])
        _run(c._get_text("http://x"))
        self.assertEqual(self.spy.delays, [10.5])  # 5*2^0*2 + jitter 0.5

    def test_429_on_last_attempt_raises(self):
        c = self._client([
            _StubResp(status=429), _StubResp(status=429),
            _StubResp(status=429),
        ])
        with self.assertRaises(AeronetError) as ctx:
            _run(c._get_text("http://x"))
        self.assertIn("429", str(ctx.exception))


class RetryAfterParsingTests(unittest.TestCase):
    def test_numeric(self):
        self.assertEqual(_retry_after_seconds("30"), 30.0)

    def test_bounded_and_floor(self):
        self.assertEqual(_retry_after_seconds("0"), 1.0)
        self.assertEqual(_retry_after_seconds("99999"), float(RETRY_AFTER_MAX))

    def test_garbage_falls_back_positive(self):
        for bad in (None, "Wed, 21 Oct 2026 07:28:00 GMT", ""):
            self.assertGreater(_retry_after_seconds(bad), 0.0)


if __name__ == "__main__":
    unittest.main()
