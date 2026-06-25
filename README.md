# Tickarr

![Version](https://img.shields.io/badge/version-0.2.00-blue)

A [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) plugin that injects dynamic text overlays into IPTV channels via FFmpeg. Tickarr clones the channel's existing stream profile, injects overlay parameters, and restores the original profile on disable — the source profile is never modified.

---

## Features

**Satellite Radio Now Playing**
- Auto-maps Dispatcharr channels to satellite radio stations
- Displays artist, song title, and channel name as a live-updating overlay
- Audio-only channels receive an injected 1280x720 black video background

**EAS/JAS Weather Alerts**
- Monitors NOAA/NWS for active weather alerts in your configured zones
- Automatically activates a full-width broadcast-style alert bar when an alert fires
- Scrolling crawl with alert details, colored severity label, and optional attention tone
- Profile switches back to normal passthrough the moment the alert clears
- Attention tone (853+960 Hz EAS dual tone) repeats at a configurable interval

> **JAS — jesmannstl Alert System.**
> Dedicated to jesmannstl, a weather fanatic and beloved member of the Dispatcharr community.
> Every alert that fires is a reminder of him. Rest in peace.

**Custom Text**
- User-defined static or scrolling text overlay on any channel
- Configurable position (top or bottom), display timing, and style

**Sports Ticker**
- Live scores from the ESPN API across 23 leagues and NASCAR
- Scrolling three-color ticker at the top or bottom of the screen
- Live games shown first; team filter available

---

## Requirements

- Dispatcharr v0.26.0 or later
- Redis (used by Dispatcharr — standard in all installs)
- FFmpeg in the Dispatcharr container (standard in all installs)

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

## ESP Team Reference

See [TEAMS.md](docs/TEAMS.md) for ESPN team abbreviations used by the Sports Ticker.
