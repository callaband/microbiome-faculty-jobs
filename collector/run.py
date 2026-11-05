"""Entry point: python -m collector.run

Reads every enabled source, keeps microbiome faculty postings, merges them into
the history in docs/data/jobs.json and writes the files the website reads.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

import yaml

from . import CONFIG_DIR, SITE_DATA_DIR, STATE_DIR
from .classify import (domains, is_faculty_title, rank_label, ranks, relevance, taxonomy, tenure,
                       tenure_label)
from .dates import find_dates
from .effort import find_effort
from .institutions import TYPE_LABELS, Classifier, classify, load_directory
from .geo import Geocoder
from .http import FetchError, PoliteClient
from .regions import country_name, region_of
from .sources import Detail, Entry, build_sources
from .text import excerpt, jaccard, norm_tokens

log = logging.getLogger("collector")

JOBS_FILE = SITE_DATA_DIR / "jobs.json"
META_FILE = SITE_DATA_DIR / "meta.json"
CSV_FILE = SITE_DATA_DIR / "jobs.csv"
FEED_FILE = SITE_DATA_DIR.parent / "feed.xml"
CHECKED_FILE = STATE_DIR / "checked.json"      # postings we opened and rejected
SUBMITTED_FILE = STATE_DIR / "submitted_urls.txt"

SOON_DAYS = 14
_CLF: Classifier | None = None  # institution directory, loaded in run()
_DIR_VERSION = 0               # version of the directory that was loaded
KEEP_CLOSED_DAYS = 180


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _job_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _title_prefilter(src, title: str) -> bool:
    """Cheap check before opening a posting's page.

    Keyword-searched boards return few results, so only obvious non-faculty titles
    (postdoc, technician...) are skipped. HigherEdJobs category feeds list every job
    in a field, so there the title must already look like a faculty rank."""
    tx = taxonomy()
    if any(rx.search(title) for rx in tx["_exclude"]):
        return False
    if src.id == "higheredjobs" or getattr(src, "require_faculty_title", False):
        return is_faculty_title(title)[0]
    return True


# ----------------------------------------------------------------------------- building records
def build_record(entry: Entry, d: Detail, source_name: str, today: date, terms: list[str]) -> dict:
    title = d.title or entry.title
    text = d.description
    anchor = d.date_posted or entry.date_posted or today
    found = find_dates(text, anchor)
    deadline = d.application_due or found.deadline
    rs, ts = ranks(title, text), tenure(title, text)
    eff = find_effort(text)
    location = {
        "city": d.city,
        "region": d.region,
        "country_code": d.country_code,
        "country": country_name(d.country_code),
        "world_region": region_of(d.country_code),
    }
    inst = classify(d.employer or entry.employer, location, text, _CLF)
    if inst.get("lat") and inst.get("lon"):
        location.update(lat=round(inst["lat"], 5), lon=round(inst["lon"], 5), precision="institution")
    return {
        "id": _job_id(entry.url),
        "title": title,
        "institution": d.employer or entry.employer,
        **inst_fields(inst),
        "location": location,
        "url": entry.url,
        "sources": [{"id": entry.source_id, "name": source_name, "url": entry.url}],
        "ranks": rs,
        "rank_label": rank_label(rs),
        "tenure": ts,
        "tenure_label": tenure_label(ts),
        "domains": domains(title, text),
        "microbiome_terms": terms,
        "date_posted": _iso(anchor),
        "first_seen": today.isoformat(),
        "last_seen": today.isoformat(),
        "last_checked": today.isoformat(),
        "review_date": _iso(found.review_date),
        "review_text": found.review_text,
        "deadline": _iso(deadline),
        "deadline_text": found.deadline_text if not d.application_due else "Application due date listed on the posting.",
        "listing_expires": _iso(d.listing_expires),
        "until_filled": found.until_filled,
        "effort": eff["split"],
        "effort_label": eff["label"],
        "effort_text": eff["text"],
        "effort_focus": eff["focus"],
        "teaching_load": eff["teaching_load"],
        "employment": d.employment,
        "salary": d.salary,
        "board_job_type": d.job_type,
        "summary": excerpt(text),
    }


def inst_fields(inst: dict) -> dict:
    types = inst["types"]
    return {
        "inst_types": types,
        "inst_type_label": " · ".join(TYPE_LABELS.get(t, t) for t in types),
        "carnegie": inst.get("carnegie", ""),
        "control": inst.get("control", ""),
        "matched_institution": inst.get("matched_name", ""),
        "inst_version": _DIR_VERSION,
    }


def refresh_record(job: dict, fresh: dict) -> None:
    """Update dates/labels of a known posting from a fresh read, keeping history fields."""
    for k in ("title", "ranks", "rank_label", "tenure", "tenure_label", "domains", "microbiome_terms",
              "review_date", "review_text", "deadline", "deadline_text", "listing_expires", "until_filled",
              "employment", "salary", "board_job_type", "summary", "effort", "effort_label", "effort_text",
              "effort_focus", "teaching_load", "inst_types", "inst_type_label", "carnegie", "control",
              "matched_institution", "inst_version"):
        if fresh.get(k) not in (None, "", []):
            job[k] = fresh[k]
    job["last_checked"] = fresh["last_checked"]
    loc, floc = job.setdefault("location", {}), fresh["location"]
    if floc.get("city") and not loc.get("city"):
        job["location"] = {**floc, **{k: v for k, v in loc.items() if k in ("lat", "lon", "precision")}}


def refresh_job(src, job: dict, entry: Entry, today: date) -> tuple[bool, str]:
    """Re-read a known posting's page. A page that is gone (404/410) closes the job."""
    try:
        d = src.fetch_detail(entry)
    except FetchError as exc:
        gone = bool(re.search(r"HTTP (404|410)\b", str(exc)))
        if gone:
            job["removed_on"] = today.isoformat()
        log.info("refresh failed %s: %s", entry.url, exc)
        return gone, str(exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not re-read %s: %r", entry.url, exc)
        return False, f"could not read page ({type(exc).__name__})"
    job.pop("removed_on", None)
    refresh_record(job, build_record(entry, d, src.name, today, job["microbiome_terms"]))
    return True, ""


def find_duplicate(rec: dict, jobs: dict[str, dict]) -> dict | None:
    """Same job posted on two boards: same place (city or institution) and near-identical title."""
    tt = norm_tokens(rec["title"])
    city = (rec["location"].get("city") or "").lower()
    inst = norm_tokens(rec["institution"] or "")
    for job in jobs.values():
        if job.get("status") == "closed" and job.get("closed_reason") != "not seen recently":
            continue
        same_place = (city and city == (job["location"].get("city") or "").lower()) or \
                     (inst and jaccard(inst, norm_tokens(job.get("institution") or "")) >= 0.6)
        if same_place and jaccard(tt, norm_tokens(job["title"])) >= 0.7:
            return job
    return None


# ----------------------------------------------------------------------------- status & priority
def assess(job: dict, today: date, stale_days: int) -> None:
    review, deadline, expires = _d(job.get("review_date")), _d(job.get("deadline")), _d(job.get("listing_expires"))
    last_seen = _d(job["last_seen"])
    closed_reason = None
    if job.get("removed_on"):
        closed_reason = "listing removed"
    elif deadline and deadline < today:
        closed_reason = "deadline passed"
    elif (today - last_seen).days > stale_days:
        closed_reason = "not seen recently"
    elif expires and expires < today and (today - last_seen).days > 1:
        closed_reason = "listing expired"
    job["status"] = "closed" if closed_reason else "open"
    job["closed_reason"] = closed_reason

    if review and review < today:
        job["priority"], job["priority_reason"] = "low", f"Review began {_fmt(review)} — application may be too late"
    elif review and (review - today).days <= SOON_DAYS:
        job["priority"], job["priority_reason"] = "soon", f"Review begins {_fmt(review)}"
    elif deadline and (deadline - today).days <= SOON_DAYS:
        job["priority"], job["priority_reason"] = "soon", f"Deadline {_fmt(deadline)}"
    else:
        job["priority"], job["priority_reason"] = "normal", ""


# ----------------------------------------------------------------------------- outputs
def write_outputs(jobs: list[dict], meta: dict) -> None:
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    jobs.sort(key=lambda j: j.get("first_seen") or "", reverse=True)
    jobs.sort(key=lambda j: j["status"] != "open")
    JOBS_FILE.write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
    res = CONFIG_DIR / "resources.yaml"
    if res.exists():
        (SITE_DATA_DIR / "resources.json").write_text(
            json.dumps(yaml.safe_load(res.read_text(encoding="utf-8")), indent=1, ensure_ascii=False), encoding="utf-8")
    META_FILE.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")

    cols = ["status", "title", "institution", "institution_type", "carnegie", "control", "city", "region", "country",
            "rank", "tenure", "effort", "teaching_load", "domains", "review_date", "deadline", "priority",
            "date_posted", "first_seen", "url"]
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for j in jobs:
            loc = j["location"]
            w.writerow([j["status"], j["title"], j["institution"], j.get("inst_type_label", ""), j.get("carnegie", ""),
                        j.get("control", ""), loc.get("city"), loc.get("region"), loc.get("country"),
                        j["rank_label"], j["tenure_label"], j.get("effort_label", ""), j.get("teaching_load", ""),
                        "; ".join(j["domains"]),
                        j.get("review_date") or "", j.get("deadline") or "", j["priority"],
                        j.get("date_posted") or "", j["first_seen"], j["url"]])

    site = meta.get("site_url", "")
    now = meta["generated_at"]
    entries = []
    for j in [j for j in jobs if j["status"] == "open"][:100]:
        loc = ", ".join(x for x in (j["location"].get("city"), j["location"].get("country")) if x)
        summary = f"{j['institution']} — {loc}. {j['rank_label']}; {j['tenure_label']}."
        if j.get("review_date"):
            summary += f" Review begins {j['review_date']}."
        entries.append(
            f"<entry><title>{escape(j['title'])} — {escape(j['institution'] or '')}</title>"
            f"<link href=\"{escape(site + 'job.html?id=' + j['id'] if site else j['url'])}\"/>"
            f"<id>urn:mfj:{j['id']}</id><updated>{j['first_seen']}T00:00:00Z</updated>"
            f"<summary>{escape(summary)}</summary></entry>"
        )
    FEED_FILE.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>Microbiome Faculty Jobs — new positions</title>"
        f"<link href=\"{escape(site)}\"/><id>urn:mfj:feed</id><updated>{now}</updated>"
        + "".join(entries) + "</feed>\n",
        encoding="utf-8",
    )


def _merge_health(new: list[dict], old: list[dict], enabled: set[str]) -> list[dict]:
    """Keep last-known status for enabled sources not run this time (e.g. with --only);
    drop sources that have been switched off."""
    seen = {s["id"] for s in new}
    return new + [s for s in old if s.get("id") not in seen and s.get("id") in enabled]


# ----------------------------------------------------------------------------- main
def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated source ids to run")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
    ap.add_argument("--sources", default=str(CONFIG_DIR / "sources.yaml"), help="sources config file")
    ap.add_argument("--max-details", type=int, default=None, help="cap on posting pages opened this run")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with open(args.sources, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    settings = cfg.get("settings", {})
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    refresh_days = int(settings.get("refresh_days", 7))
    stale_days = int(settings.get("stale_days", 10))
    max_details = args.max_details or int(settings.get("max_detail_fetches", 2000))
    taxonomy()  # fail fast on a bad config
    global _CLF, _DIR_VERSION
    dir_info, dir_rows = load_directory(offline=bool(os.environ.get("OFFLINE")))
    _CLF = Classifier(dir_rows)
    _DIR_VERSION = dir_info.get("version", 1) if dir_rows else 0

    jobs: dict[str, dict] = {j["id"]: j for j in _load_json(JOBS_FILE, [])}
    url_index = {s["url"]: j["id"] for j in jobs.values() for s in j["sources"]}
    checked: dict[str, dict] = _load_json(CHECKED_FILE, {})
    submitted = []
    if SUBMITTED_FILE.exists():
        submitted = [ln.strip() for ln in SUBMITTED_FILE.read_text(encoding="utf-8").splitlines()
                     if ln.strip().startswith("http")]

    client = PoliteClient(delay_seconds=float(settings.get("delay_seconds", 1.5)))
    only = set(args.only.split(",")) if args.only else None
    health, rejected_submissions = [], []
    details_opened = 0

    run_start = time.monotonic()
    run_limit = float(settings.get("max_minutes", 90)) * 60       # whole run, before saving
    default_src_limit = float(settings.get("source_minutes", 20)) * 60
    max_fail_streak = int(settings.get("max_failures_in_a_row", 8))

    for src in build_sources(cfg, client, submitted):
        if only and src.id not in only:
            continue
        stat = {"id": src.id, "name": src.name, "ok": True, "listed": 0, "new_matches": 0, "error": None,
                "pages_opened": 0, "note": None,
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if time.monotonic() - run_start > run_limit:
            stat.update(ok=False, error="skipped this run: the run's time limit was reached (it runs again tomorrow)")
            health.append(stat)
            continue
        t0 = time.monotonic()
        src_limit = float(src.cfg.get("max_minutes", 0)) * 60 if getattr(src, "cfg", None) else 0
        src_deadline = t0 + min(src_limit or default_src_limit, max(60.0, run_limit - (t0 - run_start)))
        if hasattr(src, "known_urls"):
            src.known_urls = set(url_index)
        fails = {"streak": 0, "last": ""}

        def opened(ok: bool, err: str = "") -> None:
            stat["pages_opened"] += 1
            if ok:
                fails["streak"] = 0
            else:
                fails["streak"] += 1
                fails["last"] = err
            if stat["pages_opened"] % 50 == 0:
                log.info("%s: %d pages opened, %d new, %.1f min", src.id, stat["pages_opened"],
                         stat["new_matches"], (time.monotonic() - t0) / 60)

        def must_stop() -> str | None:
            if fails["streak"] >= max_fail_streak:
                return f"stopped after {fails['streak']} failed requests in a row (last: {fails['last']})"
            if time.monotonic() > src_deadline:
                return "time"
            return None

        try:
            try:
                entries = src.list_entries()
            except FetchError as exc:
                stat.update(ok=False, error=str(exc))
                log.warning("%s: %s", src.id, exc)
                continue
            stat["listed"] = len(entries)
            stop = None
            for e in entries:
                stop = must_stop()
                if stop:
                    break
                known_id = url_index.get(e.url)
                if known_id:
                    job = jobs[known_id]
                    job["last_seen"] = today.isoformat()
                    if (today - _d(job["last_checked"])).days >= refresh_days and details_opened < max_details:
                        details_opened += 1
                        opened(*refresh_job(src, job, e, today))
                    continue
                if e.url in checked:
                    continue
                if e.title and not _title_prefilter(src, e.title):
                    continue  # obviously not a faculty job; don't open its page
                if details_opened >= max_details:
                    continue  # picked up on the next run
                details_opened += 1
                try:
                    d = src.fetch_detail(e)
                except FetchError as exc:
                    gone = bool(re.search(r"HTTP (404|410)\b", str(exc)))
                    opened(gone, str(exc))  # a missing page is an answer, not a failure
                    log.info("detail failed %s: %s", e.url, exc)
                    if src.id == "submitted":
                        rejected_submissions.append({"url": e.url, "why": str(exc)})
                    continue
                except Exception as exc:  # noqa: BLE001 - a page we can't parse shouldn't stop the run
                    opened(False, f"could not read page ({type(exc).__name__})")
                    log.warning("could not read %s: %r", e.url, exc)
                    continue
                opened(True)
                rel = relevance(d.title or e.title, d.description, d.job_type, d.employment)
                if not rel.keep:
                    if getattr(src, "remember_rejects", True):
                        checked[e.url] = {"on": today.isoformat(), "why": rel.reason}
                    if src.id == "submitted":
                        rejected_submissions.append({"url": e.url, "why": rel.reason})
                    continue
                rec = build_record(e, d, src.name, today, rel.terms)
                dup = find_duplicate(rec, jobs)
                if dup:
                    if not any(s["url"] == e.url for s in dup["sources"]):
                        dup["sources"].append(rec["sources"][0])
                    dup["last_seen"] = today.isoformat()
                    for k in ("review_date", "review_text", "deadline", "deadline_text"):
                        if rec.get(k) and not dup.get(k):
                            dup[k] = rec[k]
                    url_index[e.url] = dup["id"]
                    continue
                jobs[rec["id"]] = rec
                url_index[e.url] = rec["id"]
                stat["new_matches"] += 1
                log.info("NEW  %s — %s", rec["title"], rec["institution"])
            if getattr(src, "partial_listing", False) and not stop:
                # The source lists only its newest jobs: keep older ones open until their
                # deadline, and re-check their pages weekly so withdrawn ones close.
                listed = {e.url for e in entries}
                for job in jobs.values():
                    for srec in job["sources"]:
                        if srec["id"] != src.id or srec["url"] in listed or job.get("status") == "closed":
                            continue
                        job["last_seen"] = today.isoformat()
                        if (today - _d(job["last_checked"])).days >= refresh_days and details_opened < max_details \
                                and not must_stop():
                            details_opened += 1
                            opened(*refresh_job(src, job, Entry(src.id, srec["url"], job["title"]), today))
            if stop == "time":
                stat["note"] = "paused at its time limit; continues on the next run"
                log.warning("%s: time limit reached after %d pages; continuing next run", src.id, stat["pages_opened"])
            elif stop:
                stat.update(ok=False, error=stop)
                log.warning("%s: %s", src.id, stop)
        except Exception as exc:  # noqa: BLE001 - one broken reader must not stop the others
            stat.update(ok=False, error=f"internal error: {type(exc).__name__}: {exc}"[:300])
            log.exception("%s failed", src.id)
        finally:
            if hasattr(src, "finish"):
                try:
                    src.finish()
                except Exception:  # noqa: BLE001
                    log.exception("%s: could not save progress", src.id)
            stat["seconds"] = round(time.monotonic() - t0, 1)
            if stat not in health:
                health.append(stat)

    # Records classified with an older directory (or never): classify again from what we kept.
    for job in jobs.values():
        if job.get("inst_version") != _DIR_VERSION and _CLF and _CLF.available:
            name = job.get("matched_institution") or job.get("institution") or ""
            job.update(inst_fields(classify(name, job["location"], job.get("summary", ""), _CLF)))

    # Geocode, assess, prune.
    geo = Geocoder(max_lookups=int(settings.get("max_geocodes", 250)),
                   deadline=time.monotonic() + max(180.0, run_limit + 600 - (time.monotonic() - run_start)))
    for job in jobs.values():
        loc = job["location"]
        if loc.get("lat") is None and job.get("status") != "closed":
            hit = geo.locate(job.get("institution") or "", loc.get("city") or "", loc.get("region") or "",
                             loc.get("country_code"))
            if hit:
                loc.update(lat=hit["lat"], lon=hit["lon"], precision=hit["precision"])
        assess(job, today, stale_days)
    geo.save()
    cutoff = today - timedelta(days=KEEP_CLOSED_DAYS)
    kept = [j for j in jobs.values() if j["status"] == "open" or _d(j["last_seen"]) >= cutoff]
    old = (today - timedelta(days=365)).isoformat()
    checked = {u: v for u, v in checked.items() if v["on"] >= old}
    CHECKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKED_FILE.write_text(json.dumps(checked, indent=0, sort_keys=True), encoding="utf-8")

    tx = taxonomy()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner, _, name = repo.partition("/")
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "repo": repo,
        "site_url": f"https://{owner.lower()}.github.io/{name}/" if repo else "",
        "counts": {
            "open": sum(1 for j in kept if j["status"] == "open"),
            "closed": sum(1 for j in kept if j["status"] == "closed"),
            "new_this_run": sum(s["new_matches"] for s in health),
        },
        "domains": {k: {"label": v["label"], "color": v["color"]} for k, v in tx["domains"].items()},
        "sources": _merge_health(health, _load_json(META_FILE, {}).get("sources", []),
                                 {x["id"] for x in cfg.get("sources", []) if x.get("enabled", True)} | {"submitted"}),
        "rejected_submissions": rejected_submissions,
        "institution_directory": dir_info.get("source", "not available"),
        "inst_type_labels": TYPE_LABELS,
        "requests_made": client.requests_made,
        "geocode_lookups": geo.lookups,
    }
    write_outputs(kept, meta)
    log.info("done: %d open, %d closed, %d requests, %d geocodes", meta["counts"]["open"],
             meta["counts"]["closed"], client.requests_made, geo.lookups)
    return 0


if __name__ == "__main__":
    sys.exit(run())
