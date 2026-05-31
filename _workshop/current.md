# Tickarr — Working Notes
**Status: Phase 1 WORKING ✓ | Phase 2 Custom Text WORKING ✓ | Phase 3 Sports Ticker WORKING ✓**
**Last updated: 2026-05-31**

---

## Project Name
**Tickarr** (renamed from Tickerr/Tickarr in planning — directory was Tickerr, now Tickarr)
Follows *arr ecosystem naming: Tick + arr. Lives in the Dispatcharr plugin registry.

---

## What It Is
A Dispatcharr plugin that injects dynamic text overlays into IPTV stream channels via FFmpeg
`drawtext` filter. Three modes, built in this order:

1. **SiriusXM Now Playing** — auto-maps Dispatcharr channels to xmplaylist.com, shows artist/song/channel in a centered box overlay. *Working.*
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
- Dispatcharr 0.25.0 (current)
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
    "xm_deeplink": "hotelcalifornia",
    "channel_name": "Hotel California",
    "channel_description": "...",
    "type": "nowplaying"
  }
}
```

### Background Polling
Two loops running as daemon threads:
- **Fast loop** (2s tick): scans Redis for newly active streams, polls them immediately on stream-start
- **Sweep loop** (15s tick): polls all currently active channels; falls back to all channels if Redis unavailable

Global rate lock `_api_rate_lock` with `API_MIN_INTERVAL = 1.5s` in `_get_now_playing()` — prevents concurrent threads from bursting the xmplaylist API.

Always call `connection.close()` in a `finally` block after any ORM query in a background thread — Django does not auto-close thread-local DB connections outside of request/response cycle.

### Redis Active Stream Detection
**Dispatcharr v0.25+:** `live:channel:{UUID}:activity`
**Dispatcharr v0.24:** `ts_proxy:channel:{UUID}:activity`
**Always scan both patterns** — union the results. Channel identifier is a UUID, not an integer. Map UUID → integer channel ID via `Channel.objects.filter(id__in=...)` using the `uuid` field. Cache this map for 5 minutes.

Redis runs **inside** the `dispatcharr` Docker container (no separate redis container).

### File Storage
```
/data/plugins/tickarr_data/
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
FFmpeg reads via `textfile=/path/file.txt:reload=1` on every frame.

### FFmpeg Overlay (Audio-Only Channels)
SiriusXM channels are audio-only. Tickarr injects a lavfi black video background + drawtext:
```python
lavfi = '-f lavfi -i "color=c=black:s=1280x720:r=25"'
filter_complex = '[1:v]{drawtext}[vout]'
# maps: [vout] + 0:a:0
# codec: libx264 -preset ultrafast -tune stillimage -crf 28
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

### UUID Match — Provably Guaranteed, Not Coincidental
`channels.json`'s `lookaround_channel_id` field was captured directly from **SiriusXM's own internal API** (raw responses stored in `C:\Projects\epgeditarr\_workshop\sxm_channels_full.json`). xmplaylist.com also sources its `channel.id` UUID from SiriusXM's same internal API. Both services use SiriusXM's own `lookaroundChannelId` UUID namespace. The match is structural — one UUID, two consumers.

### Channel Data Source
Tickarr fetches **the same GitHub Pages file as EPGeditARR**:
```
https://jstevenscl.github.io/epgeditarr/channels.json
```
- 7-day TTL, cached to disk
- **No dependency on EPGeditARR being installed**
- Also fetch `channel_aliases.json` from same host for name normalization

### xmplaylist.com API Endpoints
```
GET https://xmplaylist.com/api/station
  → returns all stations: [{id (UUID), name, number, deeplink, ...}]

GET https://xmplaylist.com/api/station/{deeplink}
  → returns [{track: {title, artists}, ...}]
```
Rate limit: enforce 1.5s minimum globally. Returns 429 at ~2 req/s, 403 (IP ban) on bursts.

### Enable Action (v0.1.46+)
Enable Now Playing does NOT call xmplaylist during enable — just clones profiles and writes fallback text. Sweep loop fetches live data within 15 seconds. This avoids 504 Gateway Timeout when enabling 160+ channels (old approach: 160 × 1.5s = 240s > nginx 60s limit).

---

## Current Version: 0.1.81 (live on GitHub)

### Actions in plugin.json
Grouped with `type: "info"` section headers (same as Settings tab):
- **── SiriusXM Now Playing ──**: enable_nowplaying, disable_nowplaying
- **── Custom Text ──**: enable_custom, update_custom, disable_custom
- **── Sports Ticker ──**: enable_sports, disable_sports
- **── Manage ──**: view_active, refresh_channels, disable_all, clean_orphans, redis_diag, reload_poller, restart_dispatcharr

Note: `type: "info"` in actions is untested in Dispatcharr — if it renders a broken button or errors, remove the divider entries. If ignored silently, they're harmless.

### Restart Dispatcharr Action
Sends SIGHUP to gunicorn master (found via `pgrep -of gunicorn`, falls back to PID 1).
Graceful reload — new workers spawn with fresh Python code, active FFmpeg streams unaffected, sessions preserved. Use after every plugin update instead of SSH/Portainer.

### Version History (key fixes)
- **0.1.43** — Fixed Redis key format (UUID-based activity keys), global rate lock
- **0.1.44** — Fixed DB connection leak (connection.close() in finally block), removed ThreadPoolExecutor
- **0.1.45** — 640x360 resolution attempt (reverted — font quality too poor)
- **0.1.46** — Fixed 504 timeout on enable (removed xmplaylist call from enable action)
- **0.1.47** — Reverted to 1280x720
- **0.1.48** — Fixed Redis key prefix for Dispatcharr v0.25.0 (live: vs ts_proxy:), dual-pattern scan
- **0.1.49** — Added Reload Poller + Restart Dispatcharr actions
- **0.1.50** — Phase 2: Custom Text overlay (static/scrolling × always-on/timed)
- **0.1.51** — Independent target selectors per phase (np_*, custom_* prefixes)
- **0.1.52** — Fixed `-c copy` not replaced for video channels (FFmpeg rejects filter + stream copy)
- **0.1.53** — Disable Ticker falls back to custom_*/np_* selectors when disable dropdown is stale
- **0.1.54** — Update Custom Text action for real-time text changes
- **0.1.55** — A/V sync fix attempt (switched to -c:a aac, later reverted)
- **0.1.56** — Proper A/V sync fix: -tune zerolatency removes encoder lookahead, -c:a copy works cleanly
- **0.1.57** — Phase 3: Sports Ticker — ESPN API, 23 leagues, NASCAR live feed, favorites filter, sports_* fields
- **0.1.58** — Split Disable Ticker into three independent phase actions (disable_nowplaying, disable_custom, disable_sports); _do_disable helper with type_filter enforcement; removed disable_channel_id dropdown; improved no-stream-profile error message
- **0.1.59** — Added sports_fontsize field (number, default 36, min 16) to Sports Ticker settings
- **0.1.60** — Added multi-color sports ticker: three synchronized drawtext layers (scores=white+box, abbrevs=user color, labels=user color); _game_seg_triple/_sport_section_triple helpers; sports_labelcolor and sports_abbrcolor select fields; writes four files per channel (labels/abbrevs/scores/full)
- **0.1.61** — Fixed color layer sync bug: proportional fonts cause different text_w per layer → layers scroll at different speeds and visually flicker; fixed via _resolve_mono_font() check at load time; graceful fallback to single white layer (sports_full.txt) when no monospace font found in container
- **0.1.62** — Fixed remaining color layer sync: replaced U+00B7 middot separator with ASCII pipe (|); added ljust() normalization so all three layers are always the same byte length
- **0.1.63** — Phase 3 logo strip: ESPN CDN logos downloaded and composited into PNG strip per channel; _find_abbrev_positions maps team abbr → x_offset; logo strip overlaid above/below ticker via FFmpeg overlay filter — BUT race condition (bg thread) and filter_complex bug ([strip_in] label) meant logos never appeared
- **0.1.63–0.1.66** — Logo strip attempts (static PNG, FIFO/image2pipe): all abandoned. FFmpeg FIFO blocks entire filter_complex on open; static PNG can't update live. Logo feature scrapped entirely.
- **0.1.67** — Reverted to clean 3-layer drawtext (v0.1.62 behavior). Removed all logo infrastructure. Fixed fd leak (bare open() calls), wrong sports_full.txt filename in View Active, -vf quoted filter injection bug, dead imports/constants, duplicate subprocess import, stale user messages.
- **0.1.68/0.1.69** — Stale channel auto-recovery: `_channel_is_stale()` checks song.txt mtime vs STALE_THRESHOLD (120s); sweep loop polls stale channels in batches of 10 alongside active ones.
- **0.1.70** — Fixed infinite stale-retry loop: when xmplaylist returns no data, touch song.txt to reset mtime so stale recovery backs off instead of hammering the API every sweep.
- **0.1.71** — Fixed sports ticker bouncing when no games: empty scores.txt → text_w=0 → x=w-mod(t*100,w) oscillates 0↔w. Fix: write "  No games scheduled  " to scores layer (has box), equal-length spaces to labels/abbrevs so all three layers share same text_w.
- **0.1.72** — Added `type: "info"` section headers to Actions tab (SiriusXM Now Playing / Custom Text / Sports Ticker / Manage). Same grouping pattern as Settings tab.
- **0.1.73** — Fixed A/V sync on audio-only (SiriusXM) channels: audio-only path was missing `-c:a copy` so FFmpeg re-encoded audio causing drift. Changed `-tune stillimage` to `-tune zerolatency` (same as video channel path) and added `-c:a copy`. Existing channels must be disabled + re-enabled to pick up new FFmpeg params.
- **0.1.74** — Added `type: "info"` section headers to Actions tab (SiriusXM Now Playing / Custom Text / Sports Ticker / Manage). Expanded `_clean_orphans` to also sweep profiles containing "tickarr_data" in parameters (catches FIFO-era non-standard-named orphans).
- **0.1.75** — Fixed buffering on video channels (sports ticker, custom text on video streams). Two root causes: (1) `reload=1` on all drawtext layers forced a file read on every single frame; changed to `reload=30` (reads once/second, sufficient for all ticker types). (2) FFmpeg's MPEG-TS muxer default 1-second interleave buffer when transcoding video + copying audio separately; added `-max_interleave_delta 1` to suppress it. Channels with stream-copy base profiles (low latency) no longer buffer after Tickarr injects the drawtext filter.
- **0.1.76** — Fixed all-I-frame explosion on channels whose base stream profile contained `-force_key_frames "expr:gte(t,n_forced*0)"`. With `-c copy` this flag is ignored; with libx264, `gte(t, n_forced*0)` = `gte(t, 0)` = always true → every frame forced as keyframe → output bitrate explodes → buffering. `_inject_drawtext` now strips `-force_key_frames` with two regex passes before injecting the video encoder flags.
- **0.1.77** — Buffering still appeared after ~30 seconds (sports sweep loop fires, replaces placeholder with full ESPN data). Added `_MAX_FINALS_PER_SPORT = 3` cap to limit ticker text length after sweeps (later superseded by fixed-length buffer in v0.1.79; cap removed in v0.1.80).
- **0.1.78** — Added Color Mode toggle to sports ticker: Single Color (white, default, 1 drawtext layer) vs. Multi-Color (3 drawtext layers with sport labels and team abbreviations in configurable colors). Single-color mode reduces FFmpeg filter CPU by ~3×. `_build_sports_filter` takes `color_mode` parameter; `_enable_sports` stores `sports_color_mode` in mappings. Single color set as default and recommended option.
- **0.1.79** — Fixed scroll jumping when ESPN poll returns different game counts than previous poll. `text_w` in the scroll expression `mod(t*100, w+text_w)` is calculated from the text file length at filter load time; when file length changes, FFmpeg re-evaluates `text_w` mid-scroll causing the position to snap. Fixed with `_TICKER_FIXED_LEN = 600`: all ticker text files are always exactly 600 characters (padded with spaces, truncated at boundary); `text_w` is constant across reloads.
- **0.1.81** — Switched now-playing source from xmplaylist.com to stellartunerlog.com/nowplaying.json; one bulk fetch per sweep covers all 437 channels; removed per-channel rate limiter; _get_stations() now uses stellartunerlog.com/channels.json; field parsing updated (station['artist']/station['title'] instead of track/artists structure)
- **0.1.80** — Removed all artificial per-sport game count caps (`_MAX_FINALS_PER_SPORT`, all `[:N]` slices). Fixed-length buffer (`_TICKER_FIXED_LEN = 600`) already bounds ticker length regardless of game count; explicit caps were confusing and unnecessary. Updated docs to note the 600-char ticker window and recommend Favorite Teams field for users with many sports enabled.

---

## Sports Data Architecture (Phase 3 — not starting yet)

### Source
All 26 sports via ESPN Site API — free, no key required:
```
GET https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard
```

### Code to Extract from ScorecastARR
File: `C:\Projects\scorestream-pro\scorecastarr\api\app.py`
- Lines ~1615–1759: `_ticker_text_for_config()` — complete fetch + format function
- `ESPN_PATHS` dict — all 26 sports mapped to ESPN paths
- `LABELS` dict — sport_id → display name
- NASCAR spoofed headers block
- In-memory TTL cache pattern (30s)

---

## Build Plan

### Phase 1: SiriusXM Now Playing — COMPLETE (v0.1.48)
Confirmed working on Dispatcharr v0.25.0.
Monitor for 12-hour stability (DB connection fix from v0.1.44 should hold).

### Phase 2: Custom Text
- Add `enable_custom` action
- Single text file per channel
- Scrolling or static option in settings

### Phase 3: Sports Ticker — COMPLETE (v0.1.67)
- ESPN API for 22 sports + NASCAR live feed
- `sports_*` prefixed fields — fully independent from Phase 1 and 2
- League toggles grouped by category (Football/Basketball/Baseball/Hockey/Soccer/Tennis/Motor/College Other)
- Favorites field: comma-separated team abbreviations, blank = all
- `enable_sports` action: clones profile, writes scrolling 3-layer drawtext filter
- `_sports_sweep_loop`: 30s background thread, ESPN fetch + atomic file write
- `_fetch_sports_text`: 30s in-memory cache, live games first then finals
- Three layers: scores (white+box), abbrevs (user color), labels (user color) — monospace font required; falls back to single white layer if not present
- Disable Ticker and Disable All both handle sports type cleanup

---

## Possible Future Improvements (not started)

### Sports Ticker Display Window
Ticker text is always exactly 600 characters (`_TICKER_FIXED_LEN`). Live games appear first; finals fill remaining space. There are no per-sport caps — if content exceeds 600 chars it wraps on the next loop pass. Users with many leagues enabled should use the Favorite Teams field to keep the ticker focused on games they care about.

### xmplaylist.com Reliability Problem
xmplaylist.com is a community-run scraper. Channels like BPM go stale for hours with no updates — a problem we cannot fix from Tickarr's side since xmplaylist controls the polling.

**Considered solution:** A standalone service that authenticates directly with SiriusXM using personal streaming credentials and polls the now-playing endpoint for each channel. Would write directly to `/data/plugins/tickarr_data/tickers/*.txt` (reads `mappings.json` to resolve Dispatcharr channel IDs), bypassing Tickarr's xmplaylist poller entirely. FFmpeg picks up file changes on the next `reload` tick. `sxm-player`/`sxm-client` Python libraries are the candidate auth layer.

**Status:** On hold — this functionality is under consideration for a separate higher-level project (not yet named) that would act as a central data-feeding layer for Dispatcharr plugins and other integrations. If that project materializes, SiriusXM now-playing would be one of its data sources; Tickarr would consume from it rather than xmplaylist.com directly.

---

## Testing Approach
Install plugin ZIP via Dispatcharr web UI. No local Docker required.
After plugin update: use **Restart Dispatcharr** action in Tickarr (no SSH/Portainer needed).

## Publishing Status
- **GitHub:** https://github.com/jstevenscl/tickarr — v0.1.81 pushed 2026-05-31
- **GitHub Release:** v0.1.0 release still the tagged public release; v0.1.81 is on master but no new release tag yet
- **Dispatcharr/Plugins PR:** https://github.com/Dispatcharr/Plugins/pull/96 — open, awaiting maintainer review
- **Docs:** README, USERGUIDE, FAQ, TEAMS.md published; screenshots masked for PII
- **tickarr.com:** Now a Tickarr plugin landing page only — data service moved to stellartunerlog.com
- **Data source:** stellartunerlog.com (was xmplaylist.com — switched in v0.1.81)

## Pending: Dispatcharr Channel ID FR
Dispatcharr dev is implementing per-channel token data in response to our FR. Expected in main release ~2026-06-04. When it ships:
- Update `_enable_nowplaying` / active-viewer detection in plugin.py to use per-channel token
- Remove the limitation note from README and USERGUIDE (`channel-mapping` section)
- Bump version, rebuild ZIP, update manifests, push, create new GitHub Release

---

## Pending Work
- **Channel logo overlay** — use FFmpeg `movie` filter to overlay static channel logo (downloaded at enable-time) on SiriusXM audio streams. Logo never changes so no hot-reload issue. Implement as v0.1.82.
- **Dispatcharr per-channel FR** — expected ~2026-06-04; when it ships, update enable_nowplaying to use per-channel token, remove limitation note from docs.

## Session summary (2026-05-31)
- **stellartunerlog.com website** — nowplaying.html: chunked RAF rendering (fast first paint), debounced search. index.html: paid API fields replaced with capability descriptions only.
- **sxmd crash fixed** — httpx.PoolTimeout from 437 concurrent requests; fixed with Semaphore(15). All 437 channels stable.
- **Album artwork** — iTunes fallback live (`itunes.py`): queries on missing art, caches permanently in SQLite. Background backfill running through 6,600+ historical plays. Channel logos now hosted at stellartunerlog.com/logos/ (SiriusXM CDN had broken HTTPS cert). Programs/talk/sports fall back to channel logo in now-playing grid, history modal, and history page.
- **Channel coverage confirmed** — all 437 subscribed, 0 sat-only. 277 Xtra channels (1000+) investigated — not pollable via streaming API, not worth pursuing.

## Session Restart Instructions
1. Read this file first
2. Current version on GitHub master: **0.1.81** — Now Playing uses stellartunerlog.com (not xmplaylist.com)
3. All three phases working: Now Playing, Custom Text, Sports Ticker
4. Data source: https://stellartunerlog.com/nowplaying.json (bulk fetch, all 437 channels, one request per sweep)
5. tickarr.com is now the plugin landing page only — separate from StellarTunerLog
6. Memory folder: `C:\Users\Owner\.claude\projects\C--Projects-Tickarr\memory\`
