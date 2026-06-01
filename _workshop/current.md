# Tickarr — Working Notes
**Status: Phase 1 WORKING ✓ | Phase 2 Custom Text WORKING ✓ | Phase 3 Sports Ticker WORKING ✓**
**Last updated: 2026-06-01**

---

## Project Name
**Tickarr** (renamed from Tickerr/Tickarr in planning — directory was Tickerr, now Tickarr)
Follows *arr ecosystem naming: Tick + arr. Lives in the Dispatcharr plugin registry.

---

## What It Is
A Dispatcharr plugin that injects dynamic text overlays into IPTV stream channels via FFmpeg
`drawtext` filter. Three modes, built in this order:

1. **SiriusXM Now Playing** — auto-maps Dispatcharr channels to stellartunerlog.com, shows artist/song/channel in a centered box overlay. *Working.*
2. **Custom Text** — user-defined static or scrolling text message per channel.
3. **Sports Ticker** — live scores from ESPN API, scrolling ticker at top or bottom.

---

## Related Projects (local)
- `C:\Projects\epgeditarr` — live Dispatcharr plugin, provides the architecture template AND the channel data we use
- `C:\Projects\scorestream-pro` — ScorecastARR, provides the sports data fetching logic to reuse

---

## PII Policy
**Never** include real Dispatcharr URLs, IPs, or usernames in screenshots, docs, or any publishable content. Use placeholder data (e.g. `http://dispatcharr.local`, `192.168.x.x`, `admin`).

---

## Confirmed Architecture

### Plugin System
- Dispatcharr 0.25.1 (current on dispatch2)
- Python class named `Plugin` with `fields` list, `actions` list, `run(action, params, context)`, `stop(context)`
- **No frontend assets** — Dispatcharr renders the settings UI entirely from the `fields` JSON schema
- `run()` returns `{"success": True/False, "message": "..."}` — message shown verbatim in UI result panel
- Long operations can push live progress via `from core.utils import send_websocket_update`
- Settings persistence: `PluginConfig.objects.filter(key="tickarr").first().settings` — JSON blob in Django DB
- Plugin runs **inside** Dispatcharr's Django process — imports ORM models directly, no HTTP API calls to Dispatcharr needed
- ORM imports must be **deferred inside methods** (not at module top level) to avoid import-time errors

### Key ORM Imports (deferred inside methods)
```python
from core.models import StreamProfile
from apps.channels.models import Channel, ChannelStream
from apps.plugins.models import PluginConfig
from core.utils import send_websocket_update
```

### Field Schema Types
| type | description |
|---|---|
| `boolean` | toggle |
| `text` / `string` | text input |
| `number` | numeric input (use `min` for floor) |
| `select` | dropdown, `options: [{"value": "...", "label": "..."}]` |
| `info` | non-input section divider/header (use `id` starting with `_`) |

Action extras: `"confirm": {"message": "..."}` shows a confirmation dialog before `run()` is called.
Dynamic fields: build in `__init__()` by querying ORM — useful for per-channel configuration rows.

### FFmpeg Profile Management
`StreamProfile` model fields:
- `id` — primary key
- `name` — display name
- `command` — the binary/script path (e.g. `/usr/bin/ffmpeg`)
- `parameters` — the argument string (this is where `-vf drawtext=...` lives)
- `locked` — bool
- `is_active` — bool

**drawtext goes into `parameters`, not `command`.**

Pattern: clone profile → inject `drawtext` into `parameters` string → save new profile → assign to channel → on disable: restore original profile ID + delete clone.

The original profile is **never modified** — always clone. Store mapping in file:
`/data/plugins/tickarr_data/mappings.json`
```json
{
  "123": {
    "original_profile_id": 5,
    "ticker_profile_id": 47,
    "xm_deeplink": "firstwave",
    "channel_name": "1st Wave",
    "channel_description": "...",
    "type": "nowplaying"
  }
}
```
**NOTE:** `xm_deeplink` now stores the stellartunerlog.com `id` (e.g. "firstwave"), NOT the old xmplaylist deeplink slug (e.g. "1stwave"). These are different. The bridge: `deeplink_id.lower()` in stellartunerlog channels.json = old xmplaylist slug.

### Background Polling
Two loops running as daemon threads:
- **Fast loop** (2s tick): scans Redis for newly active streams, polls them immediately on stream-start
- **Sweep loop** (15s tick): polls all currently active channels; falls back to all channels if Redis unavailable

No per-channel rate limiter — stellartunerlog.com is a bulk fetch (one request covers all 437 channels).

Always call `connection.close()` in a `finally` block after any ORM query in a background thread — Django does not auto-close thread-local DB connections outside of request/response cycle.

### Redis Active Stream Detection
**Dispatcharr v0.25+:** `live:channel:{UUID}:activity`
**Dispatcharr v0.24:** `ts_proxy:channel:{UUID}:activity`
**Always scan both patterns** — union the results. Channel identifier is a UUID, not an integer. Map UUID → integer channel ID via `Channel.objects.filter(id__in=...)` using the `uuid` field. Cache this map for 5 minutes.

Redis runs **inside** the `dispatcharr` Docker container (no separate redis container).

### File Storage
```
/data/plugins/tickarr_data/
  tickers/          ← symlink → ../tickarr_0_1_82_data/tickers (see Current State note)
  mappings.json
  channel_cache.json
  station_cache.json

/data/plugins/tickarr_0_1_82_data/   ← actual data dir for current install
  tickers/
    channel_{id}_header.txt      # "♫ Now Playing ♫"
    channel_{id}_artist.txt      # "Fleetwood Mac"
    channel_{id}_song.txt        # "\"Go Your Own Way\""
    channel_{id}_channel.txt     # "Classic Rewind"
  mappings.json
  channel_cache.json
  station_cache.json
```
Atomic writes: write to `.tmp` then `os.replace()` — prevents FFmpeg reading partial content.
FFmpeg reads via `textfile=/path/file.txt:reload=30` (every ~1.2s at 25fps).

### FFmpeg Overlay (Audio-Only Channels)
SiriusXM channels are audio-only. Tickarr injects a lavfi black video background + drawtext:
```python
lavfi = '-f lavfi -i "color=c=black:s=1280x720:r=25"'
filter_complex = '[1:v]{drawtext}[vout]'
# maps: [vout] + 0:a:0
# codec: libx264 -preset ultrafast -tune zerolatency -crf 28
```
25fps is required — TiviMate won't play 1fps streams (changed in v0.1.20, do not revert).
1280x720 required for font quality — 640x360 causes pixelated upscaled text (tried in v0.1.45, reverted in v0.1.47).

### Font Sizes (1280x720)
```
header:  fontsize=36, y=(h/2-100), white, bold
artist:  fontsize=56, y=(h/2-20),  #00d4ff, bold
song:    fontsize=48, y=(h/2+60),  white
channel: fontsize=32, y=(h/2+130), #888888
```

---

## SiriusXM / Now Playing Architecture

### Data Source: stellartunerlog.com
Primary source switched from xmplaylist.com to stellartunerlog.com in v0.1.81.

**nowplaying.json** — `https://stellartunerlog.com/nowplaying.json`
- Bulk fetch: one request covers all 437 channels, 30s cache
- Top-level: `{"updated_utc": "...", "poll_interval_seconds": 30, "station_count": 437, "stations": {...}}`
- Stations dict keyed by stellartunerlog `id` (e.g. "firstwave", "hotjamz", "9585")
- Station fields: `id`, `name`, `channel_number`, `title`, `artist`, `album`, `cut_type`, `artwork_url`
- `cut_type` values: "Song" → show artist/title; "talk"/"Spot"/"Promo"/"Exp"/"Perm"/"PGM_Segment"/"Link" → show "On Air"

**channels.json** — `https://stellartunerlog.com/channels.json`
- 24h disk cache → `station_cache.json`
- Station fields: `id`, `guid` (SiriusXM UUID), `name`, `deeplink_id` (CamelCase), `channel_number`
- **KEY RELATIONSHIP:** `deeplink_id.lower()` = old xmplaylist deeplink slug. Bridge for migration.

### xmplaylist.com (fallback only)
```
GET https://xmplaylist.com/api/station/{deeplink}
  → returns [{track: {title, artists}, ...}]
```
- Only fires when stellartunerlog.com bulk response is available but a specific channel is missing
- Rate limited to 1.5s minimum between requests
- Returns 403 for most channels now (IP-level blocking) — rarely useful

### Channel Matching in mappings.json
`xm_deeplink` stores the **stellartunerlog `id`** (e.g. "firstwave" for 1st Wave).
- 423 channels have valid stellartunerlog IDs → get live now-playing data
- 23 channels have no deeplink (seasonal holiday channels: Christmas Spirit, Holly, Holiday Pops, etc. — SiriusXM only activates these at certain times of year)
- Sports/talk channels (Anaheim Ducks, VSiN, BBC World Service, etc.) have numeric STL IDs and get "On Air" overlay since stellartunerlog sends no artist/song for them

### EPGeditARR Channel Data
Tickarr also fetches channel UUID catalog from GitHub Pages for name→UUID matching:
```
https://jstevenscl.github.io/epgeditarr/channels.json
https://jstevenscl.github.io/epgeditarr/channel_aliases.json
```
7-day TTL, cached to `channel_cache.json`. No dependency on EPGeditARR being installed.

### Enable Action
Enable Now Playing: clones stream profile, writes fallback text, stores stellartunerlog ID as `xm_deeplink`. Does NOT call stellartunerlog during enable — sweep loop fetches live data within 15 seconds.

---

## Current Version: 0.1.82 (on GitHub master — dev/testing build)

### Official Public Version
- **GitHub Release tag:** v0.1.0 (the clean reset)
- **Dispatcharr/Plugins PR:** https://github.com/Dispatcharr/Plugins/pull/96 — open, awaiting review
- **Next official release:** v0.1.01 — after testing confirms v0.1.82 works correctly

### Current Dispatcharr Install State (dispatch2)
Plugin installed as UNMANAGED `tickarr_0_1_82` (versioned directory due to import-while-managed bug).
- Plugin code: `/data/plugins/tickarr_0_1_82/`
- Data dir: `/data/plugins/tickarr_0_1_82_data/` (mappings, caches, tickers)
- Symlink: `/data/plugins/tickarr_data/tickers` → `../tickarr_0_1_82_data/tickers`
  (stream profiles hardcode `tickarr_data/tickers` path; symlink redirects FFmpeg reads to new data dir)
- DB key: `tickarr_0_1_82` (NOT `tickarr` — `_get_settings()` won't find saved UI settings until next full reinstall)
- mappings.json: migrated — all 423 xm_deeplink values are now stellartunerlog IDs

### Actions in plugin.json
- **── SiriusXM Now Playing ──**: enable_nowplaying, disable_nowplaying
- **── Custom Text ──**: enable_custom, update_custom, disable_custom
- **── Sports Ticker ──**: enable_sports, disable_sports
- **── Manage ──**: view_active, refresh_channels, disable_all, clean_orphans, redis_diag, reload_poller, restart_dispatcharr

### Version History (key fixes)
- **0.1.43** — Fixed Redis key format (UUID-based activity keys), global rate lock
- **0.1.44** — Fixed DB connection leak (connection.close() in finally block), removed ThreadPoolExecutor
- **0.1.46** — Fixed 504 timeout on enable (removed API call from enable action)
- **0.1.48** — Fixed Redis key prefix for Dispatcharr v0.25.0 (live: vs ts_proxy:), dual-pattern scan
- **0.1.50** — Phase 2: Custom Text overlay
- **0.1.57** — Phase 3: Sports Ticker — ESPN API, 23 leagues, NASCAR live feed
- **0.1.62** — Fixed color layer sync: pipe separator + ljust() normalization
- **0.1.63–0.1.66** — Logo strip attempts abandoned. FFmpeg FIFO blocks on open; static PNG can't update live.
- **0.1.67** — Reverted to clean 3-layer drawtext
- **0.1.73** — Fixed A/V sync on audio-only channels (-tune zerolatency, -c:a copy)
- **0.1.75** — Fixed buffering: reload=30 (was 1), -max_interleave_delta 1
- **0.1.76** — Fixed all-I-frame explosion from -force_key_frames stripping
- **0.1.79** — Fixed scroll jump: _TICKER_FIXED_LEN=600, constant text_w across reloads
- **0.1.81** — Switched now-playing from xmplaylist.com to stellartunerlog.com bulk fetch
- **0.1.82** — Fix `_match_station_by_name` using wrong field `deeplink` (should be `deeplink_id` + `id`); fix `API_MIN_INTERVAL` NameError in `_redis_diag`; add `cut_type` filter (non-song shows "On Air"); add xmplaylist.com per-channel fallback when STL bulk is up but channel missing

---

## Testing Approach
Install plugin ZIP via Dispatcharr web UI. No local Docker required.
After plugin update: use **Restart Dispatcharr** action in Tickarr (no SSH/Portainer needed).

### Plugin Update Workflow — CRITICAL
**Always use the UPDATE button on the existing managed Tickarr card.** Do NOT delete + reimport.
- Importing a ZIP while a managed version exists creates a versioned directory (e.g. `tickarr_0_1_82`) instead of `tickarr`
- This changes the data directory path, breaking all mappings/cache; requires SSH data migration + symlinks
- The plugin.json `version` field drives the versioned directory name on unmanaged imports
- After import, full `docker restart dispatcharr` is cleaner than SIGHUP to kill zombie threads
- If forced to do delete + reimport: SSH copy `tickarr_data/*` → `tickarr_{ver}_data/`, create relative symlink `tickarr_data/tickers` → `../tickarr_{ver}_data/tickers`, run Reload Poller, migrate mappings.json deeplinks

### Deeplink Migration (if mappings.json has old xmplaylist slugs)
If `xm_deeplink` values are xmplaylist slugs (e.g. "1stwave") instead of STL IDs (e.g. "firstwave"),
run this migration inside the container using station_cache.json as the translation table:
```python
# Builds {deeplink_id.lower(): stellartunerlog_id} lookup and updates mappings in place
# 141 slugs translated, 30 already correct, remainder were already numeric STL IDs
```
The bridge: `channels.json deeplink_id.lower()` == xmplaylist slug == can map to stellartunerlog `id`.

---

## Publishing Status
- **GitHub:** https://github.com/jstevenscl/tickarr — v0.1.82 pushed 2026-06-01 (master)
- **GitHub Release:** v0.1.0 release still the tagged public release; v0.1.82 on master, no new release tag
- **Dispatcharr/Plugins PR:** https://github.com/Dispatcharr/Plugins/pull/96 — open, awaiting review
- **Docs:** README, USERGUIDE, FAQ, TEAMS.md published; screenshots masked for PII
- **tickarr.com:** Plugin landing page only — Namecheap hosting (kept), DNS via Cloudflare
- **api.tickarr.com:** Cloudflare R2 bucket `sports-data-api`. Live at https://api.tickarr.com/v1/sports.json
- **Data source:** stellartunerlog.com (switched v0.1.81; xmplaylist.com = fallback only, mostly 403)

## Pending: Dispatcharr Channel ID FR
Expected in main release ~2026-06-04. When it ships:
- Update `_enable_nowplaying` / active-viewer detection in plugin.py to use per-channel token
- Remove the limitation note from README and USERGUIDE
- Bump version, rebuild ZIP, update manifests, push, create new GitHub Release

---

## Pending Work
- **Channel logo overlay (NEXT — top priority)** — static SiriusXM channel logo overlaid via FFmpeg `movie` filter on audio streams. Download at enable-time, save to `channel_{id}_logo.png`. Never changes so no hot-reload issue. Previous FIFO/dynamic attempts (v0.1.63-66) failed; this is static only. Implement as v0.1.83.
- **Official v0.1.01 release** — once v0.1.82 testing confirmed, update manifests (`latest` → 0.1.01), copy zip, update root manifest.json, push, create GitHub Release tag, update Dispatcharr PR.
- **Dispatcharr per-channel FR** — expected ~2026-06-04; update enable_nowplaying, remove limitation docs.

## Session Summary (2026-06-01)

### sxmd / stellartunerlog.com
- nowplaying.html: 3-view toggle (List/Grid/Directory), localStorage persistence, readability improvements
- Artwork pipeline: iTunes captures Apple Music trackViewUrl; retry_count column for stale re-checks (30 days, max 3 retries); Spotify dormant (requires Premium)
- BPM artwork: 41% coverage — radio-only remixes not on Deezer/iTunes, expected behavior
- tickarr.com DNS → Cloudflare; MX migrated; Namecheap hosting kept

### Tickarr v0.1.82
- **4 changes:** deeplink_id field fix, API_MIN_INTERVAL NameError fix, cut_type filter, xmplaylist fallback
- **Deeplink mismatch discovered:** xm_deeplink in mappings.json was xmplaylist slugs ("1stwave") but stellartunerlog nowplaying.json is keyed by STL IDs ("firstwave"). Fixed via one-time migration using `deeplink_id.lower()` as bridge.
- **Install mess:** uninstall+reimport created versioned `tickarr_0_1_82` dir instead of `tickarr`. Fixed with SSH data copy + relative symlink. Stream profiles still hardcode old `tickarr_data/tickers` path — symlink redirects to new location.
- **Final state confirmed working:** 423 channels sweeping live data, music channels displaying correctly in UHF, sports/talk showing "On Air"

## Session Restart Instructions
1. Read this file first
2. GitHub master: **0.1.82** — confirmed working in UHF on dispatch2
3. All three phases working: Now Playing (stellartunerlog.com), Custom Text, Sports Ticker
4. Current Dispatcharr install: UNMANAGED `tickarr_0_1_82` at `tickarr_0_1_82_data/`; symlink in place
5. **Next session focus: channel logo overlay** — static FFmpeg `movie` filter overlay, implement as v0.1.83
6. Official public release: still v0.1.0; when v0.1.82 testing done → release as v0.1.01
7. Memory folder: `C:\Users\Owner\.claude\projects\C--Projects-Tickarr\memory\`
