import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths — derived from this file's actual location on disk
# ---------------------------------------------------------------------------

_PLUGIN_DIR        = os.path.dirname(os.path.abspath(__file__))
# Always use a fixed data directory name regardless of versioned install dir
_PLUGINS_DIR       = os.path.dirname(_PLUGIN_DIR)
_DATA_DIR          = os.path.join(_PLUGINS_DIR, "tickarr_data")
TICKER_DIR         = os.path.join(_DATA_DIR, "tickers")
MAPPINGS_FILE      = os.path.join(_DATA_DIR, "mappings.json")
CHANNEL_CACHE_FILE = os.path.join(_DATA_DIR, "channel_cache.json")

# ---------------------------------------------------------------------------
# FFmpeg / StreamProfile helpers
# ---------------------------------------------------------------------------

PROFILE_PREFIX = "Tickarr — "   # em dash

DRAWTEXT_FILTER_TEMPLATE = (
    "drawtext="
    "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ":textfile={ticker_dir}/channel_{channel_id}_header.txt:reload=1"
    ":fontsize=24:fontcolor=white"
    ":x=(w-text_w)/2:y=(h/2-66)"
    ":box=1:boxcolor=black@0.85:boxborderw=4,"
    "drawtext="
    "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ":textfile={ticker_dir}/channel_{channel_id}_artist.txt:reload=1"
    ":fontsize=37:fontcolor=#00d4ff"
    ":x=(w-text_w)/2:y=(h/2-13),"
    "drawtext="
    "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ":textfile={ticker_dir}/channel_{channel_id}_song.txt:reload=1"
    ":fontsize=32:fontcolor=white"
    ":x=(w-text_w)/2:y=(h/2+40),"
    "drawtext="
    "fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ":textfile={ticker_dir}/channel_{channel_id}_channel.txt:reload=1"
    ":fontsize=21:fontcolor=#888888"
    ":x=(w-text_w)/2:y=(h/2+86)"
)

# ---------------------------------------------------------------------------
# Custom text FFmpeg filter templates (Phase 2)
# ---------------------------------------------------------------------------

_FONT_BOLD      = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Resolved once at load time — checked in priority order.
# Multi-color sports ticker requires monospace: same char count → same text_w → sync.
def _resolve_mono_font():
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf",
    ):
        if os.path.exists(path):
            logger.info(f"tickarr: sports ticker mono font: {path}")
            return path
    logger.warning("tickarr: no monospace font found — sports ticker will use single-layer white")
    return ""

_FONT_MONO_BOLD = _resolve_mono_font()

CUSTOM_STATIC_ALWAYS = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_custom.txt:reload=1"
    ":fontsize=48:fontcolor=white"
    ":x=(w-text_w)/2:y={y_expr}"
    ":box=1:boxcolor=black@0.85:boxborderw=6"
)

CUSTOM_SCROLL_ALWAYS = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_custom.txt:reload=1"
    ":fontsize=40:fontcolor=white"
    ":x=w-mod(t*100\\,w+text_w):y={y_expr}"
    ":box=1:boxcolor=black@0.85:boxborderw=6"
)

CUSTOM_STATIC_TIMED = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_custom.txt:reload=1"
    ":fontsize=48:fontcolor=white"
    ":x=(w-text_w)/2:y={y_expr}"
    ":box=1:boxcolor=black@0.85:boxborderw=6"
    ":enable='between(mod(t,{interval_s}),0,{duration_s})'"
)

CUSTOM_SCROLL_TIMED = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_custom.txt:reload=1"
    ":fontsize=40:fontcolor=white"
    ":x=w-mod(mod(t\\,{interval_s})*100\\,w+text_w):y={y_expr}"
    ":box=1:boxcolor=black@0.85:boxborderw=6"
    ":enable='between(mod(t,{interval_s}),0,{duration_s})'"
)

# ---------------------------------------------------------------------------
# Sports ticker FFmpeg filter templates (Phase 3)
# Three synchronized monospace layers drawn in order:
#   1. scores  — white text + background box
#   2. abbrevs — team abbreviation color, no box (overlays scores layer)
#   3. labels  — sport label color, no box (overlays both)
# All three text files are always equal character count.
# Monospace font: equal char count → equal text_w → perfect scroll sync.
# ---------------------------------------------------------------------------

_SPORTS_SCORES_LAYER = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_sports_scores.txt:reload=1"
    ":fontsize={fontsize}:fontcolor=white"
    ":x=w-mod(t*100\\,w+text_w):y={y_expr}"
    ":box=1:boxcolor=black@0.85:boxborderw=6"
)
# Fallback when no monospace font — reads merged full text, single white layer
_SPORTS_SINGLE_LAYER = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_sports_full.txt:reload=1"
    ":fontsize={fontsize}:fontcolor=white"
    ":x=w-mod(t*100\\,w+text_w):y={y_expr}"
    ":box=1:boxcolor=black@0.85:boxborderw=6"
)
_SPORTS_ABBREVS_LAYER = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_sports_abbrevs.txt:reload=1"
    ":fontsize={fontsize}:fontcolor={abbrcolor}"
    ":x=w-mod(t*100\\,w+text_w):y={y_expr}"
    ":box=0"
)
_SPORTS_LABELS_LAYER = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/channel_{channel_id}_sports_labels.txt:reload=1"
    ":fontsize={fontsize}:fontcolor={labelcolor}"
    ":x=w-mod(t*100\\,w+text_w):y={y_expr}"
    ":box=0"
)

# ---------------------------------------------------------------------------
# EAS — Emergency Alert System overlay filter templates
# ---------------------------------------------------------------------------
# EAS Weather Alert — dedicated to jesmannstl
# A Dispatcharr community member and severe weather enthusiast
# whose passion for keeping people informed inspired this feature.
# Rest easy.
# ---------------------------------------------------------------------------
# Alert type: red box, flashing at 1 Hz — centered on screen
_EAS_TYPE_LAYER = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/eas_{channel_id}_type.txt:reload=1"
    ":fontsize=28:fontcolor=white"
    ":x=(w-text_w)/2:y=(h/2)-38"
    ":box=1:boxcolor=0xFF0000@0.92:boxborderw=14"
    ":enable='lt(mod(t\\,1)\\,0.5)'"
)
# Area description: yellow text, black box, static
_EAS_AREA_LAYER = (
    "drawtext="
    "fontfile={font}"
    ":textfile={ticker_dir}/eas_{channel_id}_area.txt:reload=1"
    ":fontsize=18:fontcolor=yellow@0.95"
    ":x=(w-text_w)/2:y=(h/2)+12"
    ":box=1:boxcolor=black@0.82:boxborderw=8"
)


def _inject_drawtext(params, drawtext_filter):
    is_audio_only = "-vn" in params or (
        ("-c:a" in params or "-acodec" in params)
        and "-c:v" not in params
        and "-vcodec" not in params
    )

    if is_audio_only:
        # Remove -vn and existing -map directives (replaced below)
        params = re.sub(r"\s*-vn\b", "", params)
        params = re.sub(r"\s*-map\s+\S+", "", params)
        # Add lavfi black background as second input after the stream URL input
        lavfi = '-f lavfi -i "color=c=black:s=854x480:r=15"'
        params = re.sub(r"(-i\s+\S+)", rf"\1 {lavfi}", params, count=1)
        _fc_graph = f'[1:v]{drawtext_filter}[vout]'
        fc = (
            f'-filter_complex "{_fc_graph}"'
            f' -map "[vout]" -map 0:a:0'
            f' -c:v libx264 -preset ultrafast -tune stillimage -crf 28'
        )
        if "-f mpegts" in params:
            params = params.replace("-f mpegts", f"{fc} -f mpegts")
        elif "pipe:1" in params:
            params = params.replace("pipe:1", f"{fc} pipe:1")
        else:
            params = f"{params} {fc}"
        return params

    # Replace any stream-copy video flag — FFmpeg rejects filters with stream copy.
    # zerolatency removes encoder lookahead/B-frames, so -c:a copy stays in sync
    _VID_ENCODE = "-c:v libx264 -preset ultrafast -tune zerolatency -c:a copy"
    if "-c:v copy" in params:
        params = params.replace("-c:v copy", _VID_ENCODE)
    elif "-vcodec copy" in params:
        params = params.replace("-vcodec copy", _VID_ENCODE)
    # "-c copy" copies ALL streams
    params = re.sub(r'(?<![:\w])-c\s+copy\b', _VID_ENCODE, params)

    # Strip -force_key_frames. In stream-copy profiles this is ignored, but once libx264
    # is active the expression expr:gte(t,n_forced*0) evaluates true on every single frame,
    # forcing all-I-frame output — output bitrate explodes and the encoder can't keep up.
    params = re.sub(r'\s*-force_key_frames\s+"[^"]*"', '', params)
    params = re.sub(r'\s*-force_key_frames\s+\S+', '', params)

    vf_clause = f'-vf "{drawtext_filter}"'

    if "-vf " in params:
        # Prepend drawtext to existing -vf, handling both quoted and unquoted forms
        params = re.sub(r'-vf\s+"([^"]*)"', rf'-vf "{drawtext_filter},\1"', params, count=1)
        if "-vf " in params and f'"{drawtext_filter},' not in params:
            params = re.sub(r'-vf\s+(\S+)', rf'-vf "{drawtext_filter},\1"', params, count=1)
    elif "-f mpegts" in params:
        params = params.replace("-f mpegts", f"{vf_clause} -f mpegts")
    elif "pipe:1" in params:
        params = params.replace("pipe:1", f"{vf_clause} pipe:1")
    else:
        params = params + f" {vf_clause}"

    # Suppress the default 1-second muxer interleave buffer. Without this, FFmpeg
    # buffers up to 1 second of packets to interleave transcoded video against
    # pass-through audio, producing visible startup lag on stream-copy base profiles.
    if "-max_interleave_delta" not in params:
        if "-f mpegts" in params:
            params = params.replace("-f mpegts", "-max_interleave_delta 1 -f mpegts")
        elif "pipe:1" in params:
            params = params.replace("pipe:1", "-max_interleave_delta 1 pipe:1")

    return params




# Flags that must never appear in a Tickarr-cloned profile.
# These cause audio gaps or stream instability on burst-delivered streams (e.g. SiriusXM).
# Only the cloned profile is modified — the original base profile is never touched.
_DANGEROUS_FLAGS = {
    "nobuffer":  "+nobuffer in -fflags causes audio gaps on burst-delivered streams (e.g. SiriusXM via best-streams.tv). FFmpeg passes burst gaps directly to the client with no internal buffering.",
    "low_delay": "-flags low_delay disables decoder delay compensation, causing the same burst-gap disconnects.",
}


def _strip_dangerous_flags(channel_name, params):
    """Strip known problematic FFmpeg flags from cloned profile parameters.
    Logs a clear notification for every flag removed.
    The original base profile is never modified — only the Tickarr clone is cleaned.
    """
    removed = []

    # Strip +nobuffer from -fflags value (e.g. -fflags +discardcorrupt+nobuffer)
    if "nobuffer" in params:
        def _remove_nobuffer(m):
            value = re.sub(r'\+?nobuffer', '', m.group(2))
            value = re.sub(r'\++', '+', value).strip('+')
            if not value:
                return ''
            return m.group(1) + value
        new_params = re.sub(r'(-fflags\s+)(\S+)', _remove_nobuffer, params)
        if new_params != params:
            removed.append("+nobuffer")
            params = new_params

    # Strip -flags low_delay
    if "low_delay" in params:
        new_params = re.sub(r'\s*-flags\s+low_delay\b', '', params)
        if new_params != params:
            removed.append("-flags low_delay")
            params = new_params

    for flag in removed:
        key = flag.lstrip('+-').split()[0]
        reason = _DANGEROUS_FLAGS.get(key, "known to cause stream issues")
        logger.warning(
            f"[Tickarr] Auto-removed {flag} from cloned profile for \"{channel_name}\" "
            f"— {reason} "
            f"Your original base profile is unchanged."
        )

    return params, removed


def _clone_and_inject(channel_id, original_profile, channel_name=""):
    from core.models import StreamProfile
    raw_params = original_profile.parameters or ""
    cleaned_params, removed_flags = _strip_dangerous_flags(
        channel_name or f"channel {channel_id}", raw_params
    )
    drawtext = DRAWTEXT_FILTER_TEMPLATE.format(ticker_dir=TICKER_DIR, channel_id=channel_id)
    params = _inject_drawtext(cleaned_params, drawtext)
    profile = StreamProfile(
        name=f"{PROFILE_PREFIX}{original_profile.name} [ch{channel_id}]",
        command=original_profile.command,
        parameters=params,
        locked=False,
        is_active=True,
    )
    profile.save()
    logger.info(f"tickarr: cloned profile {original_profile.id} → {profile.id} for channel {channel_id}"
                + (f" (removed: {', '.join(removed_flags)})" if removed_flags else ""))
    return profile, removed_flags


def _clone_and_inject_eas(channel_id, original_profile, channel_name=""):
    from core.models import StreamProfile
    raw_params = original_profile.parameters or ""
    cleaned_params, removed_flags = _strip_dangerous_flags(
        channel_name or f"channel {channel_id}", raw_params
    )
    eas_filter = (
        _EAS_TYPE_LAYER.format(font=_FONT_BOLD, ticker_dir=TICKER_DIR, channel_id=channel_id)
        + ","
        + _EAS_AREA_LAYER.format(font=_FONT_BOLD, ticker_dir=TICKER_DIR, channel_id=channel_id)
    )
    params = _inject_drawtext(cleaned_params, eas_filter)
    profile = StreamProfile(
        name=f"{PROFILE_PREFIX}EAS [{original_profile.name}] [ch{channel_id}]",
        command=original_profile.command,
        parameters=params,
        locked=False,
        is_active=True,
    )
    profile.save()
    logger.info(f"tickarr: EAS profile cloned {original_profile.id} → {profile.id} for channel {channel_id}"
                + (f" (removed: {', '.join(removed_flags)})" if removed_flags else ""))
    return profile, removed_flags


def _assign_profile(channel, profile):
    channel.stream_profile = profile
    channel.save(update_fields=["stream_profile"])
    try:
        channel.update_stream_profile(profile.id)
    except Exception:
        pass


def _assign_logo(channel, logo_url, channel_display_name):
    from apps.channels.models import Logo
    try:
        logo, created = Logo.objects.get_or_create(
            url=logo_url,
            defaults={"name": channel_display_name},
        )
        channel.logo = logo
        channel.save(update_fields=["logo"])
        return True, created
    except Exception as e:
        logger.warning(f"tickarr: logo assign failed for {channel_display_name}: {e}")
        return False, False


def _restore_profile(channel, original_profile_id):
    from core.models import StreamProfile
    try:
        original = StreamProfile.objects.get(id=original_profile_id)
        _assign_profile(channel, original)
    except StreamProfile.DoesNotExist:
        channel.stream_profile = None
        channel.save(update_fields=["stream_profile"])


def _delete_cloned_profile(profile_id):
    from core.models import StreamProfile
    try:
        StreamProfile.objects.filter(id=profile_id, name__startswith=PROFILE_PREFIX).delete()
    except Exception as e:
        logger.warning(f"tickarr: could not delete profile {profile_id}: {e}")


def _get_tickarr_profiles():
    from core.models import StreamProfile
    return list(StreamProfile.objects.filter(name__startswith=PROFILE_PREFIX))


def _build_custom_filter(channel_id, style, position, schedule, duration, interval):
    y_map = {
        "top":    "30",
        "center": "(h-text_h)/2",
        "bottom": "h-text_h-30",
    }
    y_expr = y_map.get(position, "h-text_h-30")

    if style == "scrolling" and schedule == "timed":
        template = CUSTOM_SCROLL_TIMED
    elif style == "scrolling":
        template = CUSTOM_SCROLL_ALWAYS
    elif schedule == "timed":
        template = CUSTOM_STATIC_TIMED
    else:
        template = CUSTOM_STATIC_ALWAYS

    return template.format(
        font=_FONT_BOLD,
        ticker_dir=TICKER_DIR,
        channel_id=channel_id,
        y_expr=y_expr,
        duration_s=int(duration),
        interval_s=int(interval) * 60,
    )

# ---------------------------------------------------------------------------
# File writer helpers
# ---------------------------------------------------------------------------


def _ensure_dirs():
    os.makedirs(TICKER_DIR, exist_ok=True)


def _atomic_write(filename, content):
    path = os.path.join(TICKER_DIR, filename)
    tmp = path + f".tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception as e:
        logger.error(f"tickarr: write failed for {filename}: {e}")


def _truncate(text, max_len):
    if not text or len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _write_nowplaying(channel_id, artist, song, channel_name):
    _ensure_dirs()
    _atomic_write(f"channel_{channel_id}_header.txt", "♫ Now Playing ♫")
    _atomic_write(f"channel_{channel_id}_artist.txt", _truncate(artist or "", 38))
    song_text = f'"{_truncate(song, 45)}"' if song else ""
    _atomic_write(f"channel_{channel_id}_song.txt", song_text)
    _atomic_write(f"channel_{channel_id}_channel.txt", channel_name or "")


def _write_custom_text(channel_id, text):
    _ensure_dirs()
    _atomic_write(f"channel_{channel_id}_custom.txt", text or "")


def _write_fallback(channel_id, name, description):
    _ensure_dirs()
    desc = (description or "")[:50] + ("..." if len(description or "") > 50 else "")
    _atomic_write(f"channel_{channel_id}_header.txt", name or "")
    _atomic_write(f"channel_{channel_id}_artist.txt", "")
    _atomic_write(f"channel_{channel_id}_song.txt", "")
    _atomic_write(f"channel_{channel_id}_channel.txt", desc)


def _remove_channel_files(channel_id):
    for suffix in ("header", "artist", "song", "channel"):
        path = os.path.join(TICKER_DIR, f"channel_{channel_id}_{suffix}.txt")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"tickarr: could not remove {path}: {e}")


def _remove_custom_file(channel_id):
    path = os.path.join(TICKER_DIR, f"channel_{channel_id}_custom.txt")
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f"tickarr: could not remove {path}: {e}")


def _write_sports_text(channel_id, labels_text, abbrevs_text, scores_text, full_text=""):
    _ensure_dirs()
    _atomic_write(f"channel_{channel_id}_sports_labels.txt",  labels_text  or "")
    _atomic_write(f"channel_{channel_id}_sports_abbrevs.txt", abbrevs_text or "")
    _atomic_write(f"channel_{channel_id}_sports_scores.txt",  scores_text  or "")
    _atomic_write(f"channel_{channel_id}_sports_full.txt",    full_text    or "")


def _eas_write_alert(channel_id, alert):
    _ensure_dirs()
    _atomic_write(f"eas_{channel_id}_type.txt", f"⚠  {alert['event'].upper()}  ⚠")
    area = (alert.get("area") or "").replace("; ", " · ")
    _atomic_write(f"eas_{channel_id}_area.txt", _truncate(area, 60))


def _eas_clear(channel_id):
    _ensure_dirs()
    _atomic_write(f"eas_{channel_id}_type.txt", "")
    _atomic_write(f"eas_{channel_id}_area.txt", "")


def _fetch_nws_alerts(zones, severity_threshold="Moderate"):
    zone_str = ",".join(z.upper() for z in zones if z.strip())
    if not zone_str:
        return []
    url = f"{NWS_ALERTS_URL}?zone={zone_str}&status=Actual"
    req = urllib.request.Request(url, headers={
        "User-Agent": NWS_UA,
        "Accept": "application/geo+json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    min_sev = _EAS_SEV.get(severity_threshold, 2)
    alerts = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if props.get("status") != "Actual":
            continue
        if props.get("urgency") in ("Past", "Unknown"):
            continue
        if _EAS_SEV.get(props.get("severity", "Unknown"), 0) < min_sev:
            continue
        alerts.append({
            "id":       props.get("id", ""),
            "event":    props.get("event", "Weather Alert"),
            "area":     props.get("areaDesc", ""),
            "severity": props.get("severity", "Unknown"),
            "expires":  props.get("expires", ""),
        })
    return alerts


def _eas_sweep():
    settings = _get_settings()
    zones_raw = (settings.get("eas_zones") or "").strip()
    if not zones_raw:
        return
    zones = [z.strip() for z in zones_raw.split(",") if z.strip()]
    severity_threshold = settings.get("eas_severity_filter") or "Moderate"
    mappings = _get_mappings()
    eas_cids = [cid for cid, m in mappings.items() if m and m.get("type") == "eas"]
    if not eas_cids:
        return
    try:
        alerts = _fetch_nws_alerts(zones, severity_threshold)
    except Exception as e:
        logger.warning(f"[Tickarr] EAS: NWS fetch failed: {e}")
        return
    worst = (max(alerts, key=lambda a: _EAS_SEV.get(a["severity"], 0)) if alerts else None)
    with _eas_lock:
        for cid in eas_cids:
            active = _eas_active.get(cid)
            if worst:
                if active != worst["event"]:
                    _eas_write_alert(cid, worst)
                    _eas_active[cid] = worst["event"]
                    if not active:
                        logger.info(f"[Tickarr] EAS ALERT: {worst['event']} — {worst['area'][:60]} (ch {cid})")
            else:
                if active:
                    _eas_clear(cid)
                    _eas_active.pop(cid, None)
                    logger.info(f"[Tickarr] EAS: alert cleared — ch {cid}")


def _eas_sweep_loop(stop_event):
    # EAS Weather Alert — dedicated to jesmannstl
    # A Dispatcharr community member and severe weather enthusiast
    # whose passion for keeping people informed inspired this feature.
    # Rest easy.
    logger.info("[Tickarr] EAS module initialized — for jesmannstl, who understood why this matters.")
    while not stop_event.is_set():
        try:
            interval = max(15, int((_get_settings().get("eas_poll_interval") or 60)))
        except Exception:
            interval = 60
        try:
            _eas_sweep()
        except Exception as e:
            logger.error(f"[Tickarr] EAS loop error: {e}", exc_info=True)
        stop_event.wait(timeout=interval)


def _remove_sports_file(channel_id):
    for fname in (f"channel_{channel_id}_sports_labels.txt",
                  f"channel_{channel_id}_sports_abbrevs.txt",
                  f"channel_{channel_id}_sports_scores.txt",
                  f"channel_{channel_id}_sports_full.txt",
                  f"channel_{channel_id}_sports.txt"):   # legacy
        path = os.path.join(TICKER_DIR, fname)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"tickarr: could not remove {path}: {e}")




# ---------------------------------------------------------------------------
# Channel cache helpers
# ---------------------------------------------------------------------------

CACHE_TTL = 7 * 24 * 3600

# Bundled channel data ships inside the plugin directory alongside plugin.py.
# No EPGeditARR dependency at runtime — data updates with each Tickarr release.
_BUNDLED_CHANNELS = os.path.join(_PLUGIN_DIR, "channels.json")
_BUNDLED_ALIASES  = os.path.join(_PLUGIN_DIR, "channel_aliases.json")


def _get_channel_data(force=False):
    if not force and os.path.exists(CHANNEL_CACHE_FILE):
        try:
            with open(CHANNEL_CACHE_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("fetched_at", 0) + CACHE_TTL > time.time() and cache.get("channels"):
                return cache["channels"], cache.get("aliases", {})
        except Exception:
            pass

    channels, aliases = {}, {}

    # Load channels — bundled file is authoritative
    if os.path.exists(_BUNDLED_CHANNELS):
        try:
            with open(_BUNDLED_CHANNELS, encoding="utf-8") as f:
                channels = json.load(f)
            logger.info(f"tickarr: loaded {len(channels)} channels from bundled channels.json")
        except Exception as e:
            logger.error(f"tickarr: failed to load bundled channels.json: {e}")
    else:
        logger.warning("tickarr: bundled channels.json not found — channel matching unavailable")

    # Load aliases — bundled file, flat dict format
    if os.path.exists(_BUNDLED_ALIASES):
        try:
            with open(_BUNDLED_ALIASES, encoding="utf-8") as f:
                raw = json.load(f)
            # Support both flat dict and wrapped {"aliases": {...}} format
            aliases = raw.get("aliases", raw) if isinstance(raw, dict) and "aliases" in raw else raw
            logger.info(f"tickarr: loaded {len(aliases)} aliases from bundled channel_aliases.json")
        except Exception as e:
            logger.error(f"tickarr: failed to load bundled channel_aliases.json: {e}")

    if channels:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = CHANNEL_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": time.time(), "channels": channels, "aliases": aliases}, f)
        os.replace(tmp, CHANNEL_CACHE_FILE)

    return channels, aliases


def _match_channel(dispatcharr_name, channels, aliases):
    normalized = _normalize(dispatcharr_name)
    lookup_lower = dispatcharr_name.lower()
    for alias, canonical in (aliases.items() if isinstance(aliases, dict) else []):
        if _normalize(alias) == normalized:
            normalized = _normalize(canonical)
            lookup_lower = canonical.lower()
            break
    if isinstance(channels, dict):
        # channels.json keyed by name.lower() (e.g. "1st wave"), not fully normalized
        return channels.get(normalized) or channels.get(lookup_lower)
    for ch in channels:
        if _normalize(ch.get("name", "")) == normalized:
            return ch
    return None


def _normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _get_mappings():
    try:
        if os.path.exists(MAPPINGS_FILE):
            with open(MAPPINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"tickarr: failed to read mappings: {e}")
    return {}


def _save_mappings(mappings):
    global _uuid_map_cache
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = MAPPINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mappings, f, indent=2)
        os.replace(tmp, MAPPINGS_FILE)
        _uuid_map_cache = {"map": {}, "fetched_at": 0}  # force refresh on next scan
    except Exception as e:
        logger.error(f"tickarr: failed to save mappings: {e}")


def _get_settings():
    from apps.plugins.models import PluginConfig
    config = PluginConfig.objects.filter(key="tickarr").first()
    if not config or not config.settings:
        return {}
    settings = dict(config.settings)
    settings.pop("channel_mappings", None)
    settings.pop("channel_cache", None)
    return settings

# ---------------------------------------------------------------------------
# Sports ticker — ESPN client (Phase 3)
# ---------------------------------------------------------------------------

ESPN_PATHS = {
    'nfl':        'sports/football/nfl',
    'ncaafb':     'sports/football/college-football',
    'cfl':        'sports/football/cfl',
    'nba':        'sports/basketball/nba',
    'wnba':       'sports/basketball/wnba',
    'ncaamb':     'sports/basketball/mens-college-basketball',
    'mlb':        'sports/baseball/mlb',
    'ncaabase':   'sports/baseball/college-baseball',
    'ncaasb':     'sports/baseball/college-softball',
    'nhl':        'sports/hockey/nhl',
    'mls':        'sports/soccer/usa.1',
    'nwsl':       'sports/soccer/usa.nwsl',
    'epl':        'sports/soccer/eng.1',
    'ucl':        'sports/soccer/uefa.champions',
    'laliga':     'sports/soccer/esp.1',
    'bundesliga': 'sports/soccer/ger.1',
    'seriea':     'sports/soccer/ita.1',
    'ligue1':     'sports/soccer/fra.1',
    'atp':        'sports/tennis/atp',
    'wta':        'sports/tennis/wta',
    'ncaavb':     'sports/volleyball/womens-college-volleyball',
    'ncaalax':    'sports/lacrosse/womens-college-lacrosse',
}
LABELS = {
    'nfl': 'NFL', 'ncaafb': 'NCAAF', 'cfl': 'CFL',
    'nba': 'NBA', 'wnba': 'WNBA', 'ncaamb': 'NCAAB',
    'mlb': 'MLB', 'ncaabase': 'NCAA Baseball', 'ncaasb': 'NCAA Softball',
    'nhl': 'NHL',
    'mls': 'MLS', 'nwsl': 'NWSL', 'epl': 'EPL', 'ucl': 'UCL',
    'laliga': 'La Liga', 'bundesliga': 'Bundesliga',
    'seriea': 'Serie A', 'ligue1': 'Ligue 1',
    'atp': 'ATP', 'wta': 'WTA',
    'ncaavb': 'NCAA VB', 'ncaalax': 'NCAA Lax',
    'nascar': 'NASCAR',
}
KNOWN_SPORTS = list(ESPN_PATHS.keys()) + ['nascar']

_sports_text_cache = {"key": None, "labels": "", "abbrevs": "", "scores": "", "full": "", "fetched_at": 0.0}
SPORTS_CACHE_TTL = 30  # seconds

# EAS globals
NWS_ALERTS_URL  = "https://api.weather.gov/alerts/active"
NWS_UA          = "Tickarr/0.2 (github.com/jstevenscl/tickarr)"
_EAS_SEV        = {"Unknown": 0, "Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}
_eas_active     = {}   # channel_id → alert event string when alert is active
_eas_lock       = threading.Lock()
_TICKER_FIXED_LEN = 600  # all ticker strings are always exactly this many chars
# Fixed length keeps text_w constant across reloads — prevents scroll position jumping
# when game count changes between ESPN polls. Content beyond 600 chars is truncated
# (live games come first so the most important scores are always visible).


def _build_sports_filter(channel_id, position="bottom", fontsize=36,
                         labelcolor="#ffd700", abbrcolor="#00d4ff",
                         color_mode="single"):
    y_map = {"top": "30", "center": "(h-text_h)/2", "bottom": "h-text_h-30"}
    y_expr = y_map.get(position, "h-text_h-30")
    fs = int(fontsize)
    x_expr = "w-mod(t*100\\,w+text_w)"
    use_multi = (color_mode == "multi") and bool(_FONT_MONO_BOLD)
    if use_multi:
        tmpl_scores  = _SPORTS_SCORES_LAYER.replace("w-mod(t*100\\\\,w+text_w)", x_expr).replace("w-mod(t*100\\,w+text_w)", x_expr)
        tmpl_abbrevs = _SPORTS_ABBREVS_LAYER.replace("w-mod(t*100\\\\,w+text_w)", x_expr).replace("w-mod(t*100\\,w+text_w)", x_expr)
        tmpl_labels  = _SPORTS_LABELS_LAYER.replace("w-mod(t*100\\\\,w+text_w)", x_expr).replace("w-mod(t*100\\,w+text_w)", x_expr)
        kwargs = dict(font=_FONT_MONO_BOLD, ticker_dir=TICKER_DIR,
                      fontsize=fs, channel_id=channel_id, y_expr=y_expr)
        scores_layer  = tmpl_scores.format(**kwargs)
        abbrevs_layer = tmpl_abbrevs.format(**kwargs, abbrcolor=abbrcolor)
        labels_layer  = tmpl_labels.format(**kwargs, labelcolor=labelcolor)
        return f"{scores_layer},{abbrevs_layer},{labels_layer}"
    else:
        font = _FONT_MONO_BOLD or _FONT_BOLD
        tmpl = _SPORTS_SINGLE_LAYER.replace("w-mod(t*100\\\\,w+text_w)", x_expr).replace("w-mod(t*100\\,w+text_w)", x_expr)
        return tmpl.format(
            font=font, ticker_dir=TICKER_DIR,
            fontsize=fs, channel_id=channel_id, y_expr=y_expr,
        )


def _game_seg_triple(away_abbr, away_score, home_abbr, home_score, suffix):
    """Build equal-length (label_seg, abbrev_seg, score_seg) for one game.
    label_seg  = all spaces (labels live at the sport section level, not game level).
    abbrev_seg = team abbreviations at their positions, spaces elsewhere.
    score_seg  = scores/status at their positions, spaces for abbreviations.
    All three strings have identical character count — monospace scroll sync.
    """
    mid  = f" {away_score} @ "
    rest = f" {home_score} {suffix}"
    total = len(away_abbr) + len(mid) + len(home_abbr) + len(rest)
    label_seg  = " " * total
    abbrev_seg = f"{away_abbr}{' ' * len(mid)}{home_abbr}{' ' * len(rest)}"
    score_seg  = f"{' ' * len(away_abbr)}{mid}{' ' * len(home_abbr)}{rest}"
    return label_seg, abbrev_seg, score_seg


def _sport_section_triple(sport_label, game_triples):
    """Assemble per-game triples into a full sport section triple.
    Prepends 'SPORT: ' — the label goes in the label layer, spaces fill the others.
    """
    lbl = sport_label + ":"
    sep = "  "
    l_parts, a_parts, s_parts = [], [], []
    for (l, a, s) in game_triples:
        l_parts.append(l)
        a_parts.append(a)
        s_parts.append(s)
    combined_l = sep.join(l_parts)
    combined_a = sep.join(a_parts)
    combined_s = sep.join(s_parts)
    prefix_len = len(lbl) + 1  # "NFL: "
    label_seg  = lbl + " " * (1 + len(combined_s))
    abbrev_seg = " " * prefix_len + combined_a
    score_seg  = " " * prefix_len + combined_s
    return label_seg, abbrev_seg, score_seg


def _fetch_sports_text(sports_list, favorites=""):
    """Fetch scores from ESPN (and NASCAR live feed).

    Returns (labels_text, abbrevs_text, scores_text, full_text) — equal-length strings.
    All three text strings are padded to the same length for monospace scroll sync.
    """
    global _sports_text_cache
    cache_key = (tuple(sorted(sports_list)), (favorites or "").strip().upper())
    now = time.time()
    if (_sports_text_cache["key"] == cache_key and
            now - _sports_text_cache["fetched_at"] < SPORTS_CACHE_TTL):
        return (_sports_text_cache["labels"],
                _sports_text_cache["abbrevs"],
                _sports_text_cache["scores"],
                _sports_text_cache.get("full", ""))

    fav_set = set(a.strip().upper() for a in favorites.split(",") if a.strip()) if favorites else set()
    live_triples  = []
    final_triples = []

    for sport_id in sports_list:
        label = LABELS.get(sport_id, sport_id.upper())
        try:
            if sport_id in ESPN_PATHS:
                url = f'https://site.api.espn.com/apis/site/v2/{ESPN_PATHS[sport_id]}/scoreboard'
                req = urllib.request.Request(url, headers={"User-Agent": "Tickarr/0.1"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read())
                events = data.get('events', [])
                live_games  = []
                final_games = []
                for ev in events[:30]:
                    comp = ev.get('competitions', [{}])[0]
                    competitors = comp.get('competitors', [])
                    if len(competitors) < 2:
                        continue
                    home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                    away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
                    away_abbr = away.get('team', {}).get('abbreviation', '?')
                    home_abbr = home.get('team', {}).get('abbreviation', '?')
                    if fav_set and away_abbr.upper() not in fav_set and home_abbr.upper() not in fav_set:
                        continue
                    away_score = away.get('score', '')
                    home_score = home.get('score', '')
                    st    = comp.get('status', {}).get('type', {})
                    state = st.get('state', '')
                    detail = st.get('shortDetail', '')
                    if state == 'in':
                        live_games.append(
                            _game_seg_triple(away_abbr, away_score, home_abbr, home_score, f"({detail})"))
                    elif state == 'post':
                        final_games.append(
                            _game_seg_triple(away_abbr, away_score, home_abbr, home_score, "FINAL"))
                if live_games:
                    live_triples.append(_sport_section_triple(label, live_games))
                if final_games:
                    final_triples.append(_sport_section_triple(label, final_games))

            elif sport_id == 'nascar':
                nascar_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://www.nascar.com/',
                    'Origin': 'https://www.nascar.com',
                }
                req = urllib.request.Request(
                    'https://cf.nascar.com/live/feeds/live-feed.json',
                    headers=nascar_headers,
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    lf = json.loads(r.read())
                if lf.get('series_id') == 1 and 1 <= lf.get('flag_state', 0) <= 8:
                    run_name = lf.get('run_name', '')
                    lap   = lf.get('lap_number', 0)
                    total = lf.get('laps_in_race', 0)
                    vehicles = sorted(lf.get('vehicles', []), key=lambda v: v.get('running_position', 99))
                    d_strs = []
                    for v in vehicles[:5]:
                        pos    = v.get('running_position', '')
                        driver = v.get('driver', {})
                        name   = (driver.get('full_name') or
                                  f"{driver.get('first_name', '')} {driver.get('last_name', '')}").strip()
                        d_strs.append(f'P{pos} {name.split()[-1] if name else "?"}')
                    lap_str = f'Lap {lap}/{total}' if total else ''
                    if d_strs:
                        lbl     = f"NASCAR ({run_name}):"
                        content = f" {'  '.join(d_strs)}  {lap_str}"
                        seg_len = len(lbl) + len(content)
                        live_triples.append((
                            lbl + " " * len(content),  # label layer
                            " " * seg_len,             # abbrev layer (no discrete abbrevs)
                            " " * len(lbl) + content,  # score layer
                        ))

        except Exception as e:
            logger.warning(f"tickarr: sports fetch error for {sport_id}: {e}")

    all_triples = live_triples + final_triples
    if not all_triples:
        labels_text = abbrevs_text = scores_text = ""
    else:
        sep_scores = "    |    "   # 9 chars ASCII — visible separator in scores layer
        sep_blank  = "         "   # 9 spaces — invisible in label/abbrev layers

        unit_l = sep_blank.join(t[0] for t in all_triples)
        unit_a = sep_blank.join(t[1] for t in all_triples)
        unit_s = sep_scores.join(t[2] for t in all_triples)

        rep_l, rep_a, rep_s = unit_l, unit_a, unit_s
        while len(rep_s) < _TICKER_FIXED_LEN:
            rep_l += sep_blank  + unit_l
            rep_a += sep_blank  + unit_a
            rep_s += sep_scores + unit_s

        # Enforce exact fixed length across all three layers.
        # Constant char count → constant text_w → scroll position never jumps on reload.
        labels_text  = rep_l[:_TICKER_FIXED_LEN].ljust(_TICKER_FIXED_LEN)
        abbrevs_text = rep_a[:_TICKER_FIXED_LEN].ljust(_TICKER_FIXED_LEN)
        scores_text  = rep_s[:_TICKER_FIXED_LEN].ljust(_TICKER_FIXED_LEN)

    # Build full merged text for single-layer fallback (used when no mono font).
    # Each position has at most one non-space char across the three layers.
    if labels_text:
        merged_chars = []
        for l, a, s in zip(labels_text, abbrevs_text, scores_text):
            merged_chars.append(l if l != ' ' else (a if a != ' ' else s))
        full_text = "".join(merged_chars)
    else:
        full_text = ""

    _sports_text_cache = {
        "key":        cache_key,
        "labels":     labels_text,
        "abbrevs":    abbrevs_text,
        "scores":     scores_text,
        "full":       full_text,
        "target_len": len(labels_text),
        "fetched_at": now,
    }
    return labels_text, abbrevs_text, scores_text, full_text

# ---------------------------------------------------------------------------
# tickarr.com data client (replaces xmplaylist.com)
# ---------------------------------------------------------------------------

TICKARR_NOWPLAYING_URL = "https://stellartunerlog.com/nowplaying.json"
TICKARR_CHANNEL_URL    = "https://stellartunerlog.com/channels.json"
TICKARR_SXM_EPG_URL    = "https://jstevenscl.github.io/tickarr/lib/satellite_radio_epg.xml"
TICKARR_SXM_SOURCE     = "Tickarr: Satellite Radio"
STATION_CACHE_TTL      = 24 * 3600
STATION_CACHE_FILE     = os.path.join(_DATA_DIR, "station_cache.json")
NOWPLAYING_CACHE_TTL   = 30   # seconds — matches stellartunerlog.com update interval

XMPLAYLIST_STATION_URL  = "https://xmplaylist.com/api/station/{deeplink}"
XMPLAYLIST_MIN_INTERVAL = 1.5  # seconds between per-channel requests

# cut_type values that indicate non-song content (talk, ads, promos, etc.)
_NON_SONG_CUT_TYPES = frozenset({"talk", "exp", "perm", "pgm_segment", "link", "spot", "promo"})
# subset where STL artist field contains an actual program/show name worth displaying
# "spot"/"promo" excluded — their artist field contains ad/promo copy, not program names
_PROGRAM_CUT_TYPES  = frozenset({"talk", "pgm_segment", "exp", "perm", "link"})

_station_cache    = {"fetched_at": 0, "stations": []}
_nowplaying_cache = {"fetched_at": 0.0, "stations": {}}
_nowplaying_lock  = threading.Lock()
_xmplaylist_lock  = threading.Lock()
_xmplaylist_last  = {"time": 0.0}


def _get_stations(force=False):
    """Fetch channel catalog from tickarr.com/channels.json (24h TTL, disk-cached)."""
    global _station_cache
    now = time.time()
    if not force and _station_cache["fetched_at"] + STATION_CACHE_TTL > now and _station_cache["stations"]:
        return _station_cache["stations"]
    if not force and os.path.exists(STATION_CACHE_FILE):
        try:
            with open(STATION_CACHE_FILE, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fetched_at", 0) + STATION_CACHE_TTL > now and cached.get("stations"):
                _station_cache = cached
                logger.debug(f"tickarr: channel list loaded from disk ({len(cached['stations'])} channels)")
                return cached["stations"]
        except Exception:
            pass
    try:
        req = urllib.request.Request(TICKARR_CHANNEL_URL, headers={"User-Agent": "Tickarr/0.1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        stations = list((data.get("channels") or {}).values())
        _station_cache = {"fetched_at": now, "stations": stations}
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = STATION_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_station_cache, f)
        os.replace(tmp, STATION_CACHE_FILE)
        logger.info(f"tickarr: fetched {len(stations)} channels from tickarr.com")
        return stations
    except Exception as e:
        logger.error(f"tickarr: channel list fetch failed: {e}")
        return _station_cache.get("stations") or []


def _get_nowplaying_bulk():
    """Fetch all channels' now-playing from tickarr.com in one request (30s TTL)."""
    global _nowplaying_cache
    now = time.time()
    with _nowplaying_lock:
        if now - _nowplaying_cache["fetched_at"] < NOWPLAYING_CACHE_TTL and _nowplaying_cache["stations"]:
            return _nowplaying_cache["stations"]
    try:
        req = urllib.request.Request(TICKARR_NOWPLAYING_URL, headers={"User-Agent": "Tickarr/0.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        stations = data.get("stations") or {}
        with _nowplaying_lock:
            _nowplaying_cache = {"fetched_at": time.time(), "stations": stations}
        return stations
    except Exception as e:
        logger.warning(f"tickarr: nowplaying bulk fetch failed: {e}")
        return _nowplaying_cache.get("stations") or {}


def _xmplaylist_fetch(deeplink):
    """Per-channel xmplaylist.com fallback with rate limiting.
    Returns (artist, song) strings, or (None, None) on failure.
    Only called when stellartunerlog.com bulk data is available but missing this channel.
    """
    global _xmplaylist_last
    with _xmplaylist_lock:
        elapsed = time.time() - _xmplaylist_last["time"]
        if elapsed < XMPLAYLIST_MIN_INTERVAL:
            time.sleep(XMPLAYLIST_MIN_INTERVAL - elapsed)
        try:
            url = XMPLAYLIST_STATION_URL.format(deeplink=deeplink)
            req = urllib.request.Request(url, headers={"User-Agent": "Tickarr/0.1"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            _xmplaylist_last["time"] = time.time()
            if data and isinstance(data, list) and data[0].get("track"):
                track  = data[0]["track"]
                artist = (track.get("artists") or [""])[0]
                song   = track.get("title", "")
                return artist or "", song or ""
        except Exception as e:
            logger.debug(f"tickarr: xmplaylist fallback failed for {deeplink}: {e}")
        _xmplaylist_last["time"] = time.time()
    return None, None


def _match_station_by_uuid(uuid, stations):
    # tickarr.com channels.json uses "guid" for the SiriusXM UUID
    for s in stations:
        if s.get("guid") == uuid:
            return s
    return None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match_station_by_name(channel_name, stations):
    if not stations:
        return None
    n = _norm(channel_name)

    # Pass 1: exact normalized name, deeplink_id, or id match
    for s in stations:
        if (_norm(s.get("name", "")) == n
                or _norm(s.get("deeplink_id", "")) == n
                or _norm(s.get("id", "")) == n):
            return s

    # Pass 2: strip leading "siriusxm" from channel name
    n2 = re.sub(r"^siriusxm", "", n)
    if n2 and n2 != n:
        for s in stations:
            sn = _norm(s.get("name", ""))
            dl = _norm(s.get("deeplink_id", ""))
            di = _norm(s.get("id", ""))
            if sn == n2 or dl == n2 or di == n2:
                return s

    # Pass 3: strip leading "siriusxm" from station name
    for s in stations:
        sn = re.sub(r"^siriusxm", "", _norm(s.get("name", "")))
        if sn and sn == n:
            return s

    # Pass 4: channel number match
    try:
        num_match = re.search(r'\b(\d+)\b', channel_name)
        if num_match:
            num = int(num_match.group(1))
            for s in stations:
                if s.get("channel_number") == num:
                    return s
    except Exception:
        pass

    # Pass 5: one name fully contains the other (min 5 chars to avoid false positives)
    if len(n) >= 5:
        for s in stations:
            sn = _norm(s.get("name", ""))
            if len(sn) >= 5 and (sn in n or n in sn):
                return s

    # Pass 6: strip trailing "radio" from channel name, then rematch
    n6 = re.sub(r"radio$", "", n)
    if n6 and n6 != n:
        for s in stations:
            if (_norm(s.get("name", "")) == n6
                    or _norm(s.get("deeplink_id", "")) == n6
                    or _norm(s.get("id", "")) == n6):
                return s

    # Pass 7: strip trailing "radio" from station name/id, then rematch
    for s in stations:
        sn = re.sub(r"radio$", "", _norm(s.get("name", "")))
        dl = re.sub(r"radio$", "", _norm(s.get("deeplink_id", "")))
        di = re.sub(r"radio$", "", _norm(s.get("id", "")))
        if (sn and sn == n) or (dl and dl == n) or (di and di == n):
            return s

    return None


# ---------------------------------------------------------------------------
# Scheduler / poll loop
# ---------------------------------------------------------------------------

_scheduler_thread = None
_stop_event = threading.Event()
_redis_client_cache = None
_redis_client_lock = threading.Lock()

STALE_THRESHOLD   = 120   # seconds — channels not updated in this long get auto-refreshed
STALE_BATCH_SIZE  = 10    # max stale channels to recover per sweep

# UUID→integer channel ID cache (refreshed every 5 min)
_uuid_map_cache = {"map": {}, "fetched_at": 0}
UUID_MAP_TTL = 300

# Distributed lock keys — one winner per loop across all uWSGI workers
SWEEP_LOCK_KEY   = "tickarr:sweep_lock"
FAST_LOCK_KEY    = "tickarr:fast_lock"
SPORTS_LOCK_KEY  = "tickarr:sports_lock"
_SWEEP_LOCK_TTL  = 45   # SWEEP_SLEEP(15) + up to 10s poll + 20s buffer; refreshed post-sweep
_FAST_LOCK_TTL   = 10   # renewed every 2s tick; 10s crash-recovery window
_SPORTS_LOCK_TTL = 60   # SPORTS_SWEEP_SLEEP(30) + poll time + buffer; refreshed post-sweep


def _get_redis_client():
    global _redis_client_cache
    with _redis_client_lock:
        if _redis_client_cache is not None:
            try:
                _redis_client_cache.ping()
                return _redis_client_cache
            except Exception:
                _redis_client_cache = None
        try:
            from django_redis import get_redis_connection
            rc = get_redis_connection("default")
            rc.ping()
            _redis_client_cache = rc
            return rc
        except Exception:
            pass
        try:
            from django.conf import settings as _settings
            import redis as _redis
            url = (getattr(_settings, "REDIS_URL", None)
                   or getattr(_settings, "CACHES", {}).get("default", {}).get("LOCATION")
                   or "redis://redis:6379/0")
            rc = _redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            rc.ping()
            _redis_client_cache = rc
            return rc
        except Exception:
            pass
        return None


def _redis_lock_acquire_or_refresh(rc, key, ttl):
    """Acquire or renew a Redis distributed lock for this process.
    Returns True if this worker holds the lock, False if another worker holds it.
    On first call uses NX-set; on subsequent calls by the same pid, refreshes TTL."""
    my_pid = str(os.getpid())
    if rc.set(key, my_pid, nx=True, ex=ttl):
        return True
    current = rc.get(key)
    if current and current.decode() == my_pid:
        rc.expire(key, ttl)
        return True
    return False


def _get_uuid_to_id_map(mappings):
    """Returns {uuid_str: int_channel_id} for all currently mapped channels.
    Cached for UUID_MAP_TTL seconds to avoid hitting the DB on every 2s tick."""
    global _uuid_map_cache
    now = time.time()
    if now - _uuid_map_cache["fetched_at"] < UUID_MAP_TTL and _uuid_map_cache["map"]:
        return _uuid_map_cache["map"]
    try:
        from apps.channels.models import Channel
        mapped_ids = set()
        for cid in mappings.keys():
            try:
                mapped_ids.add(int(cid))
            except (ValueError, TypeError):
                pass
        result = {}
        for ch in Channel.objects.filter(id__in=mapped_ids):
            uuid_val = getattr(ch, "uuid", None)
            if uuid_val:
                result[str(uuid_val).lower()] = ch.id
        _uuid_map_cache = {"map": result, "fetched_at": now}
        logger.debug(f"tickarr: uuid map refreshed — {len(result)} entries")
        return result
    except Exception as e:
        logger.debug(f"tickarr: uuid map error: {e}")
        return _uuid_map_cache.get("map", {})
    finally:
        # Close the thread-local DB connection so it doesn't sit open indefinitely.
        # Background threads are never part of Django's request/response cycle, so
        # connections are never automatically cleaned up without this.
        try:
            from django.db import connection
            connection.close()
        except Exception:
            pass


def _redis_scan_active():
    """Scan Redis for ts_proxy:channel:{UUID}:activity keys. Returns set of
    integer channel IDs with active streams, or None if Redis is unavailable."""
    rc = _get_redis_client()
    if rc is None:
        return None
    mappings = _get_mappings()
    if not mappings:
        return set()
    uuid_to_id = _get_uuid_to_id_map(mappings)
    if not uuid_to_id:
        return set()
    active = set()
    try:
        # v0.25+ uses live:channel:*:activity; v0.24 used ts_proxy:channel:*:activity
        for pattern in ("live:channel:*:activity", "ts_proxy:channel:*:activity"):
            for raw_key in rc.scan_iter(pattern, count=200):
                key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                parts = key.split(":")
                if len(parts) < 4:
                    continue
                uuid = parts[2].lower()
                cid = uuid_to_id.get(uuid)
                if cid is not None:
                    active.add(cid)
    except Exception as e:
        logger.debug(f"tickarr: Redis scan error: {e}")
        return None
    return active


def _build_channel_list(channel_mappings):
    ch = []
    for cid_str, mapping in channel_mappings.items():
        if not mapping or mapping.get("type", "nowplaying") != "nowplaying":
            continue
        deeplink = mapping.get("xm_deeplink")
        if not deeplink:
            continue
        try:
            channel_id = int(cid_str)
        except (ValueError, TypeError):
            continue
        ch.append((channel_id, deeplink, mapping.get("channel_name", ""),
                   mapping.get("channel_description", "")))
    return ch


def _write_on_air(channel_id, channel_name, title="", subtitle=""):
    """Write 'On Air' overlay for non-song content.
    title   → artist slot (show/match name)
    subtitle → song slot  (live score line, segment title, etc.)
    SiriusXM sports channels send match + score as artist + title fields."""
    _ensure_dirs()
    _atomic_write(f"channel_{channel_id}_header.txt",  "On Air")
    _atomic_write(f"channel_{channel_id}_artist.txt",  _truncate(title or "", 38))
    sub = (subtitle or "").strip()
    _atomic_write(f"channel_{channel_id}_song.txt",    _truncate(sub, 45) if sub else "")
    _atomic_write(f"channel_{channel_id}_channel.txt", channel_name or "")


def _fetch_and_write(args):
    channel_id, deeplink, channel_name, channel_description = args
    # EAS alert is active — preserve alert content, skip now-playing update
    with _eas_lock:
        if _eas_active.get(str(channel_id)):
            return
    try:
        rc = _get_redis_client()
        if rc is not None:
            if not rc.set(f"tickarr:last_fetch:{channel_id}", "1", nx=True, ex=8):
                return  # another worker fetched this channel in the last 8s — skip
        stations = _get_nowplaying_bulk()
        station  = stations.get(deeplink) if deeplink else None
        if station:
            cut_type = station.get("cut_type", "")
            if (cut_type or "").lower() in _NON_SONG_CUT_TYPES:
                if (cut_type or "").lower() in _PROGRAM_CUT_TYPES:
                    # talk/pgm_segment: artist = show/match name, title = score or segment
                    # SiriusXM sports channels send e.g. artist="Norway v Senegal",
                    # title="NOR 3 - SEN 1 • 2H" — both fields are meaningful
                    program  = station.get("artist", "") or ""
                    score    = station.get("title",  "") or ""
                    _write_on_air(channel_id, channel_name,
                                  title=program.strip(), subtitle=score.strip())
                else:
                    # spot/promo/exp/etc: artist = ad or promo copy, not useful
                    _write_on_air(channel_id, channel_name, title="")
            else:
                artist = station.get("artist", "") or ""
                song   = station.get("title",  "") or ""
                _write_nowplaying(channel_id, artist, song, channel_name)
        elif stations and deeplink:
            # Bulk is up but this deeplink is absent — try xmplaylist per-channel
            artist, song = _xmplaylist_fetch(deeplink)
            if artist is not None or song is not None:
                _write_nowplaying(channel_id, artist or "", song or "", channel_name)
            else:
                logger.warning(f"tickarr: no data for {channel_name} ({deeplink}) from either source")
                path = os.path.join(TICKER_DIR, f"channel_{channel_id}_song.txt")
                if os.path.exists(path):
                    os.utime(path, None)
        else:
            logger.warning(f"tickarr: no data for {channel_name} ({deeplink})")
            path = os.path.join(TICKER_DIR, f"channel_{channel_id}_song.txt")
            if os.path.exists(path):
                os.utime(path, None)
    except Exception as e:
        logger.warning(f"tickarr: fetch failed for {channel_name} ({deeplink}): {e}")


def _poll_channels(ch_list):
    for args in ch_list:
        _fetch_and_write(args)


def _fast_loop(stop_event):
    """Every 2s: scan Redis for newly active streams and poll them immediately.
    On first tick, just records current state without polling (avoids startup burst)."""
    known_active = None  # None = uninitialized; skip polling on first observation
    while not stop_event.wait(timeout=2):
        try:
            rc = _get_redis_client()
            if rc is not None and not _redis_lock_acquire_or_refresh(rc, FAST_LOCK_KEY, _FAST_LOCK_TTL):
                continue
            mappings = _get_mappings()
            if not mappings:
                continue
            ch_list = _build_channel_list(mappings)
            ch_ids = {ch[0]: ch for ch in ch_list}

            current_active = _redis_scan_active()
            if current_active is None:
                known_active = None
                continue  # Redis unavailable — sweep loop handles everything
            current_active &= set(ch_ids.keys())
            if known_active is None:
                known_active = current_active  # baseline — don't poll on first tick
                continue
            newly_active = current_active - known_active
            known_active = current_active
            if newly_active:
                to_poll = [ch_ids[cid] for cid in newly_active if cid in ch_ids]
                logger.info(f"tickarr: stream-start → {[ch[2] for ch in to_poll]}")
                _poll_channels(to_poll)
        except Exception as e:
            logger.debug(f"tickarr: fast loop error: {e}")


def _channel_is_stale(channel_id, now):
    """True if the channel's song file is older than STALE_THRESHOLD seconds."""
    path = os.path.join(TICKER_DIR, f"channel_{channel_id}_song.txt")
    try:
        return (now - os.path.getmtime(path)) > STALE_THRESHOLD
    except OSError:
        return False  # file doesn't exist yet — not our problem to force-refresh


def _sweep_loop(stop_event):
    """Poll channels on a fixed interval. Gates to active channels when Redis is available.
    Also auto-recovers channels whose text files haven't been updated recently."""
    SWEEP_SLEEP = 15
    while not stop_event.is_set():
        rc = None
        try:
            rc = _get_redis_client()
            if rc is not None and not _redis_lock_acquire_or_refresh(rc, SWEEP_LOCK_KEY, _SWEEP_LOCK_TTL):
                stop_event.wait(timeout=SWEEP_SLEEP)
                continue
            mappings = _get_mappings()
            if mappings:
                all_ch = _build_channel_list(mappings)
                if all_ch:
                    active_ids = _redis_scan_active()
                    now = time.time()
                    if active_ids is not None:
                        active_ch = [c for c in all_ch if c[0] in active_ids]
                        # Channels not seen by Redis but with stale data — auto-recover
                        stale_ch  = [c for c in all_ch
                                     if c[0] not in active_ids
                                     and _channel_is_stale(c[0], now)][:STALE_BATCH_SIZE]
                        ch_to_poll = active_ch + stale_ch
                        if ch_to_poll:
                            logger.info(f"tickarr: sweep {len(active_ch)} active, "
                                        f"{len(stale_ch)} stale (of {len(all_ch)})")
                            _poll_channels(ch_to_poll)
                    else:
                        # Redis unavailable — fall back to all channels
                        logger.info(f"tickarr: sweep (no Redis) — {len(all_ch)} channels")
                        _poll_channels(all_ch)
        except Exception as e:
            logger.error(f"tickarr: sweep error: {e}", exc_info=True)
        # Refresh lock after work so TTL covers the sleep period too
        if rc is not None:
            try:
                _redis_lock_acquire_or_refresh(rc, SWEEP_LOCK_KEY, _SWEEP_LOCK_TTL)
            except Exception:
                pass
        stop_event.wait(timeout=SWEEP_SLEEP)


def _sports_sweep_loop(stop_event):
    """Poll ESPN every 30s and write scores to text files for active sports channels."""
    SWEEP_SLEEP = 30
    while not stop_event.is_set():
        rc = None
        try:
            rc = _get_redis_client()
            if rc is not None and not _redis_lock_acquire_or_refresh(rc, SPORTS_LOCK_KEY, _SPORTS_LOCK_TTL):
                stop_event.wait(timeout=SWEEP_SLEEP)
                continue
            mappings = _get_mappings()
            sports_channels = [(cid, m) for cid, m in mappings.items() if m.get("type") == "sports"]
            if sports_channels:
                for cid, mapping in sports_channels:
                    sports_list    = mapping.get("sports_list", [])
                    favorites      = mapping.get("sports_favorites", "")
                    if not sports_list:
                        continue
                    try:
                        labels, abbrevs, scores, full = _fetch_sports_text(sports_list, favorites)
                        if not scores:
                            placeholder = "  No games scheduled  "
                            pad         = " " * len(placeholder)
                            scores  = placeholder
                            labels  = pad
                            abbrevs = pad
                            full    = placeholder
                        _write_sports_text(int(cid), labels, abbrevs, scores, full)
                    except Exception as e:
                        logger.warning(f"tickarr: sports write failed for channel {cid}: {e}")
        except Exception as e:
            logger.error(f"tickarr: sports sweep error: {e}", exc_info=True)
        finally:
            try:
                from django.db import connection
                connection.close()
            except Exception:
                pass
        # Refresh lock after work so TTL covers the sleep period too
        if rc is not None:
            try:
                _redis_lock_acquire_or_refresh(rc, SPORTS_LOCK_KEY, _SPORTS_LOCK_TTL)
            except Exception:
                pass
        stop_event.wait(timeout=SWEEP_SLEEP)


def _poll_loop(stop_event):
    try:
        _get_channel_data()
    except Exception:
        pass

    # Fast loop (Redis stream-start detection) runs in a sibling thread
    fast_t = threading.Thread(target=_fast_loop, args=(stop_event,), daemon=True)
    fast_t.start()
    # Sports sweep runs independently — 30s interval, ESPN scoreboard polling
    sports_t = threading.Thread(target=_sports_sweep_loop, args=(stop_event,), daemon=True)
    sports_t.start()
    # EAS sweep — NWS alert polling, interval configurable (default 60s)
    eas_t = threading.Thread(target=_eas_sweep_loop, args=(stop_event,), daemon=True)
    eas_t.start()
    # Now-playing sweep loop — one bulk fetch from tickarr.com per cycle
    _sweep_loop(stop_event)

# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class Plugin:
    @property
    def fields(self):
        try:
            return self._build_fields()
        except Exception as e:
            logger.error(f"tickarr: _build_fields failed: {e}", exc_info=True)
            return [{"id": "_error", "type": "info", "label": f"Tickarr error: {e}"}]

    def __init__(self):
        global _scheduler_thread, _stop_event
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _stop_event = threading.Event()
            _scheduler_thread = threading.Thread(
                target=_poll_loop,
                args=(_stop_event,),
                daemon=True,
                name="tickarr-poller",
            )
            _scheduler_thread.start()
            logger.info("tickarr: poller thread started")

    def _build_fields(self):
        try:
            from apps.channels.models import ChannelGroup, Channel
            managed_group_ids = set(
                Channel.objects.exclude(channel_group=None).values_list("channel_group_id", flat=True)
            )
            groups   = [{"value": str(g.id), "label": g.name}
                        for g in ChannelGroup.objects.filter(id__in=managed_group_ids).order_by("name")]
            channels = [{"value": str(c.id), "label": c.name}
                        for c in Channel.objects.exclude(channel_group=None).order_by("name")]
        except Exception:
            groups = []
            channels = []

        try:
            mappings = _get_mappings()
        except Exception:
            mappings = {}

        ticker_lines = []
        for cid, m in mappings.items():
            name = m.get("channel_name", f"Channel {cid}")
            ticker_type = m.get("type", "nowplaying")
            if ticker_type == "custom":
                style    = m.get("custom_style", "static")
                schedule = m.get("custom_schedule", "always")
                tag = f"{style}"
                if schedule == "timed":
                    tag += f", every {m.get('custom_interval', '?')}min"
                now_playing = f"[custom/{tag}] {m.get('custom_text', '')[:50]}"
            elif ticker_type == "sports":
                sl = m.get("sports_list", [])
                labels_str = ", ".join(LABELS.get(s, s) for s in sl[:5])
                fav = m.get("sports_favorites", "")
                now_playing = f"[sports: {labels_str}]" + (f" favs: {fav}" if fav else "")
            else:
                artist_file = os.path.join(TICKER_DIR, f"channel_{cid}_artist.txt")
                song_file   = os.path.join(TICKER_DIR, f"channel_{cid}_song.txt")
                try:
                    with open(artist_file, encoding="utf-8") as f: artist = f.read().strip()
                    with open(song_file,   encoding="utf-8") as f: song   = f.read().strip()
                except Exception:
                    artist = song = ""
                now_playing = f"{artist} — {song}".strip(" —") if (artist or song) else "(no data yet)"
            ticker_lines.append(f"• {name}: {now_playing}")

        active_label = (f"{len(mappings)} active ticker(s):\n" + "\n".join(ticker_lines)) if mappings else "No active tickers."

        return [
            # ── Now Playing ───────────────────────────────────────────────
            {"id": "_np_section",       "type": "info",   "label": "━━━━━━━━━━  NOW PLAYING  ━━━━━━━━━━"},
            {"id": "np_target_type",    "type": "select", "label": "Apply To",
             "options": [{"value": "group", "label": "Channel Group"}, {"value": "channel", "label": "Single Channel"}]},
            {"id": "np_channel_group_id", "type": "select", "label": "Channel Group", "options": groups},
            {"id": "np_channel_id",       "type": "select", "label": "Channel",       "options": channels},
            # ── Custom Text ───────────────────────────────────────────────
            {"id": "_custom_section",      "type": "info",   "label": "━━━━━━━━━━  CUSTOM TEXT  ━━━━━━━━━━"},
            {"id": "custom_target_type",   "type": "select", "label": "Apply To",
             "options": [{"value": "group", "label": "Channel Group"}, {"value": "channel", "label": "Single Channel"}]},
            {"id": "custom_channel_group_id", "type": "select", "label": "Channel Group", "options": groups},
            {"id": "custom_channel_id",       "type": "select", "label": "Channel",       "options": channels},
            {"id": "custom_text",      "type": "text",   "label": "Custom Text"},
            {"id": "custom_style",     "type": "select", "label": "Style",
             "options": [{"value": "static", "label": "Static"}, {"value": "scrolling", "label": "Scrolling"}]},
            {"id": "custom_position",  "type": "select", "label": "Position",
             "options": [
                 {"value": "bottom", "label": "Bottom"},
                 {"value": "top",    "label": "Top"},
                 {"value": "center", "label": "Center"},
             ]},
            {"id": "custom_schedule",  "type": "select", "label": "Schedule",
             "options": [{"value": "always", "label": "Always On"}, {"value": "timed", "label": "Timed"}]},
            {"id": "custom_duration",  "type": "number", "label": "Display Duration (seconds) — Timed only"},
            {"id": "custom_interval",  "type": "number", "label": "Repeat Interval (minutes) — Timed only"},
            # ── Sports Ticker ─────────────────────────────────────────────
            {"id": "_sports_section",       "type": "info",    "label": "━━━━━━━━━━  SPORTS TICKER  ━━━━━━━━━━"},
            {"id": "_sports_football",      "type": "info",    "label": "── Football ──"},
            {"id": "sports_nfl",            "type": "boolean", "label": "NFL"},
            {"id": "sports_ncaafb",         "type": "boolean", "label": "College Football (NCAAF)"},
            {"id": "sports_cfl",            "type": "boolean", "label": "CFL"},
            {"id": "_sports_basketball",    "type": "info",    "label": "── Basketball ──"},
            {"id": "sports_nba",            "type": "boolean", "label": "NBA"},
            {"id": "sports_wnba",           "type": "boolean", "label": "WNBA"},
            {"id": "sports_ncaamb",         "type": "boolean", "label": "College Basketball (NCAAB)"},
            {"id": "_sports_baseball",      "type": "info",    "label": "── Baseball / Softball ──"},
            {"id": "sports_mlb",            "type": "boolean", "label": "MLB"},
            {"id": "sports_ncaabase",       "type": "boolean", "label": "NCAA Baseball"},
            {"id": "sports_ncaasb",         "type": "boolean", "label": "NCAA Softball"},
            {"id": "_sports_hockey",        "type": "info",    "label": "── Hockey ──"},
            {"id": "sports_nhl",            "type": "boolean", "label": "NHL"},
            {"id": "_sports_soccer",        "type": "info",    "label": "── Soccer ──"},
            {"id": "sports_mls",            "type": "boolean", "label": "MLS"},
            {"id": "sports_nwsl",           "type": "boolean", "label": "NWSL"},
            {"id": "sports_epl",            "type": "boolean", "label": "EPL (English Premier League)"},
            {"id": "sports_ucl",            "type": "boolean", "label": "UEFA Champions League"},
            {"id": "sports_laliga",         "type": "boolean", "label": "La Liga"},
            {"id": "sports_bundesliga",     "type": "boolean", "label": "Bundesliga"},
            {"id": "sports_seriea",         "type": "boolean", "label": "Serie A"},
            {"id": "sports_ligue1",         "type": "boolean", "label": "Ligue 1"},
            {"id": "_sports_tennis",        "type": "info",    "label": "── Tennis ──"},
            {"id": "sports_atp",            "type": "boolean", "label": "ATP"},
            {"id": "sports_wta",            "type": "boolean", "label": "WTA"},
            {"id": "_sports_motor",         "type": "info",    "label": "── Motor ──"},
            {"id": "sports_nascar",         "type": "boolean", "label": "NASCAR (live races only)"},
            {"id": "_sports_college_other", "type": "info",    "label": "── College Other ──"},
            {"id": "sports_ncaavb",         "type": "boolean", "label": "NCAA Volleyball"},
            {"id": "sports_ncaalax",        "type": "boolean", "label": "NCAA Lacrosse"},
            {"id": "sports_favorites",      "type": "text",    "label": "Favorite Teams (abbreviations, comma-separated — blank = all teams)"},
            {"id": "sports_color_mode",     "type": "select",  "label": "Color Mode",
             "options": [
                 {"value": "single", "label": "Single Color — White (recommended, lower CPU)"},
                 {"value": "multi",  "label": "Multi-Color — Sport labels + team abbreviations colored"},
             ]},
            {"id": "sports_position",       "type": "select",  "label": "Ticker Position",
             "options": [{"value": "bottom", "label": "Bottom"}, {"value": "top", "label": "Top"}]},
            {"id": "sports_fontsize",       "type": "number",  "label": "Font Size (default 36)", "min": 16},
            {"id": "sports_labelcolor",     "type": "select",  "label": "Sport Label Color (NFL:, NBA:, etc.) — Multi-Color only",
             "options": [
                 {"value": "#ffd700", "label": "Gold (default)"},
                 {"value": "#00d4ff", "label": "Cyan"},
                 {"value": "#ff8c00", "label": "Orange"},
                 {"value": "#00ff80", "label": "Green"},
                 {"value": "#ff4444", "label": "Red"},
                 {"value": "#ffffff", "label": "White (no distinction)"},
             ]},
            {"id": "sports_abbrcolor",      "type": "select",  "label": "Team Abbreviation Color (KC, DEN, etc.) — Multi-Color only",
             "options": [
                 {"value": "#00d4ff", "label": "Cyan (default)"},
                 {"value": "#ffd700", "label": "Gold"},
                 {"value": "#ff8c00", "label": "Orange"},
                 {"value": "#00ff80", "label": "Green"},
                 {"value": "#ff4444", "label": "Red"},
                 {"value": "#ffffff", "label": "White (no distinction)"},
             ]},
            {"id": "sports_target_type",    "type": "select",  "label": "Apply To",
             "options": [{"value": "group", "label": "Channel Group"}, {"value": "channel", "label": "Single Channel"}]},
            {"id": "sports_channel_group_id", "type": "select", "label": "Channel Group", "options": groups},
            {"id": "sports_channel_id",       "type": "select", "label": "Channel",       "options": channels},
            # ── Channel Setup ─────────────────────────────────────────────
            {"id": "_ch_section", "type": "info", "label": "━━━━━━━━━━  SATELLITE RADIO CHANNEL SETUP  ━━━━━━━━━━"},
            {"id": "_ch_about",   "type": "info",
             "label": "Select a group or channel below, then use the Channel Setup actions to fill EPG, sort, or assign logos."},
            {"id": "ch_target_type", "type": "select", "label": "Apply To",
             "options": [{"value": "group", "label": "Channel Group"}, {"value": "channel", "label": "Single Channel"}]},
            {"id": "ch_channel_group_id", "type": "select", "label": "Channel Group", "options": groups},
            {"id": "ch_channel_id",       "type": "select", "label": "Channel",       "options": channels},
            {"id": "sort_start_number",   "type": "text",   "label": "Sort Start Number",
             "placeholder": "Leave blank to auto-detect from current channel numbers"},
            # ── EAS ───────────────────────────────────────────────────────
            {"id": "_eas_section",  "type": "info", "label": "━━━━━━━━━━  EAS WEATHER ALERTS  ━━━━━━━━━━"},
            {"id": "_eas_about",    "type": "info",
             "label": "Monitors NWS alerts for configured zones. Overlay is invisible until an alert fires, then shows alert type and affected area. Clears automatically when the alert expires."},
            {"id": "eas_zones",     "type": "text",   "label": "NWS Zone / County Codes",
             "placeholder": "e.g. TXC113,TXC121  (comma-separated — find yours at alerts.weather.gov)"},
            {"id": "eas_severity_filter", "type": "select", "label": "Minimum Severity",
             "options": [
                 {"value": "Moderate", "label": "Watch (Moderate and above)"},
                 {"value": "Severe",   "label": "Warning (Severe and above)"},
                 {"value": "Extreme",  "label": "Emergency (Extreme only)"},
             ]},
            {"id": "eas_poll_interval", "type": "number", "label": "Poll Interval (seconds)", "min": 15},
            {"id": "eas_target_type",   "type": "select", "label": "Apply To",
             "options": [{"value": "group", "label": "Channel Group"}, {"value": "channel", "label": "Single Channel"}]},
            {"id": "eas_channel_group_id", "type": "select", "label": "Channel Group", "options": groups},
            {"id": "eas_channel_id",       "type": "select", "label": "Channel",       "options": channels},
            # ── Active Tickers ────────────────────────────────────────────
            {"id": "_active_section", "type": "info", "label": "━━━━━━━━━━  ACTIVE TICKERS  ━━━━━━━━━━"},
            {"id": "_ticker_list",    "type": "info", "label": active_label},
        ]

    def run(self, action, params, context):
        if not params:
            saved = _get_settings()
            params = {k: v for k, v in saved.items() if k not in ("channel_mappings", "channel_cache")}

        dispatch = {
            "enable_nowplaying":    self._enable_nowplaying,
            "disable_nowplaying":   self._disable_nowplaying,
            "enable_custom":        self._enable_custom,
            "update_custom":        self._update_custom,
            "disable_custom":       self._disable_custom_ticker,
            "enable_sports":        self._enable_sports,
            "disable_sports":       self._disable_sports_ticker,
            "enable_eas":           self._enable_eas,
            "disable_eas":          self._disable_eas,
            "disable_all":          self._disable_all,
            "view_active":          self._view_active,
            "refresh_channels":     self._refresh_channels,
            "fill_sxm_epg":         self._fill_sxm_epg,
            "fill_epg":             self._fill_epg,
            "sort_channels":        self._sort_channels,
            "assign_logos":         self._assign_logos,
            "fill_and_sort":        self._fill_and_sort,
            "fill_sort_logos":      self._fill_sort_logos,
            "clean_orphans":        self._clean_orphans,
            "redis_diag":           self._redis_diag,
            "reload_poller":        self._reload_poller,
            "restart_dispatcharr":  self._restart_dispatcharr,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"success": False, "message": f"Unknown action: {action}"}
        try:
            return handler(params)
        except Exception as e:
            logger.error(f"tickarr: action {action} failed: {e}", exc_info=True)
            return {"success": False, "message": f"Error: {e}"}

    def stop(self, context):
        global _stop_event, _scheduler_thread
        _stop_event.set()
        if _scheduler_thread:
            _scheduler_thread.join(timeout=5)
        logger.info("tickarr: poller thread stopped")

    # ------------------------------------------------------------------ #
    # Actions                                                              #
    # ------------------------------------------------------------------ #

    def _enable_nowplaying(self, params):
        from apps.channels.models import Channel, ChannelGroup

        channels = self._resolve_channels(params, prefix="np_")
        if not channels:
            return {"success": False, "message": "No channels found for the selected target."}

        xm_channels, aliases = _get_channel_data()
        stations = _get_stations()
        mappings = _get_mappings()

        enabled, skipped, failed = [], [], []

        for channel in channels:
            cid = str(channel.id)
            if cid in mappings:
                skipped.append(f"{channel.name} (already enabled)")
                continue
            try:
                original_profile = channel.stream_profile
                if not original_profile:
                    skipped.append(f"{channel.name} (no stream profile assigned — go to Channels, open this channel, and assign any stream profile, then re-run)")
                    continue
                if original_profile.name.startswith(PROFILE_PREFIX):
                    skipped.append(f"{channel.name} (already has a Tickarr profile — run Disable Ticker first)")
                    continue

                xm_entry = _match_channel(channel.name, xm_channels, aliases)
                deeplink = None
                channel_description = ""
                if xm_entry:
                    channel_description = xm_entry.get("description", "")
                    uuid = xm_entry.get("lookaround_channel_id")
                    station = (_match_station_by_uuid(uuid, stations) if uuid else None) or \
                              _match_station_by_name(channel.name, stations)
                else:
                    station = _match_station_by_name(channel.name, stations)
                if station:
                    deeplink = station.get("id")  # tickarr.com uses "id" as the deeplink

                cloned, removed_flags = _clone_and_inject(channel.id, original_profile, channel.name)
                _assign_profile(channel, cloned)

                mappings[cid] = {
                    "original_profile_id": original_profile.id,
                    "ticker_profile_id": cloned.id,
                    "xm_deeplink": deeplink,
                    "channel_name": channel.name,
                    "channel_description": channel_description,
                    "type": "nowplaying",
                }

                # Write fallback immediately — sweep loop fetches live data within 15s
                _write_fallback(channel.id, channel.name, channel_description)

                note = (f" [auto-removed from cloned profile: {', '.join(removed_flags)}]"
                        if removed_flags else "")
                enabled.append(f"{channel.name}{note}")
            except Exception as e:
                logger.error(f"tickarr: enable failed for {channel.name}: {e}", exc_info=True)
                failed.append(f"{channel.name} (error: {e})")

        _save_mappings(mappings)

        parts = []
        if enabled:  parts.append(f"Enabled: {len(enabled)} channel(s)")
        if skipped:  parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:   parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _enable_custom(self, params):
        from apps.channels.models import Channel, ChannelGroup

        custom_text = (params.get("custom_text") or "").strip()
        if not custom_text:
            return {"success": False, "message": "Custom Text is required."}

        style    = params.get("custom_style",    "static")
        position = params.get("custom_position", "bottom")
        schedule = params.get("custom_schedule", "always")

        try:
            duration = int(params.get("custom_duration") or 10)
            interval = int(params.get("custom_interval") or 5)
        except (ValueError, TypeError):
            return {"success": False, "message": "Duration and Interval must be integers."}

        if schedule == "timed":
            if duration <= 0:
                return {"success": False, "message": "Display Duration must be greater than 0."}
            if interval <= 0:
                return {"success": False, "message": "Repeat Interval must be greater than 0."}
            if duration >= interval * 60:
                return {"success": False, "message": "Display Duration (seconds) must be less than Repeat Interval (minutes × 60)."}

        channels = self._resolve_channels(params, prefix="custom_")
        if not channels:
            return {"success": False, "message": "No channels found for the selected target."}

        mappings = _get_mappings()
        enabled, skipped, failed = [], [], []

        for channel in channels:
            cid = str(channel.id)
            if cid in mappings:
                existing_type = mappings[cid].get("type", "nowplaying")
                skipped.append(f"{channel.name} (already has a {existing_type} ticker — disable first)")
                continue
            try:
                original_profile = channel.stream_profile
                if not original_profile:
                    skipped.append(f"{channel.name} (no stream profile assigned — go to Channels, open this channel, and assign any stream profile, then re-run)")
                    continue
                if original_profile.name.startswith(PROFILE_PREFIX):
                    skipped.append(f"{channel.name} (already has a Tickarr profile — run Disable Ticker first)")
                    continue

                raw_params, removed_flags = _strip_dangerous_flags(channel.name, original_profile.parameters or "")
                drawtext = _build_custom_filter(channel.id, style, position, schedule, duration, interval)
                new_params = _inject_drawtext(raw_params, drawtext)

                from core.models import StreamProfile
                cloned = StreamProfile(
                    name=f"{PROFILE_PREFIX}{original_profile.name} [ch{channel.id}]",
                    command=original_profile.command,
                    parameters=new_params,
                    locked=False,
                    is_active=True,
                )
                cloned.save()
                _assign_profile(channel, cloned)

                mappings[cid] = {
                    "original_profile_id": original_profile.id,
                    "ticker_profile_id":   cloned.id,
                    "channel_name":        channel.name,
                    "type":                "custom",
                    "custom_text":         custom_text,
                    "custom_style":        style,
                    "custom_position":     position,
                    "custom_schedule":     schedule,
                    "custom_duration":     duration,
                    "custom_interval":     interval,
                }
                _write_custom_text(channel.id, custom_text)
                note = (f" [auto-removed: {', '.join(removed_flags)}]" if removed_flags else "")
                enabled.append(f"{channel.name}{note}")

            except Exception as e:
                logger.error(f"tickarr: enable_custom failed for {channel.name}: {e}", exc_info=True)
                failed.append(f"{channel.name} (error: {e})")

        _save_mappings(mappings)

        parts = []
        if enabled: parts.append(f"Enabled: {len(enabled)} channel(s)")
        if skipped: parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:  parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _update_custom(self, params):
        custom_text = (params.get("custom_text") or "").strip()
        if not custom_text:
            return {"success": False, "message": "Custom Text is required."}

        channels = (
            self._resolve_channels(params, prefix="custom_") or
            self._resolve_channels(params, prefix="np_")
        )
        if not channels:
            return {"success": False, "message": "No channels found. Select a channel in the Custom Text section."}

        mappings = _get_mappings()
        updated, skipped = [], []

        for channel in channels:
            cid = str(channel.id)
            mapping = mappings.get(cid)
            if not mapping or mapping.get("type") != "custom":
                skipped.append(f"{channel.name} (no custom ticker active — enable it first)")
                continue
            _write_custom_text(channel.id, custom_text)
            mapping["custom_text"] = custom_text
            updated.append(channel.name)

        if updated:
            _save_mappings(mappings)

        parts = []
        if updated: parts.append(f"Updated {len(updated)} channel(s) — text live immediately:\n" + "\n".join(f"  • {u}" for u in updated))
        if skipped: parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        return {"success": bool(updated), "message": "\n\n".join(parts) or "Nothing to do."}

    def _enable_sports(self, params):
        sports_list = [s for s in KNOWN_SPORTS if params.get(f"sports_{s}") in (True, "true", "1", 1)]
        if not sports_list:
            return {"success": False, "message": "Select at least one sport/league before enabling."}

        color_mode = params.get("sports_color_mode") or "single"
        position   = params.get("sports_position", "bottom")
        fontsize   = int(params.get("sports_fontsize") or 36)
        labelcolor = params.get("sports_labelcolor") or "#ffd700"
        abbrcolor  = params.get("sports_abbrcolor")  or "#00d4ff"
        favorites  = (params.get("sports_favorites") or "").strip()

        channels = self._resolve_channels(params, prefix="sports_")
        if not channels:
            return {"success": False, "message": "No channels found for the selected target."}

        mappings = _get_mappings()
        enabled, skipped, failed = [], [], []

        for channel in channels:
            cid = str(channel.id)
            if cid in mappings:
                existing_type = mappings[cid].get("type", "nowplaying")
                skipped.append(f"{channel.name} (already has a {existing_type} ticker — disable first)")
                continue
            try:
                original_profile = channel.stream_profile
                if not original_profile:
                    skipped.append(f"{channel.name} (no stream profile assigned — go to Channels, open this channel, and assign any stream profile, then re-run)")
                    continue
                if original_profile.name.startswith(PROFILE_PREFIX):
                    skipped.append(f"{channel.name} (already has a Tickarr profile — run Disable Ticker first)")
                    continue

                raw_params, removed_flags = _strip_dangerous_flags(channel.name, original_profile.parameters or "")
                drawtext   = _build_sports_filter(channel.id, position, fontsize,
                                                  labelcolor, abbrcolor, color_mode)
                new_params = _inject_drawtext(raw_params, drawtext)

                from core.models import StreamProfile
                cloned = StreamProfile(
                    name=f"{PROFILE_PREFIX}{original_profile.name} [ch{channel.id}]",
                    command=original_profile.command,
                    parameters=new_params,
                    locked=False,
                    is_active=True,
                )
                cloned.save()
                _assign_profile(channel, cloned)

                mappings[cid] = {
                    "original_profile_id":    original_profile.id,
                    "ticker_profile_id":      cloned.id,
                    "channel_name":           channel.name,
                    "type":                   "sports",
                    "sports_list":            sports_list,
                    "sports_favorites":       favorites,
                    "sports_position":        position,
                    "sports_fontsize":        fontsize,
                    "sports_color_mode":      color_mode,
                    "sports_labelcolor":      labelcolor,
                    "sports_abbrcolor":       abbrcolor,
                }
                placeholder = "Loading sports scores..."
                pad = " " * len(placeholder)
                _write_sports_text(channel.id,
                                   pad,
                                   pad,
                                   placeholder,
                                   placeholder)
                note = (f" [auto-removed: {', '.join(removed_flags)}]" if removed_flags else "")
                enabled.append(f"{channel.name}{note}")

            except Exception as e:
                logger.error(f"tickarr: enable_sports failed for {channel.name}: {e}", exc_info=True)
                failed.append(f"{channel.name} (error: {e})")

        _save_mappings(mappings)

        if color_mode == "multi" and _FONT_MONO_BOLD:
            color_note = f"Mode: Multi-Color — sport labels = {labelcolor}, team abbreviations = {abbrcolor}."
        elif color_mode == "multi" and not _FONT_MONO_BOLD:
            color_note = "Mode: Multi-Color requested but monospace font not found — using Single Color white. Install fonts-dejavu or fonts-liberation to enable colors."
        else:
            color_note = "Mode: Single Color white (1 drawtext layer — lower CPU)."
        parts = []
        sports_label = ", ".join(LABELS.get(s, s.upper()) for s in sports_list)
        if enabled:
            parts.append(
                f"Enabled sports ticker on {len(enabled)} channel(s)\n"
                f"Sports: {sports_label}\n"
                f"Live scores will appear within 30 seconds.\n"
                f"{color_note}\n"
                + "\n".join(f"  • {n}" for n in enabled)
            )
        if skipped:
            parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:
            parts.append("Failed:\n" + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    # ------------------------------------------------------------------ #
    # Shared disable helper + phase-specific disable actions             #
    # ------------------------------------------------------------------ #

    def _do_disable(self, channels, type_filter=None):
        """Core disable logic shared by all three phase-specific disable actions."""
        mappings = _get_mappings()
        disabled, skipped, failed = [], [], []

        for channel in channels:
            cid = str(channel.id)
            mapping = mappings.get(cid)
            if not mapping:
                skipped.append(f"{channel.name} (no ticker active on this channel)")
                continue
            ticker_type = mapping.get("type", "nowplaying")
            if type_filter and ticker_type != type_filter:
                skipped.append(f"{channel.name} (has a {ticker_type} ticker, not {type_filter} — use the correct disable action)")
                continue
            try:
                _restore_profile(channel, mapping["original_profile_id"])
                _delete_cloned_profile(mapping["ticker_profile_id"])
                _remove_channel_files(channel.id)
                if ticker_type == "custom":
                    _remove_custom_file(channel.id)
                elif ticker_type == "sports":
                    _remove_sports_file(channel.id)
                del mappings[cid]
                disabled.append(channel.name)
            except Exception as e:
                logger.error(f"tickarr: disable failed for {channel.name}: {e}", exc_info=True)
                failed.append(f"{channel.name} (error: {e})")

        _save_mappings(mappings)
        parts = []
        if disabled: parts.append(f"Disabled: {len(disabled)} channel(s)")
        if skipped:  parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:   parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _disable_nowplaying(self, params):
        channels = self._resolve_channels(params, prefix="np_")
        if not channels:
            return {"success": False, "message": "No channels found. Set the Now Playing → Apply To / Channel selector above."}
        return self._do_disable(channels, type_filter="nowplaying")

    def _disable_custom_ticker(self, params):
        channels = self._resolve_channels(params, prefix="custom_")
        if not channels:
            return {"success": False, "message": "No channels found. Set the Custom Text → Apply To / Channel selector above."}
        return self._do_disable(channels, type_filter="custom")

    def _disable_sports_ticker(self, params):
        channels = self._resolve_channels(params, prefix="sports_")
        if not channels:
            return {"success": False, "message": "No channels found. Set the Sports Ticker → Apply To / Channel selector above."}
        return self._do_disable(channels, type_filter="sports")

    def _enable_eas(self, params):
        from apps.channels.models import Channel

        zones = (params.get("eas_zones") or "").strip()
        if not zones:
            return {"success": False, "message": "No NWS zone codes configured. Enter at least one zone code in EAS Weather Alerts → NWS Zone / County Codes above."}

        channels = self._resolve_channels(params, prefix="eas_")
        if not channels:
            return {"success": False, "message": "No channels found. Set the EAS Weather Alerts → Apply To / Channel selector above."}

        mappings = _get_mappings()
        enabled, skipped, failed = [], [], []

        for channel in channels:
            cid = str(channel.id)
            if cid in mappings:
                existing = mappings[cid].get("type", "nowplaying")
                skipped.append(f"{channel.name} (already has {existing} ticker — disable first)")
                continue
            try:
                original_profile = channel.stream_profile
                if not original_profile:
                    skipped.append(f"{channel.name} (no stream profile assigned — assign one in Channels first)")
                    continue
                if original_profile.name.startswith(PROFILE_PREFIX):
                    skipped.append(f"{channel.name} (already has a Tickarr profile — disable first)")
                    continue
                cloned, removed_flags = _clone_and_inject_eas(channel.id, original_profile, channel.name)
                _assign_profile(channel, cloned)
                _eas_clear(channel.id)
                mappings[cid] = {
                    "original_profile_id": original_profile.id,
                    "ticker_profile_id":   cloned.id,
                    "channel_name":        channel.name,
                    "type":                "eas",
                }
                note = (f" [auto-removed: {', '.join(removed_flags)}]" if removed_flags else "")
                enabled.append(f"{channel.name}{note}")
            except Exception as e:
                logger.error(f"tickarr: enable EAS failed for {channel.name}: {e}", exc_info=True)
                failed.append(f"{channel.name} ({e})")

        _save_mappings(mappings)
        parts = []
        if enabled:
            parts.append(f"EAS enabled: {len(enabled)} channel(s)\n" + "\n".join(f"  • {e}" for e in enabled))
            parts.append(f"Monitoring zones: {zones}\nThe overlay is silent until a qualifying NWS alert fires.")
        if skipped: parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:  parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _disable_eas(self, params):
        channels = self._resolve_channels(params, prefix="eas_")
        if not channels:
            return {"success": False, "message": "No channels found. Set the EAS Weather Alerts → Apply To / Channel selector above."}
        mappings = _get_mappings()
        disabled, skipped, failed = [], [], []
        for channel in channels:
            cid = str(channel.id)
            mapping = mappings.get(cid)
            if not mapping or mapping.get("type") != "eas":
                skipped.append(f"{channel.name} (no EAS ticker active)")
                continue
            try:
                _restore_profile(channel, mapping["original_profile_id"])
                _delete_cloned_profile(mapping["ticker_profile_id"])
                _eas_clear(channel.id)
                with _eas_lock:
                    _eas_active.pop(cid, None)
                del mappings[cid]
                disabled.append(channel.name)
            except Exception as e:
                logger.error(f"tickarr: disable EAS failed for {channel.name}: {e}", exc_info=True)
                failed.append(f"{channel.name} ({e})")
        _save_mappings(mappings)
        parts = []
        if disabled: parts.append(f"EAS disabled: {len(disabled)} channel(s)")
        if skipped:  parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:   parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _disable_all(self, params):
        from apps.channels.models import Channel

        mappings = _get_mappings()
        if not mappings:
            return {"success": True, "message": "No active tickers to disable."}

        disabled, failed = [], []
        for cid, mapping in list(mappings.items()):
            name = mapping.get("channel_name", f"Channel {cid}")
            try:
                channel = Channel.objects.get(id=int(cid))
                _restore_profile(channel, mapping["original_profile_id"])
                _delete_cloned_profile(mapping["ticker_profile_id"])
                ticker_type = mapping.get("type", "nowplaying")
                _remove_channel_files(channel.id)
                if ticker_type == "custom":
                    _remove_custom_file(channel.id)
                elif ticker_type == "sports":
                    _remove_sports_file(channel.id)
                del mappings[cid]
                disabled.append(name)
            except Exception as e:
                logger.error(f"tickarr: disable_all failed for {name}: {e}", exc_info=True)
                failed.append(f"{name} (error: {e})")

        _save_mappings(mappings)
        parts = []
        if disabled: parts.append(f"Disabled: {len(disabled)} channel(s)\n" + "\n".join(f"  • {n}" for n in disabled))
        if failed:   parts.append("Failed:\n" + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _view_active(self, params):
        mappings = _get_mappings()
        if not mappings:
            return {"success": True, "message": "No channels currently enabled."}

        np_channels     = [(cid, m) for cid, m in mappings.items() if m.get("type", "nowplaying") == "nowplaying"]
        custom_channels = [(cid, m) for cid, m in mappings.items() if m.get("type") == "custom"]
        sports_channels = [(cid, m) for cid, m in mappings.items() if m.get("type") == "sports"]

        lines = [
            f"Total: {len(mappings)}  |  Now Playing: {len(np_channels)}  "
            f"|  Custom: {len(custom_channels)}  |  Sports: {len(sports_channels)}",
            "",
        ]

        if np_channels:
            with_deeplink = [(cid, m) for cid, m in np_channels if m.get("xm_deeplink")]
            no_deeplink   = [(cid, m) for cid, m in np_channels if not m.get("xm_deeplink")]
            lines.append(f"── Now Playing ({len(np_channels)}, {len(with_deeplink)} matched to tickarr.com) ──")
            for cid, mapping in with_deeplink[:25]:
                name = mapping.get("channel_name", f"Channel {cid}")
                deeplink = mapping.get("xm_deeplink")
                artist_file = os.path.join(TICKER_DIR, f"channel_{cid}_artist.txt")
                song_file   = os.path.join(TICKER_DIR, f"channel_{cid}_song.txt")
                try:
                    with open(artist_file, encoding="utf-8") as f: artist = f.read().strip()
                    with open(song_file,   encoding="utf-8") as f: song   = f.read().strip()
                except Exception:
                    artist = song = ""
                if artist or song:
                    lines.append(f"  [{deeplink}] {name}: {artist} — {song}")
                else:
                    lines.append(f"  [{deeplink}] {name}: (no data yet)")
            if no_deeplink:
                lines.append(f"  No tickarr.com match ({len(no_deeplink)} — run Refresh Channel Data):")
                for cid, m in no_deeplink[:5]:
                    lines.append(f"    • {m.get('channel_name', cid)}")
            lines.append("")

        if custom_channels:
            lines.append(f"── Custom Text ({len(custom_channels)}) ──")
            for cid, mapping in custom_channels[:20]:
                name  = mapping.get("channel_name", f"Channel {cid}")
                style = mapping.get("custom_style", "static")
                text  = mapping.get("custom_text", "")[:60]
                lines.append(f"  {name}: [{style}] {text}")
            lines.append("")

        if sports_channels:
            lines.append(f"── Sports Ticker ({len(sports_channels)}) ──")
            for cid, mapping in sports_channels[:20]:
                name = mapping.get("channel_name", f"Channel {cid}")
                sl   = mapping.get("sports_list", [])
                fav  = mapping.get("sports_favorites", "")
                labels_str = ", ".join(LABELS.get(s, s) for s in sl)
                sports_file = os.path.join(TICKER_DIR, f"channel_{cid}_sports_full.txt")
                try:
                    with open(sports_file, encoding="utf-8") as f:
                        preview = f.read().strip()[:100]
                except FileNotFoundError:
                    preview = "(no data yet)"
                except Exception:
                    preview = "(error)"
                lines.append(f"  {name}: [{labels_str}]" + (f"  favs: {fav}" if fav else ""))
                lines.append(f"    {preview}")

        return {"success": True, "message": "\n".join(lines)}

    def _refresh_channels(self, params):
        try:
            channels, aliases = _get_channel_data(force=True)
            stations = _get_stations(force=True)
            if not stations:
                return {"success": False, "message": "tickarr.com channel list came back empty — try again in a moment."}
            mappings = _get_mappings()
            deeplinks_fixed = 0
            descs_fixed = 0
            unmatched = []
            for cid, mapping in mappings.items():
                channel_name = mapping.get("channel_name", "")
                xm_entry = _match_channel(channel_name, channels, aliases)

                # Always update description if we have one and it's currently empty
                if xm_entry and not mapping.get("channel_description"):
                    desc = xm_entry.get("description", "")
                    if desc:
                        mappings[cid]["channel_description"] = desc
                        descs_fixed += 1

                if not mapping.get("xm_deeplink"):
                    if xm_entry:
                        uuid = xm_entry.get("lookaround_channel_id")
                        station = (_match_station_by_uuid(uuid, stations) if uuid else None) or \
                                  _match_station_by_name(channel_name, stations)
                    else:
                        station = _match_station_by_name(channel_name, stations)
                    if station:
                        deeplink = station.get("id")
                        mappings[cid]["xm_deeplink"] = deeplink
                        deeplinks_fixed += 1
                        logger.info(f"tickarr: resolved deeplink for {channel_name} → {deeplink}")
                    else:
                        unmatched.append(channel_name)

            if deeplinks_fixed or descs_fixed:
                _save_mappings(mappings)

            mapped_deeplinks = {m.get("xm_deeplink") for m in mappings.values() if m.get("xm_deeplink")}
            orphan_stations = [s["name"] for s in stations if s.get("id") not in mapped_deeplinks]

            msg = (f"Fetched: {len(channels)} channel descriptions, {len(stations)} tickarr.com channels.\n"
                   f"Fixed: {deeplinks_fixed} deeplink(s), {descs_fixed} description(s).\n"
                   f"Matched: {len(mapped_deeplinks)} of {len(stations)} tickarr.com channels.")
            if orphan_stations:
                msg += f"\n\nTickarr.com channels with no Dispatcharr match ({len(orphan_stations)}):\n" + ", ".join(orphan_stations[:20])
            if unmatched:
                msg += f"\n\nNo tickarr.com match for {len(unmatched)} Dispatcharr channel(s) (first 20):\n" + ", ".join(unmatched[:20])
            return {"success": True, "message": msg}
        except Exception as e:
            return {"success": False, "message": f"Refresh failed: {e}"}

    # ------------------------------------------------------------------ #
    # Channel Management — Fill / Sort / Logos                           #
    # Mirrors EPGeditARR's structure exactly (no separate Order action). #
    # ------------------------------------------------------------------ #

    def _ch_resolve(self, params):
        """Return (channels_data, aliases, dispatch_channels, group_or_None) or raise ValueError."""
        from apps.channels.models import Channel, ChannelGroup
        channels_data, aliases = _get_channel_data()
        if not channels_data:
            raise ValueError("Channel data not available — run Refresh Channel Data first.")
        target_type = params.get("ch_target_type", "group")
        if target_type == "group":
            group_id = params.get("ch_channel_group_id")
            if not group_id:
                raise ValueError("Select a channel group in the Channel Setup section of Settings before running this action.")
            try:
                group = ChannelGroup.objects.get(id=int(group_id))
                return channels_data, aliases, list(
                    Channel.objects.filter(channel_group=group).order_by("channel_number", "name")
                ), group
            except ChannelGroup.DoesNotExist:
                raise ValueError("Channel group not found.")
        else:
            channel_id = params.get("ch_channel_id")
            if not channel_id:
                raise ValueError("Select a channel in the Channel Setup section of Settings before running this action.")
            try:
                return channels_data, aliases, [Channel.objects.get(id=int(channel_id))], None
            except Channel.DoesNotExist:
                raise ValueError("Channel not found.")

    def _do_fill(self, channel, xm_entry):
        """Set tvg_id to the official SiriusXM channel name for EPG source matching."""
        try:
            channel.tvg_id = xm_entry.get("name", channel.name)
            channel.save(update_fields=["tvg_id"])
            return True
        except Exception as e:
            logger.warning(f"tickarr: fill failed for {channel.name}: {e}")
            return False

    def _do_logos(self, channel, xm_entry):
        """Assign logo from bundled data. Returns (ok, created)."""
        logo_url = xm_entry.get("logo_url", "")
        if not logo_url:
            return False, False
        return _assign_logo(channel, logo_url, xm_entry.get("name", channel.name))

    def _fill_epg(self, params):
        try:
            channels_data, aliases, dispatch_channels, _ = self._ch_resolve(params)
        except ValueError as e:
            return {"success": False, "message": str(e)}
        filled, skipped, failed = [], [], []
        for ch in dispatch_channels:
            xm = _match_channel(ch.name, channels_data, aliases)
            if not xm:
                skipped.append(f"{ch.name} (no SiriusXM match)")
                continue
            if self._do_fill(ch, xm):
                filled.append(ch.name)
            else:
                failed.append(ch.name)
        parts = []
        if filled:  parts.append(f"Filled EPG TVG IDs: {len(filled)} channel(s)")
        if skipped: parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:  parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _sort_channels(self, params):
        """Renumber channels sequentially from sort_start_number, ordered by SXM channel number.
        Auto-detects start number from the current minimum channel_number if not configured."""
        from apps.channels.models import Channel
        try:
            channels_data, aliases, dispatch_channels, group = self._ch_resolve(params)
        except ValueError as e:
            return {"success": False, "message": str(e)}

        start_raw = (params.get("sort_start_number") or "").strip()
        auto_detected = False
        if start_raw:
            try:
                start_number = int(start_raw)
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid Sort Start Number: {start_raw!r} — enter a whole number or leave blank to auto-detect."}
        else:
            auto_detected = True
            nums = [ch.channel_number for ch in dispatch_channels if ch.channel_number is not None]
            start_number = int(min(nums)) if nums else 1

        # Build ordered list: matched channels sorted by SXM number, unmatched at end
        matched, unmatched = [], []
        for ch in dispatch_channels:
            xm = _match_channel(ch.name, channels_data, aliases)
            if xm and xm.get("sxm_number"):
                matched.append((xm["sxm_number"], ch))
            else:
                unmatched.append(ch)
        matched.sort(key=lambda x: x[0])
        ordered = [ch for _, ch in matched] + unmatched

        # Null out all channel numbers first to avoid unique-within-group constraint conflicts
        if group:
            Channel.objects.filter(channel_group=group).update(channel_number=None)
        else:
            for ch in ordered:
                ch.channel_number = None
                ch.save(update_fields=["channel_number"])

        updated, failed = 0, []
        for i, ch in enumerate(ordered):
            new_num = start_number + i
            try:
                ch.channel_number = new_num
                ch.save(update_fields=["channel_number"])
                updated += 1
            except Exception as e:
                logger.warning(f"tickarr: sort failed for {ch.name}: {e}")
                failed.append(ch.name)

        start_note = " (auto-detected)" if auto_detected else ""
        parts = [f"Sort complete — {updated} channel(s) renumbered from {start_number}{start_note}"]
        if unmatched: parts.append(f"No SXM match (placed at end): {', '.join(c.name for c in unmatched[:10])}")
        if failed:    parts.append("Failed:\n" + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts)}

    def _assign_logos(self, params):
        try:
            channels_data, aliases, dispatch_channels, _ = self._ch_resolve(params)
        except ValueError as e:
            return {"success": False, "message": str(e)}
        assigned, skipped, failed = [], [], []
        for ch in dispatch_channels:
            xm = _match_channel(ch.name, channels_data, aliases)
            if not xm:
                skipped.append(f"{ch.name} (no SiriusXM match)")
                continue
            ok, created = self._do_logos(ch, xm)
            if ok:
                assigned.append(f"{ch.name}" + (" (new)" if created else ""))
            elif not xm.get("logo_url"):
                skipped.append(f"{ch.name} (no logo in channel data)")
            else:
                failed.append(ch.name)
        parts = []
        if assigned: parts.append(f"Assigned logos: {len(assigned)} channel(s)")
        if skipped:  parts.append("Skipped:\n" + "\n".join(f"  • {s}" for s in skipped))
        if failed:   parts.append("Failed:\n"  + "\n".join(f"  • {f}" for f in failed))
        return {"success": not failed, "message": "\n\n".join(parts) or "Nothing to do."}

    def _fill_sxm_epg(self, params):
        """Download Tickarr's own SiriusXM XMLTV and import EPG data into Dispatcharr."""
        import xml.etree.ElementTree as ET
        import io
        import gc
        from datetime import datetime, timedelta, timezone
        from apps.epg.models import EPGSource, EPGData, ProgramData
        from django.db import transaction

        try:
            channels_data, aliases, dispatch_channels, _ = self._ch_resolve(params)
        except ValueError as e:
            return {"success": False, "message": str(e)}

        # Download Tickarr's own hosted XMLTV
        xml_bytes = None
        last_err = None
        for _attempt in range(2):
            try:
                req = urllib.request.Request(TICKARR_SXM_EPG_URL, headers={"User-Agent": "Tickarr/0.1"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    xml_bytes = r.read()
                break
            except Exception as e:
                last_err = e
        if xml_bytes is None:
            return {"success": False, "message": f"Failed to download SiriusXM EPG data: {last_err}"}

        # Strip control characters invalid in XML 1.0
        xml_bytes = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', xml_bytes)

        sxm_src, _ = EPGSource.objects.get_or_create(
            name=TICKARR_SXM_SOURCE,
            defaults={"source_type": "xmltv", "url": TICKARR_SXM_EPG_URL},
        )

        now = datetime.now(timezone.utc)
        purge_before = now - timedelta(days=1)

        def _parse_dt(s):
            s = s.strip()
            dt = datetime.strptime(s[:14], "%Y%m%d%H%M%S")
            tz_str = s[14:].strip()
            if tz_str:
                sign = 1 if tz_str[0] == '+' else -1
                offset = timedelta(hours=int(tz_str[1:3]), minutes=int(tz_str[3:5])) * sign
            else:
                offset = timedelta(0)
            return (dt - offset).replace(tzinfo=timezone.utc)

        # Phase 1: create/update EPGData records from <channel> elements
        existing_epg = {e.tvg_id: e for e in EPGData.objects.filter(epg_source=sxm_src)}
        channel_map = {}
        with transaction.atomic():
            for _ev, elem in ET.iterparse(io.BytesIO(xml_bytes), events=('end',)):
                if elem.tag == 'channel':
                    ch_id = elem.get('id', '').strip()
                    if ch_id:
                        display = (elem.findtext('display-name') or ch_id).strip()
                        icon_el = elem.find('icon')
                        icon_url = (icon_el.get('src', '') if icon_el is not None else '').strip()
                        if ch_id in existing_epg:
                            entry = existing_epg[ch_id]
                            changed = []
                            if entry.name != display: entry.name = display; changed.append('name')
                            if entry.icon_url != icon_url: entry.icon_url = icon_url; changed.append('icon_url')
                            if changed: entry.save(update_fields=changed)
                        else:
                            entry = EPGData.objects.create(tvg_id=ch_id, name=display, icon_url=icon_url, epg_source=sxm_src)
                        channel_map[ch_id] = entry
                    elem.clear()
                elif elem.tag == 'programme':
                    elem.clear()

        # Phase 2: import ProgramData from <programme> elements
        total_programs = 0
        with transaction.atomic():
            ProgramData.objects.filter(epg__epg_source=sxm_src, end_time__lt=purge_before).delete()
            ProgramData.objects.filter(epg__epg_source=sxm_src, start_time__gte=now).delete()
            batch = []
            for _ev, elem in ET.iterparse(io.BytesIO(xml_bytes), events=('end',)):
                if elem.tag == 'channel':
                    elem.clear(); continue
                if elem.tag != 'programme':
                    continue
                ch_id = elem.get('channel', '').strip()
                entry = channel_map.get(ch_id)
                if entry:
                    try:
                        start = _parse_dt(elem.get('start', ''))
                        end   = _parse_dt(elem.get('stop', ''))
                    except Exception:
                        elem.clear(); continue
                    if end > purge_before:
                        batch.append(ProgramData(
                            epg=entry,
                            start_time=start, end_time=end,
                            title=(elem.findtext('title') or '').strip(),
                            sub_title=(elem.findtext('sub-title') or '').strip() or None,
                            description=(elem.findtext('desc') or '').strip(),
                            tvg_id=ch_id, custom_properties={},
                        ))
                        if len(batch) >= 2000:
                            ProgramData.objects.bulk_create(batch)
                            total_programs += len(batch)
                            batch = []
                elem.clear()
            if batch:
                ProgramData.objects.bulk_create(batch)
                total_programs += len(batch)

        del xml_bytes

        # Fuzzy-match dispatch channels to EPGData and assign channel.epg_data
        epg_lookup = {}
        for entry in channel_map.values():
            norm = _normalize(entry.name)
            epg_lookup[norm] = entry

        matched, unmatched = 0, []
        with transaction.atomic():
            for ch in dispatch_channels:
                key = _normalize(ch.name)
                xm = _match_channel(ch.name, channels_data, aliases)
                # Try alias-resolved name first, then direct
                best = (epg_lookup.get(_normalize(xm["name"])) if xm else None) or epg_lookup.get(key)
                if best:
                    if ch.epg_data_id != best.id:
                        ch.epg_data = best
                        ch.save(update_fields=['epg_data'])
                    matched += 1
                else:
                    unmatched.append(ch.name)

        n_ch = len(channel_map)
        del channel_map, epg_lookup
        gc.collect()

        sxm_src.status = "success"
        sxm_src.last_message = f"Tickarr: {n_ch:,} channels, {total_programs:,} programs"
        sxm_src.save(update_fields=["status", "last_message"])

        lines = [
            f"SiriusXM Fill EPG complete\n",
            f"  Channels assigned : {matched:,} / {len(dispatch_channels):,}",
            f"  Programs loaded   : {total_programs:,}  ({n_ch:,} XMLTV channels)",
        ]
        if unmatched:
            lines.append(f"  No match ({len(unmatched)}): " + ", ".join(unmatched[:10]))
        return {"success": True, "message": "\n".join(lines)}

    def _fill_and_sort(self, params):
        r1 = self._fill_sxm_epg(params)
        r2 = self._sort_channels(params)
        msg = "\n\n".join(filter(None, [r1["message"], r2["message"]]))
        return {"success": r1["success"] and r2["success"], "message": msg}

    def _fill_sort_logos(self, params):
        r1 = self._fill_sxm_epg(params)
        r2 = self._sort_channels(params)
        r3 = self._assign_logos(params)
        msg = "\n\n".join(filter(None, [r1["message"], r2["message"], r3["message"]]))
        return {"success": all(r["success"] for r in [r1, r2, r3]), "message": msg}

    def _clean_orphans(self, params):
        from core.models import StreamProfile
        mappings = _get_mappings()
        active_ticker_ids = {m["ticker_profile_id"] for m in mappings.values()}

        # Primary sweep: profiles whose name starts with PROFILE_PREFIX
        named = list(StreamProfile.objects.filter(name__startswith=PROFILE_PREFIX))
        orphans = [p for p in named if p.id not in active_ticker_ids]

        # Secondary sweep: catch FIFO-era leftovers whose name didn't use the current
        # prefix (different dash, older naming) but whose parameters contain tickarr_data
        seen_ids = {p.id for p in named}
        for p in StreamProfile.objects.all():
            if p.id in seen_ids or p.id in active_ticker_ids:
                continue
            if "tickarr_data" in (p.parameters or ""):
                orphans.append(p)

        if not orphans:
            return {"success": True, "message": "No orphaned profiles found."}
        deleted = []
        for profile in orphans:
            try:
                profile.delete()
                deleted.append(profile.name)
            except Exception as e:
                logger.warning(f"tickarr: could not delete profile {profile.name}: {e}")
        return {"success": True, "message": f"Deleted {len(deleted)} orphaned profile(s):\n" + "\n".join(f"  • {n}" for n in deleted)}

    def _redis_diag(self, params):
        rc = _get_redis_client()
        if rc is None:
            return {"success": False, "message": (
                "Redis unavailable — could not connect.\n\n"
                "Stream-start detection is disabled. The sweep loop will poll all active "
                "channels every 15 seconds (one bulk stellartunerlog.com fetch per cycle)."
            )}

        lines = ["Redis: connected\n"]

        # Scan for active stream keys (both v0.24 and v0.25 patterns)
        try:
            ts_keys = (list(rc.scan_iter("live:channel:*", count=500)) +
                       list(rc.scan_iter("ts_proxy:channel:*", count=500)))
            if ts_keys:
                lines.append(f"Stream keys ({len(ts_keys)} found):")
                for raw in ts_keys[:40]:
                    k = raw.decode() if isinstance(raw, bytes) else raw
                    try:
                        ktype = rc.type(raw).decode()
                        if ktype == "set":
                            n = rc.scard(raw)
                            lines.append(f"  {k}  [set, {n} member(s)]")
                        elif ktype == "string":
                            v = (rc.get(raw) or b"").decode(errors="replace")
                            lines.append(f"  {k}  [string: {v[:80]}]")
                        else:
                            lines.append(f"  {k}  [{ktype}]")
                    except Exception as ex:
                        lines.append(f"  {k}  [error: {ex}]")
                if len(ts_keys) > 40:
                    lines.append(f"  ... and {len(ts_keys) - 40} more")
            else:
                lines.append("No stream keys found — scanning ALL keys to find active stream pattern:\n")
                try:
                    all_keys = list(rc.scan_iter("*", count=500))
                    if all_keys:
                        lines.append(f"All Redis keys ({len(all_keys)} total, showing first 60):")
                        for raw in all_keys[:60]:
                            k = raw.decode() if isinstance(raw, bytes) else raw
                            try:
                                ktype = rc.type(raw).decode()
                                if ktype == "string":
                                    v = (rc.get(raw) or b"").decode(errors="replace")
                                    lines.append(f"  {k}  [string: {v[:60]}]")
                                elif ktype == "set":
                                    n = rc.scard(raw)
                                    lines.append(f"  {k}  [set, {n} member(s)]")
                                else:
                                    lines.append(f"  {k}  [{ktype}]")
                            except Exception:
                                lines.append(f"  {k}")
                        if len(all_keys) > 60:
                            lines.append(f"  ... and {len(all_keys) - 60} more")
                    else:
                        lines.append("  Redis is empty — no keys at all.")
                except Exception as e2:
                    lines.append(f"  Full scan error: {e2}")
        except Exception as e:
            lines.append(f"ts_proxy scan error: {e}")

        # Show what _redis_scan_active() currently returns
        active = _redis_scan_active()
        if active is None:
            lines.append("\n_redis_scan_active(): returned None (error during scan)")
        else:
            mappings = _get_mappings()
            ch_list = _build_channel_list(mappings)
            mapped_ids = {c[0] for c in ch_list}
            matched = active & mapped_ids
            lines.append(f"\n_redis_scan_active(): {len(active)} active channel ID(s) total, "
                         f"{len(matched)} matching mapped channels")
            if matched:
                id_to_name = {c[0]: c[2] for c in ch_list}
                for cid in sorted(matched):
                    lines.append(f"  • [{cid}] {id_to_name.get(cid, '?')}")

        return {"success": True, "message": "\n".join(lines)}

    def _reload_poller(self, params):
        global _scheduler_thread, _stop_event
        _stop_event.set()
        if _scheduler_thread:
            _scheduler_thread.join(timeout=5)
        _stop_event = threading.Event()
        _scheduler_thread = threading.Thread(
            target=_poll_loop,
            args=(_stop_event,),
            daemon=True,
            name="tickarr-poller",
        )
        _scheduler_thread.start()
        logger.info("tickarr: poller thread reloaded via action")
        return {"success": True, "message": "Poller thread restarted. Live data will resume within 15 seconds."}

    def _restart_dispatcharr(self, params):
        import signal as _signal

        def _do_restart():
            time.sleep(2)
            try:
                result = subprocess.run(
                    ["pgrep", "-of", "gunicorn"],
                    capture_output=True, text=True
                )
                pid = int(result.stdout.strip())
                logger.info(f"tickarr: sending SIGHUP to gunicorn master PID {pid}")
                os.kill(pid, _signal.SIGHUP)
            except Exception as e:
                logger.warning(f"tickarr: gunicorn SIGHUP failed ({e}), falling back to PID 1")
                try:
                    os.kill(1, _signal.SIGHUP)
                except Exception as e2:
                    logger.error(f"tickarr: restart failed: {e2}")

        threading.Thread(target=_do_restart, daemon=True).start()
        return {"success": True, "message": "Restart signal sent. Dispatcharr will reload in ~2 seconds.\n\nRefresh this page in about 15 seconds."}

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _resolve_channels(self, params, prefix=""):
        from apps.channels.models import Channel, ChannelGroup
        target_type = params.get(f"{prefix}target_type", "group")
        if target_type == "group":
            group_id = params.get(f"{prefix}channel_group_id")
            if not group_id:
                return []
            try:
                group = ChannelGroup.objects.get(id=int(group_id))
                return list(Channel.objects.filter(channel_group=group).order_by("name"))
            except ChannelGroup.DoesNotExist:
                return []
        else:
            channel_id = params.get(f"{prefix}channel_id")
            if not channel_id:
                return []
            try:
                return [Channel.objects.get(id=int(channel_id))]
            except Channel.DoesNotExist:
                return []
