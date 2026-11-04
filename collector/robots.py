"""robots.txt rules, read the way Google documents them (RFC 9309).

Python's built-in urllib.robotparser ignores `*` and `$` wildcards, so a rule
like `Disallow: /unijobs/jobsrss/*` never matched and the feed was treated as
allowed. This parser supports:
  - groups for several user-agents, matched by product token (case-insensitive);
    the most specific group wins, otherwise `*`
  - `*` (any characters) and `$` (end of URL) in paths
  - longest matching rule wins; on a tie, Allow wins
  - Allow / Disallow with an empty path (= no rule)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str, re.Pattern]] = field(default_factory=list)  # (allow, path, regex)


def _compile(path: str) -> re.Pattern:
    anchored = path.endswith("$")
    if anchored:
        path = path[:-1]
    parts = [re.escape(p) for p in path.split("*")]
    return re.compile("".join(p if i == 0 else ".*" + p for i, p in enumerate(parts)) + ("$" if anchored else ""))


def _norm(path: str) -> str:
    # Compare unescaped paths so %2F-style differences don't matter.
    try:
        return unquote(path)
    except Exception:  # noqa: BLE001
        return path


class Robots:
    def __init__(self, text: str):
        self.groups: list[_Group] = []
        cur: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if cur is None or not last_was_agent:
                    cur = _Group()
                    self.groups.append(cur)
                cur.agents.append(val.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if cur is None or not val:
                    continue
                cur.rules.append((key == "allow", val, _compile(_norm(val))))
            else:
                last_was_agent = False  # sitemap, crawl-delay, content-signal, ...

    def _group_for(self, agent: str) -> list[_Group]:
        token = agent.lower().split("/")[0].strip()
        specific = [g for g in self.groups if any(a != "*" and a and token.startswith(a) for a in g.agents)]
        if specific:
            return specific
        return [g for g in self.groups if "*" in g.agents]

    def can_fetch(self, agent: str, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        path = _norm(path)
        if path == "/robots.txt":
            return True
        best: tuple[int, bool] | None = None
        for g in self._group_for(agent):
            for allow, raw, rx in g.rules:
                if rx.match(path):
                    length = len(raw.rstrip("$"))
                    if best is None or length > best[0] or (length == best[0] and allow):
                        best = (length, allow)
        return True if best is None else best[1]
