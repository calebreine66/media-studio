from __future__ import annotations

from dataclasses import replace

from media_studio.core.capabilities import Capabilities
from media_studio.models import Options


LOSSLESS = {"png", "tiff", "bmp", "ffv1", "flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"}
QUALITY_VIDEO = {"libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9"}
TWO_PASS = {"libx264", "libvpx-vp9", "mpeg4"}
SWITCHABLE_LOSSLESS = {"libx264", "libx265", "libwebp", "libwebp_anim"}


def recommended(
    caps: Capabilities, kind: str, operation: str, fmt: str = "", profile: str = "balanced"
) -> Options:
    available = caps.formats(kind)
    default = {"video": "mp4", "image": "png" if operation == "convert" else "jpg", "audio": "mp3"}[kind]
    chosen = next((f for f in available if f.key == (fmt or default)), available[0] if available else None)
    if chosen is None:
        from media_studio.models import MediaError

        raise MediaError(f"No supported {kind} output encoders are installed.")
    enc = caps.choices(chosen)[0].name
    quality = {"high": 18, "balanced": 23, "small": 29, "smallest": 34}.get(profile, 23)
    if enc in {"libsvtav1", "libaom-av1", "libvpx-vp9"}:
        quality += 8
    if kind == "image":
        quality = {"high": 95, "balanced": 82, "small": 65, "smallest": 45}.get(profile, 82)
    audio = caps.choices(chosen, True)[0].name if chosen.audio else enc if kind == "audio" else ""
    preset = (
        "6"
        if enc == "libsvtav1"
        else "4"
        if enc == "libaom-av1"
        else "2"
        if enc == "libvpx-vp9"
        else "medium"
    )
    o = Options(
        kind=kind,
        operation=operation,
        format=chosen.key,
        encoder=enc,
        quality=quality,
        preset=preset,
        audio_encoder=audio,
        audio_bitrate={"high": 256, "balanced": 192, "small": 128, "smallest": 96}.get(profile, 192),
        compression_level=9 if operation == "compress" else 6,
        rate_control="quality" if enc in QUALITY_VIDEO or kind == "image" else "bitrate",
    )
    if kind == "video" and enc not in LOSSLESS and enc != "prores_ks":
        o.pixel_format = "yuv420p" if "yuv420p" in caps.encoders[enc].pixels else ""
    if kind == "image" and chosen.key in {"jpg", "bmp"}:
        o.alpha = "background"
    return o


BUILTINS = (
    ("MP4 compatibility", "video", "mp4", "libx264", {}),
    ("High quality H.264", "video", "mp4", "libx264", {"quality": 18, "preset": "slow"}),
    ("Small H.265", "video", "mp4", "libx265", {"quality": 28}),
    ("AV1 high efficiency", "video", "mkv", "libsvtav1", {"quality": 32, "preset": "6"}),
    ("Web video", "video", "webm", "libvpx-vp9", {"quality": 32, "preset": "2"}),
    ("Archive · lossless FFV1", "video", "mkv", "ffv1", {"audio_encoder": "flac", "pixel_format": ""}),
    ("Lossless PNG", "image", "png", "png", {"compression_level": 9}),
    ("High quality JPEG", "image", "jpg", "mjpeg", {"quality": 95, "alpha": "background"}),
    ("Small JPEG", "image", "jpg", "mjpeg", {"quality": 65, "alpha": "background"}),
    ("WebP high quality", "image", "webp", "libwebp", {"quality": 90}),
    ("WebP lossless", "image", "webp", "libwebp", {"lossless": True}),
    ("MP3 high quality", "audio", "mp3", "libmp3lame", {"audio_bitrate": 320}),
    ("MP3 small", "audio", "mp3", "libmp3lame", {"audio_bitrate": 128}),
    ("AAC high quality", "audio", "m4a", "aac", {"audio_bitrate": 256}),
    ("Opus voice", "audio", "opus", "libopus", {"audio_bitrate": 32, "channels": 1}),
    ("Opus music", "audio", "opus", "libopus", {"audio_bitrate": 128}),
    ("FLAC lossless", "audio", "flac", "flac", {"compression_level": 8}),
    ("WAV uncompressed", "audio", "wav", "pcm_s24le", {}),
)


def builtins(caps: Capabilities, kind: str, operation: str) -> dict[str, Options]:
    result = {}
    for name, media, fmt, encoder, changes in BUILTINS:
        if media != kind or encoder not in caps.encoders:
            continue
        if not any(f.key == fmt for f in caps.formats(kind)):
            continue
        o = recommended(caps, kind, operation, fmt)
        changes = {**changes, "encoder": encoder}
        if kind == "audio":
            changes["audio_encoder"] = encoder
        result[name] = replace(o, **changes)
    return result


def quality_description(o: Options) -> str:
    if o.encoder == "copy":
        return "Stream copy · no generational quality loss. Streams must fit the destination container."
    if o.encoder.startswith("pcm_"):
        return "Uncompressed audio · sample rate, channels and bit depth changes can alter the source."
    if o.encoder in LOSSLESS or o.lossless:
        return "Lossless encoding · resizing, color or audio processing can still change the source. Size may increase."
    if o.format == "gif":
        return "Palette-based image · colors may change. Image workflows export the first frame only."
    return "Lossy / quality-based encoding · smaller files trade some quality for space. Size reduction is not guaranteed."
