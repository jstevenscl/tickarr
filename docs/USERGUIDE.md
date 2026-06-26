# Tickarr User Guide

Tickarr is a plugin for [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) that adds live text overlays to IPTV channels via FFmpeg. It clones the channel's existing stream profile, injects overlay parameters into the clone, and restores the original when disabled. Your source profiles are never modified.

---

## Table of Contents

1. [Installation](#installation)
2. [Before You Start — Universal Requirements](#before-you-start--universal-requirements)
3. [Satellite Radio Now Playing](#satellite-radio-now-playing)
4. [EAS/JAS Weather Alerts](#easjas-weather-alerts)
5. [Custom Text](#custom-text)
6. [Sports Ticker](#sports-ticker)
7. [Settings Reference](#settings-reference)
8. [Actions Reference](#actions-reference)
9. [Troubleshooting](#troubleshooting)

---

## Installation

1. In Dispatcharr, go to **Plugins → Find Plugins**.
2. Search for **Tickarr** and click **Install**.
3. When installation completes, go to **Tickarr → Actions** and run **Restart Dispatcharr**.

   > **This step is required every time you install or update Tickarr.** Dispatcharr loads plugin code once at startup — without a restart, none of the new code is active.

4. After the page reloads, navigate back to the Tickarr plugin page and continue with the setup section below for the overlay type you want.

---

## Before You Start — Universal Requirements

Before enabling **any** Tickarr overlay on a channel, that channel must have a stream profile assigned to it in Dispatcharr. Tickarr clones that profile to inject the overlay — if the channel has no profile, there is nothing to clone and the enable action will skip the channel.

**How to assign a stream profile:**
1. In Dispatcharr, go to **Channels**.
2. Open the channel you want to enable a Tickarr overlay on.
3. Under **Stream Profile**, choose any active profile.
4. Save.

Repeat for every channel (or use a Channel Group default profile) before running any Tickarr enable action.

---

## Satellite Radio Now Playing

### What it does

Tickarr fetches the currently playing track for each satellite radio station from [stellartunerlog.com](https://stellartunerlog.com) and displays the artist name, song title, and channel name in a centered overlay on the stream. For audio-only channels (no video signal), Tickarr also injects a 1280×720 black video frame so the overlay has something to render on.

The overlay updates automatically as tracks change — no interaction needed after setup.

---

### Step 1 — Set up your satellite radio channels in Dispatcharr

If you have not yet set up channel names, EPG data, sort order, or logos for your satellite radio channels, Tickarr can do all of it. These steps are optional but strongly recommended before enabling Now Playing so that channel matching works correctly.

All four actions below use the same **Apply To** target you configure in Tickarr settings. Scroll to the **Satellite Radio Channel Setup** section in Tickarr settings and select your channel group before running any of these.

| Action | What it does | When to run it |
|---|---|---|
| **Fill EPG — Full Satellite Radio Guide** | Downloads Tickarr's satellite radio EPG and assigns it to the selected channels. Sets tvg-id, channel name, and guide data. | Run this first if your SiriusXM channels have no EPG. |
| **Fill EPG — TVG ID Only** | Sets only the tvg-id on selected channels so they match an EPG source you already have loaded. Does not download guide data. | Use instead of Full EPG if you have an existing EPG source. |
| **Sort Channels** | Renumbers the selected channels by satellite radio lineup order. Fills in the Sort Start Number automatically if left blank. | Run after Fill EPG to put channels in the right order. |
| **Assign Logos** | Sets channel logos from Tickarr's built-in satellite radio library. Channels with no match are skipped. | Run after sorting. |
| **Fill EPG + Sort** | Runs Full EPG fill and Sort together. | Shortcut for the two most common steps. |
| **Fill EPG + Sort + Logos** | Runs all three together. | Recommended for a full first-time setup. |

---

### Step 2 — Configure Now Playing settings

In Tickarr settings, scroll to the **Now Playing** section and fill in the following fields **in order**:

1. **Trigger Mode** — Controls when the overlay is active:
   - **On-Demand (recommended)** — The overlay only activates when someone is watching the channel. When the channel goes idle, it automatically restores to the original passthrough profile. This is the best option for most users because it avoids unnecessary re-encoding on unwatched channels and reduces memory and CPU usage.
   - **Always On** — The overlay encodes 24/7 regardless of viewers. Use this only if you have a specific reason to need the profile always active.

2. **Apply To** — Choose the scope:
   - **All Channels** — Enables Now Playing on every channel Tickarr can see. Use this only if your entire channel library is satellite radio.
   - **Channel Group** — Enables Now Playing on every channel in a specific group. This is the recommended option for most installs where satellite radio channels are in their own group.
   - **Multiple Groups (CSV)** — Enter a comma-separated list of group names to enable across several groups at once.
   - **Single Channel** — Enables Now Playing on one specific channel.

3. Fill in the field that matches your Apply To selection:
   - If **Channel Group**: select the group from the **Channel Group** dropdown.
   - If **Multiple Groups**: type the group names in **Group Names** (e.g. `SiriusXM, Satellite Radio`).
   - If **Single Channel**: select the channel from the **Channel** dropdown.
   - Leave all other target fields blank.

---

### Step 3 — Enable the overlay

Run **Actions → Enable Now Playing**.

Tickarr will:
- In **On-Demand** mode: register the selected channels. No profile clone happens yet. The overlay activates automatically the first time a viewer tunes in.
- In **Always On** mode: clone a stream profile for each selected channel immediately and start the poller.

The action result will confirm how many channels were enabled and how many were skipped (already enabled, no stream profile, etc.).

---

### Step 4 — Verify

- Run **Actions → View Active Tickers** to see a list of all enabled channels grouped by type.
- Tune into one of the enabled channels. The overlay appears within 15 seconds of the first viewer connecting (one poll interval).
- In On-Demand mode: after you stop watching and the channel goes idle for 30 seconds, the overlay is silently removed and the channel returns to passthrough. It reactivates the next time someone tunes in.

---

### Channel name matching

Tickarr matches Dispatcharr channel names to satellite radio stations automatically using fuzzy matching. A channel named `Hits 1` will match `SiriusXM Hits 1` without manual configuration. Running **Fill EPG** first sets standard names that match reliably.

If a channel does not match, run **Actions → Refresh Channel Data** and then re-run the enable action.

---

### Disabling

Run **Actions → Disable Now Playing**. All cloned profiles are deleted and original profiles are restored. In On-Demand mode this also removes any currently-active overlay clones.

---

## EAS/JAS Weather Alerts

> **JAS — jesmannstl Alert System.**
> Dedicated to jesmannstl, a weather fanatic and beloved member of the Dispatcharr community.
> Every alert that fires is a reminder of him. Rest in peace.

---

### What it does

Tickarr monitors NOAA/NWS for active weather alerts in your configured zones. When an alert fires, it automatically switches affected channels to a broadcast-style EAS overlay — a full-width alert bar with a scrolling crawl, colored severity label, and optional attention tone. When the alert clears, channels silently switch back to their normal passthrough profiles. No action is ever required from you.

Your channel runs at full passthrough 100% of the time there is no alert. EAS only re-encodes while an alert is active.

---

### Step 1 — Find your NWS zone codes

Go to [weather.gov](https://www.weather.gov), enter your location, and look for your county or zone code. Codes look like `OHZ001` (zone) or `OHC035` (county).

You can verify a zone code is correct and has active alerts by checking:
`https://api.weather.gov/alerts/active?zone=OHZ001`

To monitor multiple zones (e.g. your county plus surrounding counties), you will enter them all in the next step.

---

### Step 2 — Configure EAS settings

In Tickarr settings, scroll to the **EAS Weather Alerts** section and fill in the following:

1. **Zone IDs** — Enter your zone or county code(s), comma-separated. Example: `OHZ001,OHC035`. No spaces needed. Codes are case-sensitive.

2. **Poll Interval (seconds)** — How often Tickarr checks NWS for new or cleared alerts. Default is 60 seconds. Minimum is 15. Lower values mean faster detection but more API calls.

3. **Overlay Style**:
   - **Broadcast (recommended)** — Dark bar across the bottom with a colored severity label on the left and a scrolling white crawl on the right. Looks like a real TV station alert.
   - **Tickarr** — Simpler two-line text overlay.

4. **Alert Label Color** — Hex color for the severity label box (e.g. `0xCC0000` for red, `0xFF8C00` for orange). This sets the default color; severity automatically overrides it for tornado warnings and other critical events.

5. **Severity Filter** — Minimum severity level to trigger the overlay. Options: Minor, Moderate, Severe, Extreme. Default is Moderate. Set to Extreme if you only want the overlay to fire for the most critical events.

6. **Siren Tone Interval (seconds)** — How often the EAS attention tone (853 Hz + 960 Hz dual tone) repeats during an active alert. Set to `0` to disable the tone entirely. Set to `60` for a tone every minute. Set to `300` for less intrusive toning on long-duration events like flood watches. Minimum is 30 when enabled.

7. **EAS Transcode Quality** — Resolution during an active alert: `full` (source resolution), `1080p30`, `720p`, or `720p30`. Lower quality reduces CPU load. If your server struggles during alerts, try `720p30`.

8. **Test Alert Duration (seconds)** — How long the Test EAS Alert action fires before auto-restoring. Default 60. Range 10–600.

---

### Step 3 — Select your channels

Still in EAS settings:

1. **Apply To** — Choose: All Channels, Channel Group, Multiple Groups (CSV), or Single Channel.
2. Fill in the matching target field (Channel Group dropdown, group name list, or single channel dropdown).

---

### Step 4 — Enable EAS

Run **Actions → Enable EAS Silent Ticker**.

Tickarr registers the selected channels as EAS-armed. No profile is cloned yet. Channels stream normally on their original profiles. The clone only happens when an actual alert fires for your zones.

---

### Step 5 — Test your EAS setup

Before waiting for a real alert, verify your overlay looks correct:

Run **Actions → Test EAS Alert**.

This fires a fake alert on your enabled channel(s) for the duration set in **Test Alert Duration**, then automatically restores passthrough. Use this to confirm:
- The crawl bar appears correctly on screen
- The severity label color is right
- The attention tone fires if configured
- The channel restores cleanly when the test ends

> The test uses your exact configured EAS settings — same overlay style, same tone, same quality. If the test looks right, a real alert will look right too.

---

### How profile switching works

- **Alert fires:** Tickarr clones the channel's current passthrough profile, injects the EAS bar and tone, and assigns the clone. Your original profile is never modified.
- **Alert clears:** The EAS clone is deleted and the original profile is restored automatically. This happens within one poll interval (default 60 seconds).
- **Multiple alerts:** If more than one alert is active simultaneously, the overlay shows `WEATHER ALERT` as the label and the crawl lists all active events. When all alerts clear, the profile restores.

---

### Disabling

Run **Actions → Disable EAS Ticker**. All EAS-armed channels return to their original profiles. If an alert is currently active, the EAS clone is also deleted.

---

## Custom Text

### What it does

Custom Text displays any message you choose on one or more channels. You can show it as static text or a scrolling ticker, position it at the top or bottom, and control whether it is always visible or appears on a timed schedule.

---

### Step 1 — Configure Custom Text settings

In Tickarr settings, scroll to the **Custom Text** section and fill in the following **in order**:

1. **Trigger Mode** — Controls when the overlay profile is active:
   - **On-Demand (recommended)** — No profile is cloned until you set text via **Update Custom Text**. When you clear the text (set it to blank) and run Update again, the overlay removes itself and the channel returns to passthrough. This saves CPU on channels where you only occasionally need a message.
   - **Always On** — A profile is cloned and assigned immediately when you enable, even if text is empty. The overlay encodes 24/7.

2. **Apply To** — Choose: All Channels, Channel Group, Multiple Groups, or Single Channel.

3. Fill in the matching target field (group dropdown, group name list, or channel dropdown). Leave all other target fields blank.

4. **Custom Text** — The message to display. In On-Demand mode you can leave this blank at enable time and set the text later via Update Custom Text. In Always On mode, text is required.

5. **Style**:
   - **Static** — Text stays in a fixed position.
   - **Scrolling** — Text scrolls horizontally across the screen.

6. **Position** — Top or Bottom of the screen.

7. **Schedule**:
   - **Always On** — Text is visible continuously while the channel is running.
   - **Timed** — Text appears for a set number of seconds, disappears, then reappears on a repeating cycle.

8. If you chose **Timed**, set:
   - **Display Duration** — Seconds the text stays visible each cycle.
   - **Repeat Interval** — Minutes between appearances (measured from when the text disappears). Must be longer than Duration.

---

### Step 2 — Enable

Run **Actions → Enable Custom Text**.

- In **On-Demand** mode with no text: Tickarr registers the channels. Nothing else happens until you set text.
- In **On-Demand** mode with text already entered: Tickarr clones profiles and activates the overlay immediately.
- In **Always On** mode: Tickarr clones profiles and writes the text immediately.

---

### Step 3 — Set or change text (On-Demand and Always On)

To set or update the displayed message at any time without disabling:

1. Update the **Custom Text** field with your new message.
2. Run **Actions → Update Custom Text**.

The change takes effect immediately — no stream restart needed.

**To remove the overlay on On-Demand channels:** Clear the Custom Text field (leave it blank) and run **Actions → Update Custom Text**. Tickarr will restore the original passthrough profile and delete the overlay clone.

---

### Disabling

Run **Actions → Disable Custom Ticker**. All cloned profiles are deleted and original profiles are restored.

---

## Sports Ticker

### What it does

The sports ticker pulls live scores from the ESPN API and displays them in a scrolling bar at the top or bottom of the screen. Live games are shown first, followed by final scores. The ticker updates automatically as scores change.

---

### Step 1 — Configure Sports Ticker settings

In Tickarr settings, scroll to the **Sports Ticker** section and fill in the following **in order**:

1. **Trigger Mode** — Controls when the overlay profile is active:
   - **Always On** — The ticker encodes 24/7 regardless of whether any game is in progress. Best if you always want the ticker running.
   - **Active Games Only** — The overlay only activates when at least one of your selected leagues has a live game in progress. When all games end, the channel automatically restores to passthrough. Saves CPU during off-hours and overnight.
   - **Favorite Teams Only** — Same as Active Games Only, but the trigger is narrower: the overlay only fires when one of your favorite teams is currently playing. Requires Favorite Teams to be set (see step 5 below).

2. **Apply To** — Choose: All Channels, Channel Group, Multiple Groups, or Single Channel.

3. Fill in the matching target field. Leave the others blank.

4. **League Selection** — Toggle on the leagues you want to include in the ticker. You can enable as many as you like — sports seasons rarely overlap so enabling several does not usually mean they all appear at once.

   Available leagues: NFL, NCAAF, CFL, NBA, WNBA, NCAAB, MLB, NCAA Baseball, NCAA Softball, NHL, MLS, NWSL, EPL, UCL, La Liga, Bundesliga, Serie A, Ligue 1, ATP, WTA, NCAA Volleyball, NCAA Lacrosse, NASCAR

   > **Tip:** The leagues you toggle on are also the leagues that define the trigger in Active Games Only and Favorite Teams Only modes. If you enable NFL and NHL, the overlay fires when either has a live game.

5. **Favorite Teams** — Optional. Enter team abbreviations comma-separated (e.g. `GB, CHI, DET`). When favorites are set, only games involving those teams appear in the ticker. Required when using **Favorite Teams Only** trigger mode. See [TEAMS.md](TEAMS.md) for all abbreviations by league.

6. **Ticker Position** — Top or Bottom of the screen.

7. **Font Size** — Text size in points. Default 36, minimum 16.

8. **Color Mode**:
   - **Single Color — White (default)** — All ticker text is white. Lower CPU, works on any channel.
   - **Multi-Color** — Sport/league labels and team abbreviations render in separate configurable colors. Requires a monospace bold font inside the Dispatcharr container.

9. If using **Multi-Color**, optionally set:
   - **Label Color** — Color for the sport/league label (default gold, `#ffd700`).
   - **Abbrev Color** — Color for team abbreviations (default `#00d4ff`).

---

### Step 2 — Enable

Run **Actions → Enable Sports Ticker**.

- In **Always On** mode: Tickarr clones profiles and starts the ESPN poller immediately.
- In **Active Games Only** or **Favorite Teams Only** mode: Tickarr registers the channels. The overlay activates automatically when a qualifying live game is detected, and restores to passthrough when all qualifying games end. If no viewers are connected to the channel for 30 seconds after all games end, the passthrough restore is also triggered regardless.

---

### Step 3 — Verify

- Run **Actions → View Active Tickers** to confirm the channels are registered.
- Tune in during a live game to see the ticker fire. During off-hours, in smart trigger modes, the channel will be on passthrough — this is correct behavior.

---

### Notes on ticker capacity

The ticker displays approximately 600 characters of content per pass. When many leagues are enabled and lots of games are in progress, scores that don't fit in the first pass will appear on the next loop. To keep the ticker focused on what you care about, use **Favorite Teams** — this filters the ticker to only those teams regardless of how many leagues are enabled.

---

### Disabling

Run **Actions → Disable Sports Ticker**. All cloned profiles are deleted and original profiles are restored.

---

## Settings Reference

### Now Playing Settings

| Field | Description |
|---|---|
| Trigger Mode | On-Demand (recommended) or Always On — see [Satellite Radio Now Playing](#satellite-radio-now-playing) |
| Apply To | Scope: All Channels, Channel Group, Multiple Groups, or Single Channel |
| Channel Group | The group to enable (visible when Apply To is Channel Group) |
| Group Names | Comma-separated group names (visible when Apply To is Multiple Groups) |
| Channel | The individual channel to enable (visible when Apply To is Single Channel) |

### Custom Text Settings

| Field | Description |
|---|---|
| Trigger Mode | On-Demand (recommended) or Always On |
| Apply To | Scope: All Channels, Channel Group, Multiple Groups, or Single Channel |
| Channel Group / Group Names / Channel | Matching target field for the Apply To selection |
| Custom Text | The message to display. Can be left blank in On-Demand mode. |
| Style | Static (fixed position) or Scrolling (horizontal scroll) |
| Position | Top or Bottom of the screen |
| Schedule | Always On or Timed |
| Display Duration | Seconds the text stays visible per cycle (Timed only) |
| Repeat Interval | Minutes between appearances (Timed only) |

### Sports Ticker Settings

| Field | Description |
|---|---|
| Trigger Mode | Always On, Active Games Only, or Favorite Teams Only |
| Apply To | Scope: All Channels, Channel Group, Multiple Groups, or Single Channel |
| Channel Group / Group Names / Channel | Matching target field |
| League Toggles | One toggle per supported league; enable any combination |
| Favorite Teams | Comma-separated team abbreviations. Required for Favorite Teams Only mode. |
| Ticker Position | Top or Bottom |
| Font Size | Text size in points (default 36, minimum 16) |
| Color Mode | Single Color — White or Multi-Color |
| Label Color | Sport/league label color (Multi-Color only, default `#ffd700`) |
| Abbrev Color | Team abbreviation color (Multi-Color only, default `#00d4ff`) |

### EAS Settings

| Field | Description |
|---|---|
| Zone IDs | Comma-separated NWS zone or county codes (e.g. `OHZ001,OHC035`). Find yours at [weather.gov](https://www.weather.gov). |
| Poll Interval (seconds) | How often Tickarr checks NWS for alerts. Default 60s, minimum 15s. |
| Overlay Style | `broadcast` — TV-style bar at the bottom (recommended). `tickarr` — simpler two-line overlay. |
| Alert Label Color | Hex color for the severity label box (e.g. `0xCC0000`). |
| Severity Filter | Minimum severity to trigger: Minor, Moderate, Severe, or Extreme. Default: Moderate. |
| Siren Tone Interval (seconds) | Seconds between EAS attention tone repetitions (853+960 Hz). Set to 0 to disable. |
| EAS Transcode Quality | Output resolution during alerts: `full`, `1080p30`, `720p`, or `720p30`. Lower = less CPU. |
| Test Alert Duration (seconds) | How long the Test EAS Alert action runs before auto-restoring. Default 60, range 10–600. |
| Apply To | Scope of channels to enable EAS on |

### Satellite Radio Channel Setup Settings

| Field | Description |
|---|---|
| Apply To | Scope to use for all Channel Setup actions (Fill EPG, Sort, Logos) |
| Sort Start Number | Channel number to start from when sorting. Leave blank to auto-detect. |

---

## Actions Reference

### Satellite Radio Now Playing

| Action | Description |
|---|---|
| Enable Now Playing | Registers targeted channels for Now Playing. In On-Demand mode, clones profiles when viewers connect. In Always On mode, clones immediately. |
| Disable Now Playing | Restores original profiles and removes all clones for Now Playing channels. |

### Satellite Radio Channel Setup

| Action | Description |
|---|---|
| Fill EPG — Full Satellite Radio Guide | Downloads Tickarr's satellite radio EPG and assigns it to the selected channels. |
| Fill EPG — TVG ID Only | Sets tvg-id only — use when you already have an EPG source loaded. |
| Sort Channels | Renumbers selected channels by satellite radio lineup order. |
| Assign Logos | Sets logos from Tickarr's built-in satellite radio library. |
| Fill EPG + Sort | Runs Full EPG fill and Sort together. |
| Fill EPG + Sort + Logos | Runs Full EPG fill, Sort, and Logos together. Recommended for first-time setup. |

### Custom Text

| Action | Description |
|---|---|
| Enable Custom Text | Registers channels. In On-Demand mode, clones profile only when text is set. In Always On mode, clones immediately. |
| Update Custom Text | Sets or changes the displayed text. In On-Demand mode, also clones the profile if no overlay is active, or restores passthrough if text is cleared. |
| Disable Custom Ticker | Restores original profiles and removes all clones for Custom Text channels. |

### Sports Ticker

| Action | Description |
|---|---|
| Enable Sports Ticker | Registers channels. In Always On mode, clones immediately. In smart modes, clones when a live qualifying game is detected and restores when all games end. |
| Disable Sports Ticker | Restores original profiles and removes all clones for Sports Ticker channels. |

### EAS/JAS Weather Alerts

| Action | Description |
|---|---|
| Enable EAS Silent Ticker | Arms selected channels for EAS. No profile is cloned until a real alert fires. |
| Test EAS Alert | Fires a fake EAS overlay for the configured Test Alert Duration, then auto-restores. Use this to verify your overlay looks correct without waiting for a real alert. |
| Disable EAS Ticker | Restores original profiles and disarms all EAS-enabled channels. |
| Migrate EAS to Dynamic Mode | One-time migration for users upgrading from an older version of Tickarr that used always-on EAS profiles. Restores all EAS channels to passthrough and re-arms them in dynamic mode. |

### Manage

| Action | Description |
|---|---|
| View Active Tickers | Lists all channels that have a Tickarr overlay registered, grouped by type. Shows which channels have active overlay profiles vs. passthrough. |
| Refresh Channel Data | Reloads the channel and group list from Dispatcharr. Run this if a channel or group is missing from a dropdown. |
| Disable All Tickers | Disables every active Tickarr overlay across all channels. |
| Clean Orphaned Profiles | Removes cloned stream profiles left behind when channels were deleted while a Tickarr overlay was active. |
| Redis Diagnostics | Reports whether Redis is reachable and how many channels have active viewers detected. |
| Reload Poller | Restarts background polling threads without restarting Dispatcharr. Use if overlays stop updating but streams are still live. |
| Restart Dispatcharr | Restarts the Dispatcharr container. Required after every install or update. |

---

## Troubleshooting

### Overlay is not appearing

1. Confirm you ran **Restart Dispatcharr** after installing or updating the plugin.
2. Confirm the channel has a stream profile assigned in Dispatcharr (see [Before You Start](#before-you-start--universal-requirements)).
3. If using **On-Demand** mode: confirm someone is actively watching the channel. The overlay only activates when a viewer is connected. Give it up to 15 seconds on first connect.
4. If using **Active Games Only** or **Favorite Teams Only** for Sports: confirm there is a live qualifying game in progress. During off-hours, this is correct behavior — the channel will be on passthrough.
5. Run **Actions → View Active Tickers** to confirm the channel is registered.
6. Try **Actions → Reload Poller**, then switch away from and back to the channel in your player.

### Overlay shows stale or wrong content

Run **Actions → Reload Poller**. If still stale after 30 seconds, disable and re-enable the channel. The disable/enable cycle re-clones the profile with current parameters and forces a fresh data fetch.

### "No games scheduled" in the sports ticker

This is not an error. The ESPN API has no live or recently finished games for the leagues you selected right now. The ticker will show scores automatically when games start. Confirm your league toggles are set to leagues that are currently in season.

### Channel missing from dropdown

Run **Actions → Refresh Channel Data**, then check that the channel is managed by Dispatcharr, belongs to a channel group, and has a stream profile assigned.

### EAS alert is not firing

- Confirm your zone codes are correct and the alert is actually active for those zones. You can verify at `https://api.weather.gov/alerts/active?zone=OHZ001` (replace with your code).
- Confirm the alert's severity meets or exceeds your **Severity Filter** setting.
- Confirm the alert's status is `actual` (not `test` or `exercise`) — Tickarr filters for real alerts only.
- Run **Test EAS Alert** to verify your EAS setup is working independently of a real alert.
- Check Dispatcharr container logs for any Tickarr EAS errors.

### EAS channel not restoring after alert clears

If Dispatcharr was restarted while an EAS alert was active, the plugin may lose track of the original profile. Run **Actions → Clean Orphaned Profiles**, then manually restore the channel's profile in Dispatcharr if needed.

### Audio/video sync problems

Sports Ticker and EAS overlays require video re-encoding. If you experience A/V drift, disable and re-enable the affected channel — this re-clones the profile with the current FFmpeg parameters and regenerates audio PTS. If problems persist on sports channels, try toggling Single Color mode (lower encoder complexity).

### Siren tone not playing

Confirm **Siren Tone Interval** is greater than 0. The tone only applies to profiles cloned after the setting is saved — if an EAS alert was already active when you changed the setting, it will not apply until the next alert cycle. Use **Test EAS Alert** after saving the new setting to verify.

### Orphaned stream profiles after deleting channels

Run **Actions → Clean Orphaned Profiles**.

### Redis errors or zero active channels

Run **Actions → Redis Diagnostics**. If Redis is unreachable, On-Demand and smart trigger modes will not detect viewers — Tickarr falls back to polling all registered channels. Restart Dispatcharr to restart Redis if needed.

### Plugin changes not taking effect after an update

Run **Actions → Restart Dispatcharr**. Plugin code is cached at startup — a restart is always required after any update.
