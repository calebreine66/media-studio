from __future__ import annotations

import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from media_studio.core.process import capture
from media_studio.models import MediaError


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    kind: str
    muxer: str
    encoders: tuple[str, ...]
    audio: tuple[str, ...] = ()
    video_copy: tuple[str, ...] = ()
    audio_copy: tuple[str, ...] = ()


VIDEO = ("libx264", "libx265", "libsvtav1", "libaom-av1", "h264_videotoolbox", "hevc_videotoolbox")
SOUND = ("aac", "libmp3lame", "libopus", "libvorbis", "flac", "pcm_s16le", "pcm_s24le", "ac3")
# Compatibility policy is curated; every selectable entry is intersected with the actual installation.
FORMATS = (
    Format(
        "mp4",
        "MP4",
        "video",
        "mp4",
        VIDEO + ("mpeg4",),
        ("aac", "libmp3lame", "ac3"),
        ("h264", "hevc", "av1", "mpeg4"),
        ("aac", "mp3", "ac3"),
    ),
    Format(
        "mkv",
        "Matroska · MKV",
        "video",
        "matroska",
        VIDEO + ("libvpx-vp9", "ffv1", "mpeg4"),
        SOUND,
        ("h264", "hevc", "av1", "vp9", "vp8", "mpeg4", "mpeg2video", "ffv1", "prores"),
        ("aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "ac3", "eac3", "dts"),
    ),
    Format(
        "mov",
        "QuickTime · MOV",
        "video",
        "mov",
        ("libx264", "libx265", "prores_ks", "mpeg4"),
        ("aac", "pcm_s16le", "pcm_s24le", "ac3"),
        ("h264", "hevc", "prores", "mpeg4", "mjpeg"),
        ("aac", "pcm_s16le", "pcm_s24le", "ac3"),
    ),
    Format(
        "webm",
        "WebM",
        "video",
        "webm",
        ("libvpx-vp9", "libsvtav1", "libaom-av1"),
        ("libopus", "libvorbis"),
        ("vp8", "vp9", "av1"),
        ("opus", "vorbis"),
    ),
    Format(
        "avi",
        "AVI",
        "video",
        "avi",
        ("mpeg4", "libx264", "ffv1"),
        ("libmp3lame", "pcm_s16le"),
        ("mpeg4", "h264", "ffv1", "mjpeg"),
        ("mp3", "pcm_s16le"),
    ),
    Format(
        "mpg",
        "MPEG",
        "video",
        "mpeg",
        ("mpeg2video", "mpeg1video"),
        ("mp2",),
        ("mpeg2video", "mpeg1video"),
        ("mp2",),
    ),
    Format(
        "ts",
        "MPEG transport stream",
        "video",
        "mpegts",
        ("libx264", "libx265", "mpeg2video"),
        ("aac", "ac3", "mp2"),
        ("h264", "hevc", "mpeg2video"),
        ("aac", "ac3", "mp2"),
    ),
    Format("m4v", "M4V", "video", "mp4", ("libx264", "libx265"), ("aac",), ("h264", "hevc"), ("aac",)),
    Format("png", "PNG", "image", "image2", ("png",)),
    Format("jpg", "JPEG", "image", "image2", ("mjpeg",)),
    Format("webp", "WebP", "image", "image2", ("libwebp", "libwebp_anim")),
    Format("avif", "AVIF", "image", "avif", ("libaom-av1", "libsvtav1")),
    Format("tiff", "TIFF", "image", "image2", ("tiff",)),
    Format("bmp", "BMP", "image", "image2", ("bmp",)),
    Format("gif", "GIF · first frame", "image", "image2", ("gif",)),
    Format("jp2", "JPEG 2000", "image", "image2", ("jpeg2000", "libopenjpeg")),
    Format("mp3", "MP3", "audio", "mp3", ("libmp3lame",), audio_copy=("mp3",)),
    Format(
        "m4a",
        "AAC · M4A",
        "audio",
        "ipod",
        ("aac", "alac"),
        audio_copy=(
            "aac",
            "alac",
        ),
    ),
    Format("aac", "AAC", "audio", "adts", ("aac",), audio_copy=("aac",)),
    Format(
        "wav",
        "WAV",
        "audio",
        "wav",
        ("pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"),
        audio_copy=("pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"),
    ),
    Format("flac", "FLAC", "audio", "flac", ("flac",), audio_copy=("flac",)),
    Format(
        "ogg",
        "Ogg Vorbis",
        "audio",
        "ogg",
        ("libvorbis", "libopus", "flac"),
        audio_copy=("vorbis", "opus", "flac"),
    ),
    Format("opus", "Opus", "audio", "opus", ("libopus",), audio_copy=("opus",)),
    Format("ac3", "AC-3", "audio", "ac3", ("ac3",), audio_copy=("ac3",)),
    Format("wma", "Windows Media Audio", "audio", "asf", ("wmav2",), audio_copy=("wmav2",)),
)

ENCODER_LABELS = {
    "libx264": "H.264 · x264",
    "libx265": "H.265 / HEVC · x265",
    "libsvtav1": "AV1 · SVT-AV1",
    "libaom-av1": "AV1 · libaom",
    "libvpx-vp9": "VP9 · libvpx",
    "prores_ks": "Apple ProRes",
    "ffv1": "FFV1 · lossless",
    "h264_videotoolbox": "H.264 · Apple hardware",
    "hevc_videotoolbox": "HEVC · Apple hardware",
    "libmp3lame": "MP3 · LAME",
    "libopus": "Opus",
    "libvorbis": "Vorbis",
    "libwebp": "WebP",
    "libwebp_anim": "WebP",
}


@dataclass
class Encoder:
    name: str
    kind: str
    description: str
    pixels: tuple[str, ...] = ()
    sample_formats: tuple[str, ...] = ()
    sample_rates: tuple[int, ...] = ()
    options: frozenset[str] = frozenset()

    @property
    def label(self) -> str:
        return ENCODER_LABELS.get(self.name, self.name.upper().replace("_", " "))


@dataclass
class Capabilities:
    ffmpeg: str
    ffprobe: str
    version: str
    encoders: dict[str, Encoder]
    muxers: set[str]
    decoders: set[str] = field(default_factory=set)
    filters: set[str] = field(default_factory=set)
    hardware: tuple[str, ...] = ()
    unavailable_hardware: tuple[str, ...] = ()

    def formats(self, kind: str) -> list[Format]:
        return [
            f
            for f in FORMATS
            if f.kind == kind
            and f.muxer in self.muxers
            and any(e in self.encoders for e in f.encoders)
            and (not f.audio or any(e in self.encoders for e in f.audio))
        ]

    def format(self, kind: str, key: str) -> Format:
        for fmt in self.formats(kind):
            if fmt.key == key:
                return fmt
        raise MediaError(f"{key.upper()} output is unavailable in this FFmpeg installation.")

    def choices(self, fmt: Format, audio: bool = False) -> list[Encoder]:
        return [self.encoders[e] for e in (fmt.audio if audio else fmt.encoders) if e in self.encoders]


def locate(name: str, configured: str = "") -> str:
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            path /= name + (".exe" if os.name == "nt" else "")
        return str(path)
    bundled = Path(__file__).resolve().parents[2] / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name) or name


def detect(ffmpeg: str = "", ffprobe: str = "") -> Capabilities:
    ffmpeg, ffprobe = locate("ffmpeg", ffmpeg), locate("ffprobe", ffprobe)
    try:
        version = capture([ffmpeg, "-version"]).splitlines()[0]
        capture([ffprobe, "-version"])
    except MediaError as exc:
        raise MediaError(
            "FFmpeg or FFprobe could not start. Set working executable paths in Settings.",
            exc.details or str(exc),
        ) from exc
    commands = ["-encoders", "-muxers", "-decoders", "-filters", "-hwaccels"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        raw = dict(zip(commands, pool.map(lambda c: capture([ffmpeg, "-hide_banner", c]), commands)))
    encoders = {}
    for line in raw["-encoders"].splitlines():
        match = re.match(r"^\s*([VAS])[A-Z.]{5}\s+(\S+)\s+(.*)$", line)
        if match and match[2] != "=":
            encoders[match[2]] = Encoder(
                match[2], {"V": "video", "A": "audio", "S": "subtitle"}[match[1]], match[3]
            )
    muxers = set()
    for line in raw["-muxers"].splitlines():
        match = re.match(r"^\s*E\s+(\S+)\s", line)
        if match and match[1] != "=":
            muxers.update(match[1].split(","))
    wanted = {e for f in FORMATS for e in f.encoders + f.audio}

    def describe(name: str) -> Encoder:
        enc = encoders[name]
        details = capture([ffmpeg, "-hide_banner", "-h", f"encoder={name}"])
        for label, attr in (
            ("pixel formats", "pixels"),
            ("sample formats", "sample_formats"),
            ("sample rates", "sample_rates"),
        ):
            match = re.search(rf"Supported {label}:\s*([^\n]+)", details)
            if match:
                values = match[1].split()
                setattr(
                    enc,
                    attr,
                    tuple(int(v) for v in values if v.isdigit()) if attr == "sample_rates" else tuple(values),
                )
        enc.options = frozenset(re.findall(r"^\s+-(\S+)\s", details, re.MULTILINE))
        return enc

    with ThreadPoolExecutor(max_workers=4) as pool:
        for enc in pool.map(describe, sorted(wanted & encoders.keys())):
            encoders[enc.name] = enc
    unavailable = []
    for name in sorted(wanted & encoders.keys()):
        if "videotoolbox" not in name:
            continue
        try:
            capture(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=size=128x128:duration=0.1",
                    "-frames:v",
                    "1",
                    "-c:v",
                    name,
                    "-b:v",
                    "500k",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=15,
            )
        except MediaError:
            unavailable.append(name)
            del encoders[name]
    decoders = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\w+)\s", raw["-decoders"], re.MULTILINE))
    filters = set(re.findall(r"^\s*[TSC.]{2,3}\s+(\w+)\s", raw["-filters"], re.MULTILINE))
    hardware = tuple(line.strip() for line in raw["-hwaccels"].splitlines()[1:] if line.strip())
    return Capabilities(
        ffmpeg, ffprobe, version, encoders, muxers, decoders, filters, hardware, tuple(unavailable)
    )
