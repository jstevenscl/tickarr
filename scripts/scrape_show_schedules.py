#!/usr/bin/env python3
"""
Scrape SiriusXM's public per-channel schedule pages to build a rich,
real weekly show schedule for the satellite radio EPG.

Complements build_sports_epg.py, which handles the ~124 team/league
play-by-play channels via game events. This script covers the other
~381 named channels (music, talk, news, comedy, etc.) that otherwise
only ever get a single generic 24h fill block in the EPG — no real
show names or air times at all.

Runs on its OWN cadence — daily, not the 4-hourly cadence used for
sports. A channel's weekly show lineup doesn't change nearly as often
as a game schedule (which needs frequent re-checks for rain delays,
overtime, etc.). This script does not touch the sports pipeline.

Output: lib/show_schedules.json — per-channel list of
  {show_name, start_utc, end_utc} covering however many days out
  SiriusXM's own schedule page reaches (observed: ~5-7 days).
  Channels with no page, a failed fetch, or no schedule data simply
  don't appear in the output — the EPG generator's existing 24h
  generic-fill logic covers the gap for those, and for anything past
  the last real scraped day within the fill window. This is a
  deliberate fallback design: a scrape failure never breaks the EPG,
  it just silently falls back to today's existing behavior for that
  channel/window.

Run manually:
  python scripts/scrape_show_schedules.py

Not yet wired into a GitHub Actions workflow — see NOT YET DONE notes
in _workshop/current.md for remaining integration steps.
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
CHANNELS_JSON = ROOT / "lib" / "channels.json"
OUT_JSON = ROOT / "lib" / "show_schedules.json"

UA = "Tickarr-ShowScheduleEPG/1.0 (github.com/jstevenscl/tickarr)"
CHANNELS_LIST_URL = "https://www.siriusxm.com/channels"

FETCH_DELAY_SECONDS = 1.5  # politeness delay between per-channel fetches


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def discover_channel_slugs(html: str) -> list[str]:
    """
    Extract every /channels/{slug} reference from the main listing page's
    embedded vanityURL fields (Next.js RSC data, not plain <a href> links
    — those undercount; vanityURL is the authoritative per-channel field
    and was confirmed against channels.json to cover the full real set).
    """
    vals = re.findall(r'vanityURL\\":\\"([^\\]*)\\"', html)
    slugs = set()
    for v in vals:
        m = re.match(r"/channels/([a-z0-9\-]+)$", v)
        if m:
            slugs.add(m.group(1))
    return sorted(slugs)


def extract_shows(html: str) -> list[dict]:
    """
    Extract {show_name, program_id, channel_id, show_schedules} for every
    show on one channel page. The page embeds this via Next.js RSC
    streaming chunks (self.__next_f.push(...)) — not valid JSON on its
    own (React's Flight wire format uses $D for dates and $L/$N-style
    backreferences elsewhere), but each show's show_schedules array is
    well-formed once unescaped, so we extract it with manual
    bracket-matching rather than parsing the whole page as one document.
    """
    shows = []
    for m in re.finditer(r'\\"show_name\\":\\"([^\\]*)\\"', html):
        show_name = m.group(1)
        start = m.end()

        pid_m = re.match(r',\\"program_id\\":(\d+)', html[start:start + 60])
        program_id = int(pid_m.group(1)) if pid_m else None

        sched_m = re.search(r',\\"show_schedules\\":\[', html[start:start + 200])
        if not sched_m:
            continue
        arr_start = start + sched_m.end() - 1  # position of the opening [

        depth, i = 0, arr_start
        while i < len(html):
            if html[i] == "[":
                depth += 1
            elif html[i] == "]":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            continue  # malformed/truncated — skip rather than guess

        raw_arr = html[arr_start:i + 1]
        unescaped = raw_arr.replace('\\"', '"').replace("\\\\", "\\")
        unescaped = re.sub(r'"\$D', '"', unescaped)  # strip React Flight date prefix

        tail = html[i + 1:i + 120]
        ch_m = re.search(r'\\"channel_id\\":\\"([^\\"]*)\\"', tail)
        channel_id = ch_m.group(1) if ch_m else None

        try:
            schedules = json.loads(unescaped)
        except json.JSONDecodeError as e:
            print(f"    [skip] failed to parse show_schedules for {show_name!r}: {e}", file=sys.stderr)
            continue

        shows.append({
            "show_name": show_name,
            "program_id": program_id,
            "channel_id": channel_id,
            "show_schedules": schedules,
        })
    return shows


def dedupe_shows(shows: list[dict]) -> list[dict]:
    """
    Same show can appear multiple times on a page (lineup card, schedule
    dropdown, on-air-now strip, etc.) — keep the richest (most non-empty
    day_schedules) copy per program_id.
    """
    best: dict = {}
    for s in shows:
        key = s["program_id"] if s["program_id"] is not None else hash(s["show_name"])
        richness = sum(len(d.get("day_schedules", [])) for d in s["show_schedules"])
        if key not in best or richness > best[key]["_richness"]:
            s["_richness"] = richness
            best[key] = s
    out = list(best.values())
    for s in out:
        del s["_richness"]
    return out


def flatten_to_slots(shows: list[dict]) -> list[dict]:
    """[{show_name, show_schedules:[{date, day_schedules:[...]}]}] -> flat
    list of {show_name, start_utc, end_utc}."""
    slots = []
    for s in shows:
        for day in s["show_schedules"]:
            for slot in day.get("day_schedules", []):
                start = slot.get("start_time")
                end = slot.get("end_time")
                if not start or not end:
                    continue
                slots.append({
                    "show_name": s["show_name"],
                    "start_utc": start,
                    "end_utc": end,
                })
    return slots


def load_entity_id_to_name() -> dict:
    """Reverse-map channels.json's sxm_entity_id -> channel display name.
    Confirmed this field matches the scraped channel_id exactly across
    all formats seen (string slugs, numeric IDs, and Xtra-channel UUIDs)."""
    data = json.loads(CHANNELS_JSON.read_text(encoding="utf-8"))
    mapping = {}
    for v in data.values():
        eid = v.get("sxm_entity_id")
        name = v.get("name")
        if eid and name:
            mapping[eid] = name
    return mapping


def scrape(slugs: list[str], entity_map: dict, delay: float = FETCH_DELAY_SECONDS,
           limit: Optional[int] = None):
    """Fetch + parse each channel page. Returns (channel_name -> slots, stats)."""
    if limit:
        slugs = slugs[:limit]

    all_channel_shows: dict = {}
    stats = {"ok": 0, "failed": 0, "unmapped": 0, "no_data": 0}

    for i, slug in enumerate(slugs, 1):
        url = f"https://www.siriusxm.com/channels/{slug}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  [{i}/{len(slugs)}] FAILED {slug}: {e}", file=sys.stderr)
            stats["failed"] += 1
            time.sleep(delay)
            continue

        shows = dedupe_shows(extract_shows(html))
        if not shows:
            stats["no_data"] += 1
            time.sleep(delay)
            continue

        by_channel: dict = {}
        for s in shows:
            by_channel.setdefault(s["channel_id"], []).append(s)

        for channel_id, ch_shows in by_channel.items():
            ch_name = entity_map.get(channel_id)
            if not ch_name:
                stats["unmapped"] += 1
                continue
            slots = flatten_to_slots(ch_shows)
            all_channel_shows.setdefault(ch_name, []).extend(slots)
            stats["ok"] += 1

        if i % 25 == 0:
            print(f"  [{i}/{len(slugs)}] ...")
        time.sleep(delay)

    return all_channel_shows, stats


def main():
    print("Fetching channel listing page...")
    listing_html = fetch(CHANNELS_LIST_URL)
    slugs = discover_channel_slugs(listing_html)
    print(f"  {len(slugs)} channel slugs discovered")

    entity_map = load_entity_id_to_name()
    print(f"  {len(entity_map)} channels in channels.json with an sxm_entity_id")

    limit = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        limit = int(sys.argv[1])
        print(f"  LIMIT={limit} (test run)")

    all_channel_shows, stats = scrape(slugs, entity_map, limit=limit)

    print(f"Done: {stats['ok']} channels mapped, {stats['failed']} fetch failures, "
          f"{stats['no_data']} pages with no show data, "
          f"{stats['unmapped']} channel_ids with no channels.json match")

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channels": all_channel_shows,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written: {OUT_JSON}  ({len(all_channel_shows)} channels)")


if __name__ == "__main__":
    main()
