"""Geocoding with OpenStreetMap Nominatim, cached in data/geocache.json.

Nominatim's usage policy asks for at most 1 request/second, an identifying
User-Agent and caching of results; this module does all three. Only new
places are looked up, so a normal daily run makes a handful of requests.
"""

from __future__ import annotations

import json
import logging
import os
import time

import requests

from . import STATE_DIR
from .http import _user_agent
from .regions import country_name

log = logging.getLogger(__name__)
CACHE_FILE = STATE_DIR / "geocache.json"
NOMINATIM = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")


class Geocoder:
    def __init__(self, max_lookups: int = 250):
        self.cache: dict[str, dict | None] = {}
        if CACHE_FILE.exists():
            self.cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        self.max_lookups = max_lookups
        self.lookups = 0
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = _user_agent()
        email = os.environ.get("GEOCODER_EMAIL")
        self.params_extra = {"email": email} if email else {}

    def save(self) -> None:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self.cache, indent=0, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    def _query(self, q: str, country: str | None) -> dict | None:
        key = f"{q}|{country or ''}".lower()
        if key in self.cache:
            return self.cache[key]
        if self.lookups >= self.max_lookups or os.environ.get("OFFLINE"):
            return None
        wait = 1.1 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.lookups += 1
        params = {"q": q, "format": "jsonv2", "limit": 1, **self.params_extra}
        if country:
            params["countrycodes"] = country.lower()
        try:
            r = self.session.get(NOMINATIM, params=params, timeout=30)
            r.raise_for_status()
            hits = r.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("geocode failed for %r: %s", q, exc)
            return None  # don't cache failures; retry next run
        res = {"lat": round(float(hits[0]["lat"]), 5), "lon": round(float(hits[0]["lon"]), 5)} if hits else None
        self.cache[key] = res
        return res

    def locate(self, institution: str, city: str, region: str, country_code: str | None) -> dict | None:
        """Try the institution first, then the city, then the country."""
        cname = country_name(country_code)
        tries = []
        if institution:
            tries.append((", ".join(x for x in (institution, city, region) if x), "institution"))
            tries.append((institution, "institution"))
        if city:
            tries.append((", ".join(x for x in (city, region, cname) if x), "city"))
        if region:
            tries.append((", ".join(x for x in (region, cname) if x), "region"))
        if cname:
            tries.append((cname, "country"))
        for q, precision in tries:
            hit = self._query(q, country_code)
            if hit:
                return {**hit, "precision": precision}
        return None
