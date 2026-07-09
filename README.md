# Tickarr

![Version](https://img.shields.io/badge/version-0.3.03-blue)

A [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) plugin that injects dynamic text overlays into IPTV channels via FFmpeg. Tickarr clones the channel's existing stream profile, injects overlay parameters, and restores the original profile on disable — the source profile is never modified.

---

## Features

**Satellite Radio Now Playing**
- Auto-maps Dispatcharr channels to satellite radio stations
- Displays artist, song title, and channel name as a live-updating overlay
- Audio-only channels receive an injected 1280x720 black video background — **the base profile must be genuinely audio-only (no `-c:v`/`-vcodec` flag, not even `-c:v copy`)** or the overlay will never render. See [Your base profile must be genuinely audio-only](docs/USERGUIDE.md#your-base-profile-must-be-genuinely-audio-only) in the User Guide.
- On-Demand mode: overlay activates when a viewer tunes in, restores to passthrough when idle

**EAS/JAS Weather Alerts — USA (NOAA/NWS)**
- Monitors NOAA/NWS for active weather alerts in your configured zones
- Automatically activates a full-width broadcast-style alert bar when an alert fires
- Scrolling crawl with alert details, colored severity label, and optional attention tone
- When multiple alert types are active, the label shows the most severe event and the crawl lists all of them
- Profile switches back to normal passthrough the moment the alert clears
- Attention tone (853+960 Hz EAS dual tone) repeats at a configurable interval
- Co-arms with Now Playing, Custom Text, and Sports Ticker — EAS takes precedence when an alert fires and the previous ticker resumes when it clears
- Test EAS Alert action to verify your overlay without waiting for a real alert

> **JAS — jesmannstl Alert System.**
> Dedicated to jesmannstl, a weather fanatic and beloved member of the Dispatcharr community.
> Every alert that fires is a reminder of him. Rest in peace.

**Weather Canada Alerts (Environment Canada)**
- Monitors Environment Canada for active alerts in your configured city IDs
- Same broadcast-style overlay as NWS — full-width alert bar, colored severity label, scrolling crawl
- NAAD attention signal (Canadian alerting tone) plays at the configured interval during active alerts
- Severity mapped to Canada's color system: Yellow (Watch/Moderate), Orange (Warning/Severe), Red (Emergency/Extreme)
- Bilingual area names — alert location displayed in English or French based on your language setting
- Can run simultaneously with NWS EAS — independent channel targeting for each source
- Separate city lookup action: enter a city name or province code to find your city IDs

**Custom Text**
- User-defined static or scrolling text overlay on any channel
- Configurable position (top or bottom), display timing, and style
- On-Demand mode: overlay fires when text is set, disappears when text is cleared

**Sports Ticker**
- Live scores from the ESPN API across 26 leagues and NASCAR
- Scrolling or static ticker at the top or bottom of the screen — live games shown first
- Smart trigger modes: Always On, Active Games Only, or Favorite Teams Only
- Active Games Only: ticker fires automatically when a live game is in progress, clears when all games end
- Favorite Teams Only: ticker fires only when your specified teams are playing
- Static mode: centered fixed text — ideal when showing one or two teams via Favorite Teams

---

## How On-Demand Mode Works

Every overlay type in Tickarr supports an on-demand mode, which keeps your channels on normal passthrough until there is actually something to show. No re-encoding, no CPU overhead, no unnecessary profile clones — until the trigger condition is met.

### Sports Ticker

You can set the sports ticker to only display when there is actually a live game happening. If you have MLB enabled, every time there is a live MLB game on, the ticker automatically appears on any channel you are actively watching. The moment all the games end, the ticker disappears and your channel goes back to normal.

If you only care about a specific team, you can set a Favorite Teams filter. Put in the Astros and the ticker will only ever appear when the Astros are playing — not during any other game, only Houston. The moment that game ends it goes away until the next time they take the field.

If you are using Favorite Teams and only following one or two teams, you can set the Ticker Style to **Static** — the score sits centered and fixed on screen rather than scrolling. Keep Scrolling if you have multiple leagues or teams enabled, since long content will be cut off in Static mode.

### Satellite Radio Now Playing

Tickarr does not do anything to a channel until someone actually starts watching it. The moment a viewer tunes in, the Now Playing overlay activates — showing the current artist, song title, and channel name. If nobody has been watching for about 30 seconds, it quietly switches back to normal passthrough until the next time someone tunes in.

This matters a lot if you have a large satellite radio lineup. Instead of re-encoding hundreds of channels around the clock whether anyone is watching or not, Tickarr only runs the overlay on the channels that are actually being watched right now.

### Custom Text

Nothing happens until you give it something to display. You enable it on a channel and the channel stays completely normal until you go to Update Custom Text, type your message, and run the action — at that point the overlay appears. When you want it gone, clear the text field and run Update Custom Text again. Tickarr removes the overlay and puts the channel back to passthrough instantly.

### EAS Weather Alerts

Your channel runs 100% normally at all times. Tickarr sits quietly in the background watching the NWS API for your configured zone codes — no overlay, no extra encoding, nothing. The moment an actual weather alert goes active for your zone, Tickarr automatically switches the channel to the EAS overlay: scrolling alert bar, severity label, and attention tone if configured. The second that alert clears on the NWS side, your channel goes silently back to normal. Completely automatic, start to finish.

---

## Requirements

- Dispatcharr v0.27.1 or later
- Redis (used by Dispatcharr — standard in all installs)
- FFmpeg in the Dispatcharr container (standard in all installs)
- Channels must have an FFmpeg-based stream profile assigned — **Proxy** and **Redirect** profiles bypass FFmpeg and cannot be used with any Tickarr overlay. See [Before You Start](docs/USERGUIDE.md#before-you-start--universal-requirements) in the User Guide if affected channels are being skipped.

---

## Installation

1. Open Dispatcharr → **Plugins → Find Plugins**
2. Search for **Tickarr** and install
3. After installation, go to **Tickarr → Actions → Restart Dispatcharr**

   > A restart is required after every install or update. Django caches plugin code at startup — without a restart, new code will not load.

4. Configure your settings on the Tickarr plugin page
5. Run the appropriate enable action for the overlay type you want

---

## Quick Start

See the [User Guide](docs/USERGUIDE.md) for full setup instructions, settings reference, and troubleshooting.

---

## Actions Tab — Button Color Key

Each section of the Actions tab has its own button color. Filled buttons activate or update; outline buttons remove, restore, or run a secondary utility.

| Color | Section |
|---|---|
| Cyan | Satellite Radio — Now Playing and Channel Setup |
| Orange | EAS / JAS Weather Alerts (USA — NWS) |
| Teal | Weather Canada Alerts (Environment Canada) |
| Blue | Custom Text |
| Green | Sports Ticker |
| Violet | Manage |
| Red | Global destructive — Disable All Tickers and Restart Dispatcharr only |

---

## ESPN Team Reference

See [TEAMS.md](docs/TEAMS.md) for ESPN team abbreviations used by the Sports Ticker.
