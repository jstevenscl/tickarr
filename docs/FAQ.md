# Tickarr FAQ

---

## General

**Q: Do I need to restart Dispatcharr after installing or updating Tickarr?**

Yes. Dispatcharr caches Python modules at startup — new plugin code is not active until you restart. After any install or update, go to **Tickarr → Actions → Restart Dispatcharr**. The page will go offline for about 15 seconds, then come back with the new code loaded.

---

**Q: Will enabling a ticker change my stream quality or original stream profile?**

No. Tickarr clones your existing stream profile and injects the overlay filter into the clone. Your original profile is never modified. When you disable the ticker, the original profile is restored and the clone is deleted.

---

**Q: The overlay is not showing up after I enabled it. What should I check?**

1. Make sure you restarted Dispatcharr after the last install or update.
2. Make sure someone is actively watching the channel. Tickarr only writes overlay data to channels that have active viewers.
3. Wait up to 30 seconds after enabling for the first data to load.
4. Try **Actions → Reload Poller** to restart the background data thread.
5. If still nothing, disable and re-enable the channel to re-clone the stream profile with current parameters.

---

## Sports Ticker

**Q: The ticker says "No games scheduled." Is something broken?**

No — this is normal. It means the ESPN API has no live or recently finished games for the leagues you have enabled right now. This happens during off-hours, between seasons, and on days with no scheduled games. The ticker will start showing scores automatically as soon as games begin. Check your league toggles to make sure the right sports are turned on.

---

**Q: How many games can the ticker show at once?**

The ticker scrolls approximately 600 characters of content per pass. Live games always appear first, followed by final scores. When many leagues are active and there are lots of games in progress, scores that don't fit in the first 600 characters will appear on the next loop — typically a few seconds later.

If you want to make sure specific teams are always visible regardless of how many games are happening, use the **Favorite Teams** field. When favorites are set, only games involving those teams are included in the ticker.

---

**Q: I have a lot of leagues enabled but I'm not seeing my team's game. What's happening?**

The ticker fits roughly 600 characters per scroll pass. If many leagues are active simultaneously, some games may not appear until the next loop. The fix is to enter your teams in the **Favorite Teams** field (comma-separated abbreviations, e.g. `KC, DEN, LAR`). With favorites set, only those teams' games are displayed — the ticker stays focused no matter how many leagues are active.

---

**Q: What's the difference between Single Color and Multi-Color mode?**

- **Single Color (default):** All ticker text is white. Uses one FFmpeg drawtext layer. Lower CPU usage, smoother on lower-powered systems, and recommended for most setups.
- **Multi-Color:** Sport/league labels (NFL:, NBA:, etc.) and team abbreviations are drawn in configurable colors, with scores in white. Uses three drawtext layers — approximately 3× more filter processing. Requires a monospace bold font in the container (DejaVu Mono or Liberation Mono); falls back to Single Color automatically if none is found.

If you are experiencing buffering on a sports ticker channel, try switching to Single Color mode (disable and re-enable the channel after changing the setting).

---

**Q: Why does Multi-Color require a monospace font?**

The three color layers (scores, abbreviations, labels) all scroll at the same speed because they share the same `text_w` measurement. That only works correctly if every character in each layer is the same width — a property guaranteed by monospace fonts. With a proportional font, the layers would have different widths and drift apart visually while scrolling.

---

**Q: The ticker was scrolling smoothly and then started jumping or changing length. What happened?**

This was a known issue in earlier versions caused by the ticker text changing length between ESPN poll cycles (every 30 seconds), which caused FFmpeg to recalculate the scroll width mid-scroll. It is fixed in v0.1.0: all ticker files are always exactly the same length, so the scroll width never changes between reloads.

If you're on v0.1.0 and still seeing this, disable and re-enable the channel to pick up the current parameters.

---

**Q: The stream buffers after enabling the sports ticker. What can I do?**

A few things to check:

1. **Try Single Color mode.** Multi-Color uses three drawtext layers which is more CPU-intensive. Switch to Single Color (disable → change Color Mode setting → re-enable).
2. **Check your base stream profile.** If the channel's original profile contains `-force_key_frames`, older versions of Tickarr would inherit that and produce very high bitrate output. v0.1.0 strips this automatically.
3. **Check your VPN or network.** If Dispatcharr or your IPTV provider routes through a VPN, VPN instability can cause buffering on any transcoded stream. Try disabling the ticker and see if the stream runs clean — if it does and buffering returns only with the ticker, the VPN may be under load.
4. **Run Reload Poller.** A stuck background thread can cause file I/O issues that indirectly stress the encoder.

---

**Q: Can I put the sports ticker on an audio-only channel?**

Yes. Tickarr automatically detects audio-only channels and injects a 1280×720 black video background so the overlay has somewhere to render. The result is a black screen with the scrolling ticker, which is normal and expected for radio-style channels.

---

## Custom Text

**Q: How do I change the text on an active Custom Text channel without interrupting the stream?**

Update the **Custom Text** field with your new message and run **Actions → Update Custom Text**. The new text appears immediately without disabling and re-enabling the channel.

---

**Q: What is the difference between Static and Scrolling style?**

- **Static:** The text stays centered at a fixed position on screen. Good for channel branding, station IDs, or short messages.
- **Scrolling:** The text scrolls horizontally across the screen from right to left. Good for longer messages or news-style tickers.

---

**Q: What does the Timed schedule do?**

Timed mode makes the overlay appear for a set number of seconds, disappear, then reappear on a repeating cycle. For example: Duration = 10 seconds, Interval = 5 minutes means the text shows for 10 seconds, hides for 4 minutes 50 seconds, then shows again for 10 seconds, and so on. Use this when you want a subtle periodic reminder rather than a persistent overlay.

---

**Q: Can I use Custom Text and Sports Ticker on the same channel at the same time?**

No. Each channel supports one active ticker at a time. To switch types, disable the current ticker and enable the new one.

---

## SiriusXM Now Playing

**Q: My SiriusXM channel is showing the channel name but no artist or song. Why?**

The overlay uses fallback content (the channel name) until the first successful poll of xmplaylist.com. This takes up to 15 seconds after enabling. If it never updates, the channel name may not match any station in the xmplaylist database. Run **Actions → Refresh Channel Data** to retry the matching. If still unmatched, the channel name may be too different from the xmplaylist station name to auto-match — this is a known limitation of fuzzy matching.

---

**Q: Does Tickarr support SiriusXM video channels?**

Yes. The Now Playing overlay is designed for audio-only channels (where it injects a black video background), but it will also work on video channels. The overlay box will appear centered on the existing video.

---

**Q: Why is the Now Playing info sometimes a track or two behind?**

xmplaylist.com is a third-party service that scrapes SiriusXM. There is inherent delay between when a track starts playing and when xmplaylist reflects it, typically 30–60 seconds. This is a limitation of the data source, not Tickarr.
