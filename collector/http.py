"""A small, polite HTTP client: one session, per-site delay, robots.txt, retries."""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlsplit

import requests

from .robots import Robots

log = logging.getLogger(__name__)


def _user_agent() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "microbiome-faculty-jobs")
    return (
        f"microbiome-faculty-jobs/1.0 (+https://github.com/{repo}; "
        "open-access academic job tracker; checks once a day)"
    )


class PoliteClient:
    def __init__(self, delay_seconds: float = 1.5, timeout: tuple[float, float] = (10.0, 25.0)):
        self.delay = delay_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": _user_agent(),
                "Accept-Language": "en-US,en;q=0.8",
            }
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, Robots | None] = {}
        self.requests_made = 0
        self._speeds: dict[str, list[float]] = {}
        self._slow_warned: set[str] = set()

    # -- robots.txt -----------------------------------------------------------
    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rules: Robots | None = None
            try:
                resp = self.session.get(host + "/robots.txt", timeout=self.timeout)
                if resp.status_code < 400:
                    rules = Robots(resp.text)
                elif resp.status_code in (401, 403):
                    rules = Robots("User-agent: *\nDisallow: /")  # access refused: stay out
                # 404 and other client errors: no robots.txt, everything allowed
            except requests.RequestException:
                rules = None
            self._robots[host] = rules
        rules = self._robots[host]
        return True if rules is None else rules.can_fetch(self.session.headers["User-Agent"], url)

    def _note_speed(self, url: str, seconds: float) -> None:
        """Log once per site when it answers slowly, to make slow runs easy to explain."""
        host = urlsplit(url).netloc
        times = self._speeds.setdefault(host, [])
        times.append(seconds)
        if len(times) == 20 and sum(times) / 20 > 8 and host not in self._slow_warned:
            self._slow_warned.add(host)
            log.warning("%s is slow: %.1f s per page on average", host, sum(times) / 20)
        if len(times) > 20:
            del times[0]

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.delay:
                time.sleep(self.delay - gap)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, *, accept: str | None = None, retries: int = 2) -> requests.Response:
        """GET a URL. Raises FetchError when the site refuses or keeps failing."""
        if not self.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        headers = {"Accept": accept} if accept else {}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._wait(url)
            started = time.monotonic()
            try:
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
                self.requests_made += 1
            except requests.RequestException as exc:
                kind = "timed out" if isinstance(exc, requests.Timeout) else "could not connect"
                last_exc = FetchError(f"{kind} to {urlsplit(url).netloc} ({type(exc).__name__})")
                if attempt >= 1:
                    break  # one retry is enough for a site that isn't answering
                time.sleep(3)
                continue
            self._note_speed(url, time.monotonic() - started)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = FetchError(f"HTTP {resp.status_code} for {url}")
                wait = 5 * (attempt + 1)
                ra = resp.headers.get("Retry-After", "")
                if ra.isdigit():
                    wait = min(int(ra), 60)  # the site asked us to slow down
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            if _looks_blocked(resp):
                # Bot-protection page. We do not try to get around these.
                raise FetchError(f"blocked by bot protection at {urlsplit(url).netloc}")
            return resp
        raise FetchError(str(last_exc) if last_exc else f"failed to fetch {url}")


class FetchError(Exception):
    pass


def _looks_blocked(resp: requests.Response) -> bool:
    if len(resp.content) > 6000:
        return False
    body = resp.text.lower()
    return any(
        marker in body
        for marker in ("_incapsula_resource", "cf-chl-", "captcha", "access denied", "request unsuccessful")
    )
