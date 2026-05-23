# Tickarr

![Version](https://img.shields.io/badge/version-0.1.0-blue)

A [Dispatcharr](http://dispatcharr.local) plugin that injects dynamic text overlays into IPTV channels via the FFmpeg `drawtext` filter. Tickarr clones the channel's existing stream profile, injects overlay parameters, and restores the original profile on disable — the source profile is never modified.

<!-- screenshots: docs/screenshots/ -->

---

## Features

**SiriusXM Now Playing**
- Auto-maps Dispatcharr channels to SiriusXM stations via xmplaylist.com
- Displays artist, song title, and channel name in a centered overlay box
- Audio-only channels receive an injected 1280x720 black video background
- Note: currently clones a stream profile for every channel in the selected scope — see the [User Guide](docs/USERGUIDE.md#channel-mapping) for details

**Custom Text**
- User-defined static or scrolling text overlay on any channel
- Supports always-on or timed display (appears for N seconds every X seconds)
- Configurable position (top or bottom of screen)

**Sports Ticker**
- Live scores from the ESPN API across 23 leagues and NASCAR
- Scrolling three-color ticker at the top or bottom of the screen
- Live games shown first; favorites filter to display only selected teams
- [ESPN team abbreviations reference](docs/TEAMS.md)

---

## Requirements

- Dispatcharr v0.25.0 or later
- Redis (used by Dispatcharr for active-viewer detection)
- FFmpeg available in the Dispatcharr container (standard in all Dispatcharr installs)

---

## Installation

1. Open Dispatcharr and navigate to **Plugins → Find Plugins**.
2. Paste the Tickarr registry URL into the plugin source field and install Tickarr.
3. After installation completes, go to **Tickarr → Actions → Restart Dispatcharr**.

   > Restarting Dispatcharr is required after every install or update. Django caches module code at startup; without a restart, new plugin code will not be loaded.

4. Return to the Tickarr plugin page and configure your settings.
5. Run the appropriate enable action for the overlay type you want to use.

---

## Quick Start

See the [User Guide](docs/USERGUIDE.md) for full setup instructions, settings reference, and troubleshooting.
