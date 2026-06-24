#!/usr/bin/env python3
"""
Build lib/channels.json from StellarTunerLog (primary) or Rebrowser CSV (fallback).

StellarTunerLog fetches channel data directly from SiriusXM's API and is the
authoritative source for Tickarr. The Rebrowser public CSV is used as a fallback
if STL is unreachable.

Run manually:
  python scripts/build_channels_sxm.py

Called automatically by .github/workflows/update-channels.yml on a weekly schedule.
"""

import csv
import io
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

ROOT        = Path(__file__).parent.parent
OUT_PATH    = ROOT / "lib" / "channels.json"
ALIASES_PATH = ROOT / "lib" / "channel_aliases.json"

STL_CHANNELS_URL  = "https://stellartunerlog.com/channels.json"
REBROWSER_CSV_URL = "https://raw.githubusercontent.com/rebrowser/siriusxm-dataset/main/channels/data.csv"
UA = "Tickarr/1.0 (github.com/jstevenscl/tickarr)"

_SEASONAL_RE = re.compile(
    r"(holiday|christmas|xmas|halloween|thanksgiving|seasonal|limited edition"
    r"|fallon|country christmas|christmas spirit|billboard \d{4})",
    re.IGNORECASE,
)


def _load_existing() -> dict:
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_aliases() -> dict:
    try:
        raw = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
        return {k.lower(): v for k, v in raw.items()}
    except Exception:
        return {}


def _is_seasonal(name: str) -> bool:
    return bool(_SEASONAL_RE.search(name))


def _clean_name(name: str) -> str:
    return unicodedata.normalize("NFC", name.replace("’", "'").replace("‘", "'")).strip()


def fetch_stl():
    """Fetch channel list from StellarTunerLog (primary source — live SiriusXM API data)."""
    try:
        req = urllib.request.Request(STL_CHANNELS_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        channels = data.get("channels", {})
        if isinstance(channels, dict) and channels:
            print(f"  STL: {len(channels)} channels (updated {data.get('updated_utc', 'unknown')})")
            return channels
    except Exception as e:
        print(f"  STL fetch failed: {e}")
    return None


def build_from_stl(stl_channels: dict, existing: dict, aliases: dict) -> dict:
    """Build channels.json from STL data."""
    out = {}
    for entry in stl_channels.values():
        name = _clean_name(entry.get("name") or "")
        if not name:
            continue

        canonical = aliases.get(name.lower(), name)
        key = canonical.lower()

        desc = (
            entry.get("long_description")
            or entry.get("medium_description")
            or entry.get("description")
            or ""
        ).strip()

        genre = (entry.get("primary_genre") or "").strip()
        ch_num = entry.get("channel_number") or entry.get("xm_number") or entry.get("sirius_number")
        entity_id = str(entry.get("id") or "")
        guid = entry.get("guid") or None

        # Prefer STL-hosted logo (already proxied from SiriusXM)
        logo_url = entry.get("logo_square_url") or entry.get("logo_url") or ""

        # Preserve existing logo if STL has none
        if not logo_url:
            logo_url = (existing.get(key) or {}).get("logo_url", "")

        seasonal = True if _is_seasonal(name) else None

        if key in out:
            key = f"{key}_{ch_num}" if ch_num else f"{key}_{entity_id}"

        out[key] = {
            "name":                  canonical,
            "description":           desc,
            "genre":                 genre,
            "sxm_number":            ch_num,
            "seasonal":              seasonal,
            "logo_url":              logo_url,
            "sxm_logo_src":          (existing.get(key) or {}).get("sxm_logo_src", ""),
            "sxm_entity_id":         entity_id,
            "lookaround_channel_id": guid,
        }

    return out


def fetch_rebrowser():
    """Fetch Rebrowser public SiriusXM CSV (fallback source)."""
    try:
        req = urllib.request.Request(REBROWSER_CSV_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(raw)))
        print(f"  Rebrowser fallback: {len(rows)} rows")
        return rows
    except Exception as e:
        print(f"  Rebrowser fetch failed: {e}")
    return None


_SXM_GENERIC_RE = re.compile(r"^SiriusXM \d+$")
_DYNAMIC_RE = re.compile(
    r"^(NFL|MLB|NBA|NHL|NCAA|ACC|Big\s+1[02]|Big\s+Ten|SEC|Sports|College)\s+Play.{0,20}\d+$",
    re.IGNORECASE,
)


def build_from_rebrowser(rows: list, existing: dict, aliases: dict) -> dict:
    """Build channels.json from Rebrowser CSV (fallback)."""
    out = {}
    seen_numbers = set()

    for row in rows:
        raw_name = row.get("name", "").strip()
        if not raw_name:
            continue
        cleaned = _clean_name(raw_name)
        if _SXM_GENERIC_RE.match(cleaned):
            continue

        ch_str = row.get("streamingChannelNumber", "").strip()
        ch = int(ch_str) if ch_str.isdigit() else None
        if ch is None and _DYNAMIC_RE.match(cleaned):
            continue

        canonical = aliases.get(cleaned.lower(), cleaned)
        key = canonical.lower()

        if ch is not None:
            if ch in seen_numbers:
                continue
            seen_numbers.add(ch)

        desc = (row.get("longDescription") or row.get("shortDescription") or "").strip()
        genre = row.get("genreName", "").strip()
        entity_id = row.get("channelId", "").strip()
        existing_ch = existing.get(key) or {}
        logo_url = existing_ch.get("logo_url", "")
        seasonal = True if _is_seasonal(canonical) else None

        if key in out:
            key = f"{key}_{ch}" if ch else key

        out[key] = {
            "name":                  canonical,
            "description":           desc,
            "genre":                 genre,
            "sxm_number":            ch,
            "seasonal":              seasonal,
            "logo_url":              logo_url,
            "sxm_logo_src":          existing_ch.get("sxm_logo_src", ""),
            "sxm_entity_id":         entity_id,
            "lookaround_channel_id": existing_ch.get("lookaround_channel_id"),
        }

    return out


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing()
    aliases  = _load_aliases()

    print("Building channels.json...")

    stl = fetch_stl()
    if stl:
        channels = build_from_stl(stl, existing, aliases)
        source = "STL (SiriusXM API via StellarTunerLog)"
    else:
        print("  Falling back to Rebrowser dataset...")
        rows = fetch_rebrowser()
        if not rows:
            print("ERROR: both STL and Rebrowser failed — channels.json unchanged")
            return
        channels = build_from_rebrowser(rows, existing, aliases)
        source = "Rebrowser CSV (fallback)"

    with_nums = sum(1 for v in channels.values() if v.get("sxm_number") is not None)
    with_logo = sum(1 for v in channels.values() if v.get("logo_url"))
    seasonal  = sum(1 for v in channels.values() if v.get("seasonal"))
    print(f"  {len(channels)} channels, {with_nums} with numbers, {with_logo} with logos, {seasonal} seasonal")
    print(f"  Source: {source}")

    OUT_PATH.write_text(json.dumps(channels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written: {OUT_PATH}")


if __name__ == "__main__":
    main()
