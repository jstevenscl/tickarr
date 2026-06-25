# Tickarr User Guide

Tickarr is a plugin for [Dispatcharr](http://dispatcharr.local) that injects live text overlays into IPTV channels using FFmpeg. For a brief overview, see the [README](../README.md).

---

## Table of Contents

1. [Overview](#overview)
2. [Installation and First Run](#installation-and-first-run)
3. [Satellite Radio Now Playing](#satellite-radio-now-playing)
4. [EAS/JAS Weather Alerts](#easjas-weather-alerts)
5. [Custom Text](#custom-text)
6. [Sports Ticker](#sports-ticker)
7. [Settings Reference](#settings-reference)
8. [Actions Reference](#actions-reference)
9. [Troubleshooting](#troubleshooting)

---

## Overview

Tickarr adds four types of overlays to channels managed by Dispatcharr:

- **Satellite Radio Now Playing** — shows the current artist and track for satellite radio channels.
- **Custom Text** — displays any text you choose, either static or scrolling, on a schedule you control.
- **Sports Ticker** — shows live scores from the ESPN API for 23 leagues and NASCAR.
- **EAS Weather Alerts** — monitors NOAA/NWS and automatically activates a broadcast-style alert bar with scrolling crawl and attention tone when an active weather alert fires for your zones.

When you enable an overlay, Tickarr clones the channel's existing FFmpeg stream profile, adds a `drawtext` filter to the cloned copy, and assigns that copy to the channel. Your original stream profile is never changed. When you disable an overlay, the original profile is restored and the cloned profile is deleted.

Text content is written to files on disk (`/data/plugins/tickarr_data/tickers/`). FFmpeg reads those files live, so the overlay updates without interrupting the stream.

---

## Installation and First Run

![Tickarr plugin details page](screenshots/details.png)

1. In Dispatcharr, go to **Plugins → Find Plugins**.
2. Paste the Tickarr registry URL into the source field and click **Install**.
3. Wait for the installation to complete.
4. Go to **Tickarr → Actions** and run **Restart Dispatcharr**.

   This step is required. Dispatcharr loads plugin code once at startup; without a restart, none of the new code is active.

5. After Dispatcharr restarts, navigate back to the Tickarr plugin page.
6. Configure your settings for whichever overlay type you want to use, then run the corresponding **Enable** action.

> Note: Repeat steps 3 and 4 after every Tickarr update.

---

## Satellite Radio Now Playing

### What it does

Tickarr polls stellartunerlog.com at regular intervals to find the currently playing track for each satellite radio station. It displays the artist name, song title, and the Dispatcharr channel name in a centered overlay box on a black background. For channels that carry audio only (no video signal), Tickarr injects a 1280x720 black video frame so the overlay has somewhere to render.

### Setup

![Now Playing settings](screenshots/settings-nowplaying.png)

1. Under **Now Playing**, choose who this applies to:
   - **Single Channel** — overlay goes on one channel you select.
   - **Channel Group** — overlay goes on every channel in a group.
   - **All Channels** — overlay goes on every Dispatcharr-managed channel.
2. If you chose Single Channel, select the channel from the **Channel** dropdown. If you chose Channel Group, select the group.
3. Run **Actions → Enable Now Playing**.

### Channel mapping

Tickarr matches Dispatcharr channel names to satellite radio station names automatically. The match is fuzzy — for example, a channel named "Hits 1" will match the station by that name without needing manual configuration.

> **Note on stream profiles:** Tickarr currently clones a stream profile for every satellite radio channel in the selected scope. This is a limitation of how Dispatcharr identifies active viewers — the plugin does not yet have access to individual channel IDs at query time. Dispatcharr is actively implementing per-channel token data (expected in an upcoming release), which will allow Tickarr to target only channels with active viewers and eliminate unnecessary profile clones. Until then, enabling Now Playing on a large channel group or "All Channels" will create one cloned profile per channel in that scope.

### What to expect

- The overlay will not appear instantly. The poller needs up to 15 seconds to fetch the first track data after enabling.
- Audio-only channels will show a solid black screen with the overlay centered on it. This is expected behavior.
- The overlay updates automatically as tracks change.

### Disabling

Run **Actions → Disable Now Playing**. The original stream profile is restored and the cloned profile is deleted.

---

## EAS/JAS Weather Alerts

> **JAS — jesmannstl Alert System.**
> Dedicated to jesmannstl, a weather fanatic and beloved member of the Dispatcharr community.
> Every alert that fires is a reminder of him. Rest in peace.

---

Tickarr monitors NOAA/NWS for active weather alerts in your configured zones. When an alert fires, it automatically switches affected channels to a broadcast-style EAS overlay profile — a full-width alert bar with a scrolling crawl and colored severity label. When the alert clears, channels silently switch back to their normal passthrough profiles with no action required.

### Prerequisites

- Your NWS zone code(s) — find yours at [alerts.weather.gov](https://alerts.weather.gov) (e.g. `OHZ001`)
- At least one channel enabled for EAS via **Actions → Enable EAS Silent Ticker**

### Setup

1. In Tickarr Settings under **EAS Weather Alerts**, enter your NWS zone code(s) in **Zone IDs** (comma-separated for multiple zones, e.g. `OHZ001,OHZ002`).
2. Configure your remaining EAS settings (see the [EAS Settings Reference](#eas-settings) below).
3. Select the channels or channel group you want EAS to cover.
4. Run **Actions → Enable EAS Silent Ticker**.

That's it. Channels stream exactly as normal until an alert fires. No re-encoding, no overlay, no CPU cost — until there's something to show.

### What the overlay looks like

The **broadcast** style (recommended) places a dark bar across the bottom of the screen with:
- A colored severity label on the left (`TORNADO WARNING`, `FLOOD WATCH`, `WEATHER ALERT`, etc.)
- A white scrolling crawl to the right listing the alert details and affected areas

When multiple alert types are active simultaneously the label shows `WEATHER ALERT` and the crawl lists all active events.

Label color follows the highest-severity active alert and can be customized with the **Alert Label Color** setting.

### Attention tone

When **Siren Tone Interval** is greater than 0, Tickarr mixes a real EAS attention tone — 853 Hz + 960 Hz dual tone, 8 seconds — into the audio stream. The tone repeats at your configured interval for the life of the alert. Setting it to 60 means viewers hear the tone once per minute; 300 is less intrusive for long-duration events.

The tone is generated mathematically inside FFmpeg — no external audio file needed, and it works on any channel regardless of source audio codec.

### How profile switching works

- **Alert fires:** Tickarr clones the channel's current stream profile, injects the EAS overlay (and tone if configured), and assigns the clone. The original profile is never modified.
- **Alert clears:** The EAS clone is deleted and the original profile is restored. The switch happens within one poll interval (default 60 seconds).
- **Mid-alert settings change:** Profile changes don't apply to an already-running alert. To apply new settings immediately, disable your zones and re-enable them to force a fresh clone.

### Disabling

Run **Actions → Disable EAS Ticker**. The original profile is restored on all EAS-enabled channels.

---

## Custom Text

### What it does

Custom Text lets you display any message you choose on one or more channels. You can show it as static text (always the same position, no movement) or as a scrolling ticker. You can keep it on screen at all times or set a timed schedule where it appears for a set number of seconds, disappears, then reappears.

### Setup

![Custom Text settings](screenshots/settings-customtext.png)

1. Under **Custom Text**, choose **Apply To** (Single Channel, Channel Group, or All Channels) and select the channel or group.
2. Enter your message in the **Custom Text** field.
3. Choose a **Style**:
   - **Static** — text stays in a fixed position.
   - **Scrolling** — text scrolls horizontally across the screen.
4. Choose a **Position**: **Top** or **Bottom** of the screen.
5. Choose a **Schedule**:
   - **Always On** — text is visible whenever the channel is being watched.
   - **Timed** — text appears for a specified number of seconds, then hides, then repeats.
6. If you chose Timed, set:
   - **Duration** — how many seconds the text stays visible each cycle.
   - **Interval** — how many seconds between appearances (measured from when the text disappears to when it next appears).
7. Run **Actions → Enable Custom Text**.

### Updating text without disabling

If you want to change the message without disrupting the stream, update the **Custom Text** field and run **Actions → Update Custom Text**. You do not need to disable and re-enable.

### Disabling

Run **Actions → Disable Custom Ticker**.

---

## Sports Ticker

### What it does

The sports ticker pulls live scores from the ESPN API and displays them in a scrolling bar at the top or bottom of the screen. Live games appear first in the rotation, followed by final scores. The ticker updates automatically as scores change.

### Setup

![Sports Ticker league toggles](screenshots/settings-sports-leagues.png)

![Sports Ticker options — Favorite Teams, Color Mode, position](screenshots/settings-sports-options.png)

![Sports Ticker channel selection](screenshots/settings-sports-channel.png)

1. Under **Sports Ticker**, choose **Apply To**, then the channel or group.
2. Toggle on the leagues you want to include. Available leagues:

   NFL, NCAAF, CFL, NBA, WNBA, NCAAB, MLB, NCAA Baseball, NCAA Softball, NHL, MLS, NWSL, EPL, UCL, La Liga, Bundesliga, Serie A, Ligue 1, ATP, WTA, NCAA Volleyball, NCAA Lacrosse, NASCAR

3. Optionally, enter team abbreviations in the **Favorite Teams** field (comma-separated, e.g. `LAL, GSW, BOS`). When favorites are set, only games involving those teams are shown. Leave blank to show all teams. See the [ESPN Team Abbreviations Reference](TEAMS.md) for a full list of abbreviations by league.
4. Set **Ticker Position**: Top or Bottom.
5. Adjust **Font Size** if needed (default 36, minimum 16).
6. Choose a **Color Mode**:
   - **Single Color — White** (default, recommended) — all ticker text is white. Uses less CPU and is the smoothest option for most channels.
   - **Multi-Color** — sport/league labels and team abbreviations are rendered in configurable colors. Requires a monospace bold font in the container; falls back to single color if not found.
7. If using Multi-Color, optionally customize:
   - **Label Color** — color for the sport/league label (default gold, `#ffd700`).
   - **Abbrev Color** — color for team abbreviations (default `#00d4ff`).
8. Run **Actions → Enable Sports Ticker**.

> **Note on ticker capacity:** The ticker displays approximately 600 characters of content per pass, with live games shown first. When many leagues are enabled and there are lots of active games, scores that don't fit in the first 600 characters will be shown on the next loop. To make sure the games you care about are always visible, use the **Favorite Teams** field — when favorites are set, only games involving those teams are included, keeping the ticker focused regardless of how many leagues are active.

### "No games scheduled"

If the ticker shows "No games scheduled," it means the ESPN API returned no live or recently finished games for the leagues you selected at the time of the last poll. This is normal during off-hours and off-season. The ticker will update automatically when games begin.

### Disabling

Run **Actions → Disable Sports Ticker**.

---

## Settings Reference

### Now Playing Settings

| Field | Type | Description |
|---|---|---|
| Apply To | Dropdown | Scope of the overlay: Single Channel, Channel Group, or All Channels |
| Channel Group | Dropdown | The channel group to apply the overlay to (visible when Apply To is Channel Group) |
| Channel | Dropdown | The individual channel to apply the overlay to (visible when Apply To is Single Channel) |

### Custom Text Settings

| Field | Type | Description |
|---|---|---|
| Apply To | Dropdown | Scope: Single Channel, Channel Group, or All Channels |
| Channel Group | Dropdown | Channel group selection (visible when Apply To is Channel Group) |
| Channel | Dropdown | Channel selection (visible when Apply To is Single Channel) |
| Custom Text | Text | The message to display on screen |
| Style | Dropdown | Static (fixed position) or Scrolling (horizontal scroll) |
| Position | Dropdown | Top or Bottom of the screen |
| Schedule | Dropdown | Always On or Timed |
| Duration | Number | Seconds the text stays visible per cycle (visible when Schedule is Timed) |
| Interval | Number | Seconds between appearances (visible when Schedule is Timed) |

### Sports Ticker Settings

| Field | Type | Description |
|---|---|---|
| Apply To | Dropdown | Scope: Single Channel, Channel Group, or All Channels |
| Channel Group | Dropdown | Channel group selection (visible when Apply To is Channel Group) |
| Channel | Dropdown | Channel selection (visible when Apply To is Single Channel) |
| League Toggles | Checkboxes | One toggle per supported league/sport; enable the sports you want shown |
| Favorite Teams | Text | Comma-separated team abbreviations; leave blank to show all teams. See the [ESPN Team Abbreviations Reference](TEAMS.md). |
| Ticker Position | Dropdown | Top or Bottom of the screen |
| Font Size | Number | Text size in points (default 36, minimum 16) |
| Color Mode | Dropdown | Single Color — White (default, lower CPU) or Multi-Color (sport labels and team abbreviations in separate colors) |
| Label Color | Color | Color of the sport/league label — Multi-Color only (default gold, #ffd700) |
| Abbrev Color | Color | Color of team abbreviations — Multi-Color only (default #00d4ff) |

### EAS Settings

| Field | Description |
|---|---|
| Zone IDs | Comma-separated NWS zone codes to monitor (e.g. `OHZ001,OHZ002`). Find yours at [alerts.weather.gov](https://alerts.weather.gov). |
| Poll Interval (seconds) | How often Tickarr checks NWS for new or cleared alerts. Minimum 15s, default 60s. |
| Overlay Style | `broadcast` — TV-station-style bar at the bottom of the screen (recommended). `tickarr` — simpler two-line text overlay. |
| Alert Label Color | Hex color for the severity label box (e.g. `0xCC0000` for red). |
| Severity Filter | Minimum severity to trigger the overlay: Minor, Moderate, Severe, or Extreme. Default: Moderate. |
| Siren Tone Interval (seconds) | How often the EAS attention tone (853+960 Hz dual tone) repeats during an active alert. Set to 0 to disable. Minimum 30s when enabled. |
| EAS Transcode Quality | Output resolution while an alert is active: `full` (source resolution), `1080p30`, `720p`, or `720p30`. Lower quality reduces encoder CPU load. |
| Apply To | Scope of channels to enable EAS on: All Channels, Channel Group, Multiple Groups, or Single Channel. |

---

## Actions Reference

![Actions tab — all available actions](screenshots/actions-top.png)

![Actions tab — Manage section](screenshots/actions-bottom.png)

### Satellite Radio Now Playing

| Action | Description |
|---|---|
| Enable Now Playing | Clones stream profiles for targeted channels and injects the Now Playing overlay. Starts the stellartunerlog.com poller. |
| Disable Now Playing | Restores original stream profiles on all Now Playing channels and removes the cloned profiles. |

### Custom Text

| Action | Description |
|---|---|
| Enable Custom Text | Clones stream profiles and injects the custom text overlay with the current settings. |
| Update Custom Text | Updates the displayed message on active Custom Text channels without disabling and re-enabling. |
| Disable Custom Ticker | Restores original stream profiles on Custom Text channels and removes the cloned profiles. |

### Sports Ticker

| Action | Description |
|---|---|
| Enable Sports Ticker | Clones stream profiles and injects the sports ticker overlay. Starts the ESPN score poller. |
| Disable Sports Ticker | Restores original stream profiles on Sports Ticker channels and removes the cloned profiles. |

### EAS/JAS Weather Alerts

| Action | Description |
|---|---|
| Enable EAS Silent Ticker | Arms the EAS monitor on selected channels. Channels stream normally until an NWS alert fires for your zones, then switch automatically to the EAS overlay profile. |
| Disable EAS Ticker | Restores original stream profiles on all EAS-enabled channels and disarms the monitor. |
| Migrate EAS to Dynamic Mode | One-time migration for users upgrading from the old always-on EAS profile. Restores all EAS channels to passthrough and switches them to dynamic mode. |

### Manage

| Action | Description |
|---|---|
| View Active Tickers | Lists all channels that currently have a Tickarr overlay active, grouped by overlay type. |
| Refresh Channel Data | Reloads the list of Dispatcharr channels and groups used to populate settings dropdowns. |
| Disable All Tickers | Disables every active Tickarr overlay across all channels and restores original profiles. |
| Clean Orphaned Profiles | Removes cloned stream profiles left behind when a channel was deleted while a Tickarr overlay was still active. |
| Redis Diagnostics | Reports how many channels have active viewers detected via Redis, and whether the Redis connection is healthy. |
| Reload Poller | Restarts background polling threads without restarting Dispatcharr. Use this if overlays stop updating but streams are still running. |
| Restart Dispatcharr | Restarts the Dispatcharr container. Required after every plugin install or update. |

---

## Troubleshooting

### Overlay is not appearing after enabling

1. Confirm you ran **Restart Dispatcharr** after installing or updating the plugin.
2. Check that the channel is actively being watched. Tickarr only applies the overlay to channels with active viewers.
3. Wait up to 15 seconds after enabling for the first data to arrive (especially for Now Playing).
4. If the overlay still does not appear, try **Actions → Reload Poller**, then switch away from and back to the channel in your player.

### Overlay is showing stale or incorrect content

Run **Actions → Reload Poller**. This restarts the background polling threads and forces a fresh data fetch. If the overlay is still stale after a minute, disable and re-enable the channel: the disable/enable cycle re-clones the stream profile with current parameters.

### Audio/video sync problems

**Sports Ticker channels:** The scrolling drawtext filter requires video re-encoding, which can introduce pipeline latency. To compensate, sports ticker channels re-encode audio (`-c:a aac`) so audio PTS is regenerated alongside video rather than passed through independently. If you are still experiencing sync drift, disable and re-enable the channel to ensure the current parameters are applied.

**Now Playing and Custom Text channels:** A/V sync issues can occur if the stream profile was cloned with outdated parameters. Disable and re-enable the affected channel to re-clone the profile with the current FFmpeg settings.

### "No games scheduled" in the sports ticker

This is not an error. It means the ESPN API has no live or finished games to report for the leagues you selected right now. The ticker will begin showing scores automatically when games start. Check your league selections to confirm the right leagues are toggled on.

### Channels appear in the wrong group or are missing from dropdowns

Run **Actions → Refresh Channel Data**. This syncs Tickarr's internal channel list with the current state of Dispatcharr. If a channel is still missing, confirm it is managed by Dispatcharr (not an externally managed or passthrough channel) and that it belongs to a channel group.

### Orphaned stream profiles after deleting channels

If you delete a Dispatcharr channel while a Tickarr overlay is active, the cloned stream profile is left behind. Run **Actions → Clean Orphaned Profiles** to remove them.

### Redis errors or zero active channels in diagnostics

Run **Actions → Redis Diagnostics** to check the connection status. If Redis is unreachable, no channels will be detected as active and Tickarr will not apply overlays. Verify that the Redis service is running inside Dispatcharr and that no network configuration is blocking the connection. Restarting Dispatcharr via **Actions → Restart Dispatcharr** will also restart Redis.

### EAS/JAS alert not activating

- Confirm your zone codes at [alerts.weather.gov](https://alerts.weather.gov) — codes are case-sensitive (e.g. `OHZ001` not `ohz001`).
- Confirm the active alert's severity meets or exceeds your **Severity Filter** setting.
- Check the Dispatcharr container logs for any Tickarr EAS errors.

### EAS channel not restoring after alert clears

If Dispatcharr was restarted while an EAS alert was active, the plugin may lose track of the original profile mapping. Run **Actions → Clean Orphaned Profiles** to remove any stuck EAS clone profiles, then manually restore the channel's profile in Dispatcharr if needed.

### Siren tone not playing

- Confirm **Siren Tone Interval** is set to a value greater than 0.
- The tone only applies to profiles cloned after the setting is saved. If an alert was already active when you changed the setting, disable your zones and re-add them to force a fresh profile clone.

### Stream buffering during an EAS alert

EAS re-encodes video to apply the overlay — this uses more CPU than normal passthrough. If buffering persists, try lowering **EAS Transcode Quality** to `720p` or `720p30` to reduce encoder load.

### Plugin changes not taking effect after update

Run **Actions → Restart Dispatcharr**. Dispatcharr caches Python modules at startup; a restart is required for any new or changed plugin code to become active.
