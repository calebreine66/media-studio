from __future__ import annotations

import math
import os
import re
import shlex
import shutil
from fractions import Fraction
from pathlib import Path

from media_studio.core.capabilities import Capabilities
from media_studio.models import MediaError, MediaInfo, Options
from media_studio.presets import LOSSLESS, QUALITY_VIDEO, SWITCHABLE_LOSSLESS, TWO_PASS


def expert_arguments(value: str) -> list[str]:
    """A deliberately limited set of output options; no extra inputs, outputs, or file-reading filters."""
    allowed = {
        "-aq-mode",
        "-aq-strength",
        "-rc-lookahead",
        "-sc_threshold",
        "-qcomp",
        "-qblur",
        "-slices",
        "-slice-max-size",
        "-compression_level",
        "-global_quality",
        "-qmin",
        "-qmax",
        "-max_muxing_queue_size",
        "-frame_duration",
        "-application",
        "-tune",
        "-deadline",
        "-row-mt",
        "-tile-columns",
        "-tile-rows",
        "-cutoff",
        "-aac_coder",
        "-dither_method",
    }
    try:
        args = shlex.split(value)
    except ValueError as exc:
        raise MediaError("Additional FFmpeg arguments contain an unmatched quote.") from exc
    if len(args) % 2:
        raise MediaError("Enter additional arguments as option/value pairs, for example: -aq-strength 0.8")
    for key, val in zip(args[::2], args[1::2]):
        if key not in allowed:
            raise MediaError(
                f"Expert option {key} is not supported. Only the documented output tuning options are allowed."
            )
        if not re.fullmatch(r"[-+a-zA-Z0-9_.,:]+", val):
            raise MediaError(f"Invalid value for {key}. Paths, URLs and filter graphs are not accepted here.")
    return args


def same_file(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except OSError:
        return False


def unique_output(path: Path, reserved: set[Path] | None = None) -> Path:
    reserved = reserved or set()
    candidate, index = path, 2
    while candidate.exists() or candidate.is_symlink() or candidate.resolve() in reserved:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        index += 1
    return candidate


def suggested_output(source: MediaInfo, directory: Path, options: Options, name: str = "") -> Path:
    if name:
        if Path(name).name != name or name in {".", ".."} or any(c in name for c in "/\\\0"):
            raise MediaError("Output filename must be a name, without a directory path.")
        stem = Path(name).stem if Path(name).suffix else name
    else:
        stem = source.path.stem + ("_compressed" if options.operation == "compress" else "")
    output = directory.expanduser().resolve() / f"{stem}.{options.format}"
    if same_file(source.path, output):
        output = output.with_name(f"{stem}_{options.operation}ed.{options.format}")
    return output


def video_bitrate(source: MediaInfo, o: Options) -> int:
    if o.target_mb <= 0:
        return o.bitrate
    if source.duration <= 0:
        raise MediaError("Target size needs a known source duration. Choose bitrate or quality mode instead.")
    audio = 0 if not source.audio or o.audio_mode == "remove" else o.audio_bitrate
    if o.audio_mode == "copy" and source.audio:
        try:
            audio = int(source.audio.get("bit_rate", 0)) // 1000
        except (TypeError, ValueError):
            audio = 0
        if not audio:
            raise MediaError(
                "Target size cannot estimate this copied audio stream. Convert audio or disable target size."
            )
    result = int(o.target_mb * 1_000_000 * 8 / source.duration / 1000 * 0.98 - audio)
    if result < 50:
        raise MediaError(
            "Target size is too small for this duration and audio bitrate. Increase the target size."
        )
    return result


def validate(
    source: MediaInfo,
    output: Path,
    o: Options,
    caps: Capabilities,
    replace: bool = False,
    filesystem: bool = True,
) -> None:
    def require(condition: bool, message: str):
        if not condition:
            raise MediaError(message)

    require(o.kind == source.kind, f"This source is {source.kind} media. Use the {source.kind} workflow.")
    require(o.operation in {"convert", "compress"}, "Choose conversion or compression.")
    fmt = caps.format(o.kind, o.format)
    require(
        o.encoder == "copy" or o.encoder in fmt.encoders and o.encoder in caps.encoders,
        "The selected encoder is unavailable or incompatible with the output format.",
    )
    require(o.kind != "image" or o.encoder != "copy", "Image workflows require an image encoder.")
    require(output.suffix.lower() == "." + fmt.key, "Output extension does not match the selected format.")
    require(not same_file(source.path, output), "Output cannot be the source file, including a link to it.")
    require(o.resize in {"original", "custom", "fit", "percent"}, "Invalid resize mode.")
    require(o.scaler in {"neighbor", "bilinear", "bicubic", "lanczos", "area"}, "Choose a supported scaler.")
    require(o.rate_control in {"quality", "bitrate", "cbr"}, "Choose a supported rate-control method.")
    require(
        o.audio_rate_control in {"bitrate", "quality", "vbr", "cbr"},
        "Choose a supported audio rate-control method.",
    )
    require(o.audio_mode in {"convert", "copy", "remove"}, "Choose a supported audio handling mode.")
    require(o.metadata in {"preserve", "remove"}, "Choose whether to preserve or remove metadata.")
    require(o.subtitles in {"remove", "copy", "convert"}, "Choose a supported subtitle handling mode.")
    require(o.alpha in {"preserve", "remove", "background"}, "Choose a supported transparency mode.")
    require(o.rotate in {"none", "clockwise", "counterclockwise", "180"}, "Invalid rotation.")
    require(o.flip in {"none", "horizontal", "vertical"}, "Invalid flip direction.")
    for value, low, high, name in (
        (o.width, 1, 16384, "Width"),
        (o.height, 1, 16384, "Height"),
        (o.scale_percent, 1, 400, "Scale percentage"),
        (o.bitrate, 1, 1_000_000, "Bitrate"),
        (o.max_bitrate, 0, 1_000_000, "Maximum bitrate"),
        (o.buffer_size, 0, 2_000_000, "Buffer size"),
        (o.audio_bitrate, 8, 1536, "Audio bitrate"),
        (o.channels, 0, 8, "Channels"),
        (o.sample_rate, 0, 384000, "Sample rate"),
        (o.volume_db, -60, 30, "Volume gain"),
        (o.target_mb, 0, 1_000_000, "Target size"),
        (o.compression_level, 0, 12, "Compression level"),
        (o.threads, 0, 128, "Thread count"),
        (o.gop, 0, 10000, "GOP size"),
        (o.b_frames, -1, 16, "B-frames"),
    ):
        require(
            isinstance(value, (int, float)) and math.isfinite(value) and low <= value <= high,
            f"{name} must be between {low} and {high}.",
        )
    require(o.sample_rate == 0 or o.sample_rate >= 8000, "Sample rate must be at least 8000 Hz.")
    if o.fps:
        try:
            rate = float(Fraction(o.fps))
        except (ValueError, ZeroDivisionError):
            raise MediaError(
                "Frame rate must be a number or fraction, for example 29.97 or 30000/1001."
            ) from None
        require(0 < rate <= 240, "Frame rate must be above 0 and no more than 240.")
    if o.crop:
        require(
            bool(re.fullmatch(r"\d+:\d+:\d+:\d+", o.crop)),
            "Crop must be width:height:x:y, using whole pixels.",
        )
        w, h, x, y = map(int, o.crop.split(":"))
        require(
            w > 0
            and h > 0
            and x + w <= source.video.get("width", 0)
            and y + h <= source.video.get("height", 0),
            "Crop rectangle must fit within the source image.",
        )
    require(
        bool(re.fullmatch(r"#[0-9a-fA-F]{6}", o.background)),
        "Background color must be a six-digit hex color.",
    )
    for val, choices, label in (
        (o.color_space, {"", "bt709", "bt470bg", "smpte170m", "bt2020nc"}, "color space"),
        (o.color_range, {"", "tv", "pc"}, "color range"),
        (o.color_primaries, {"", "bt709", "bt470bg", "smpte170m", "bt2020"}, "color primaries"),
        (
            o.color_transfer,
            {"", "bt709", "smpte170m", "iec61966-2-1", "smpte2084", "arib-std-b67"},
            "transfer",
        ),
    ):
        require(val in choices, f"Unsupported {label} value.")
    filtering = (
        o.resize != "original"
        or o.fps
        or o.crop
        or o.rotate != "none"
        or o.flip != "none"
        or any(
            (
                o.deinterlace,
                o.denoise,
                o.sharpen,
                o.grayscale,
                o.pixel_format,
                o.color_space,
                o.color_range,
                o.color_primaries,
                o.color_transfer,
            )
        )
    )
    if o.kind in {"image", "video"} and o.encoder != "copy":
        w, h = source.video.get("width", 0), source.video.get("height", 0)
        if o.crop:
            w, h = map(int, o.crop.split(":")[:2])
        if o.rotate in {"clockwise", "counterclockwise"}:
            w, h = h, w
        if o.resize == "percent":
            w, h = int(w * o.scale_percent / 100), int(h * o.scale_percent / 100)
        elif o.resize in {"custom", "fit"}:
            if o.keep_aspect or o.resize == "fit":
                scale = min(o.width / max(1, w), o.height / max(1, h))
                w, h = int(w * scale), int(h * scale)
            else:
                w, h = o.width, o.height
        minimum = 2 if o.kind == "video" else 1
        require(
            w >= minimum and h >= minimum, "The requested resize would produce an empty or too-small image."
        )
        if o.encoder == "libsvtav1":
            require(
                w >= 64 and h >= 64,
                "SVT-AV1 needs dimensions of at least 64 × 64. Resize the image or choose another encoder.",
            )
    if o.encoder == "copy":
        codec = source.video.get("codec_name") if o.kind == "video" else source.audio.get("codec_name")
        require(
            codec in (fmt.video_copy if o.kind == "video" else fmt.audio_copy),
            f"The source {codec} stream cannot be copied into {fmt.label}. Choose an encoder.",
        )
        if o.kind == "video":
            require(
                not filtering and not o.target_mb and not o.two_pass,
                "Stream copy cannot resize, filter, change frame rate or pixel format, or target a size. Reset those controls.",
            )
    else:
        enc = caps.encoders[o.encoder]
        require(
            not o.pixel_format or o.pixel_format in enc.pixels,
            "The pixel format is not supported by this encoder.",
        )
        require(
            not o.lossless or o.encoder in LOSSLESS | SWITCHABLE_LOSSLESS,
            "This encoder has no supported lossless mode.",
        )
        if o.kind == "image":
            require(1 <= o.quality <= 100, "Image quality must be between 1 and 100.")
        elif o.kind == "video" and o.encoder in QUALITY_VIDEO:
            require(
                0 <= o.quality <= (51 if o.encoder in {"libx264", "libx265"} else 63),
                "Quality is outside this encoder's range.",
            )
        if o.encoder in {"libx264", "libx265"}:
            require(
                o.preset
                in {
                    "ultrafast",
                    "superfast",
                    "veryfast",
                    "faster",
                    "fast",
                    "medium",
                    "slow",
                    "slower",
                    "veryslow",
                },
                "Choose a valid x264/x265 speed preset.",
            )
        if o.encoder in {"libsvtav1", "libaom-av1", "libvpx-vp9"}:
            require(
                o.preset.isdigit()
                and 0 <= int(o.preset) <= {"libsvtav1": 13, "libaom-av1": 8, "libvpx-vp9": 5}[o.encoder],
                "Choose a valid encoder speed preset.",
            )
        require(
            not o.profile
            or o.encoder == "libx264"
            and o.profile in {"baseline", "main", "high", "high10", "high422", "high444"}
            or o.encoder == "prores_ks"
            and o.profile in {"0", "1", "2", "3", "4", "5"},
            "Profile is unsupported for this encoder.",
        )
        require(
            not o.level
            or o.encoder == "libx264"
            and o.level in {"3.0", "3.1", "4.0", "4.1", "4.2", "5.0", "5.1", "5.2", "6.0", "6.1", "6.2"},
            "Level is unsupported for this encoder.",
        )
        if o.profile in {"baseline", "main", "high"}:
            require(
                not o.lossless,
                "This H.264 profile does not support lossless encoding. Select Automatic profile.",
            )
            require(
                not o.pixel_format or o.pixel_format in {"yuv420p", "yuvj420p", "nv12", "nv21"},
                "This H.264 profile requires 8-bit 4:2:0 pixels.",
            )
        if o.profile == "baseline":
            require(o.b_frames <= 0, "H.264 Baseline does not allow B-frames.")
    require(
        not o.two_pass
        or o.kind == "video"
        and o.encoder in TWO_PASS
        and (o.rate_control != "quality" or o.target_mb > 0)
        and not o.lossless,
        "Two-pass encoding requires a supported bitrate-based video encoder.",
    )
    if o.target_mb:
        require(
            o.kind == "video" and o.encoder not in LOSSLESS and o.encoder != "copy" and not o.lossless,
            "Target size requires a lossy video encoder.",
        )
        video_bitrate(source, o)
    if o.kind == "audio" or o.kind == "video" and source.audio and o.audio_mode != "remove":
        audio_encoder = (
            o.encoder if o.kind == "audio" else o.audio_encoder if o.audio_mode == "convert" else "copy"
        )
        if audio_encoder == "copy":
            require(
                source.audio.get("codec_name") in fmt.audio_copy,
                "Source audio is incompatible with this container. Convert or remove audio.",
            )
            require(
                not any((o.sample_rate, o.channels, o.sample_format, o.volume_db, o.normalize)),
                "Audio stream copy cannot resample, change channels, adjust volume, or normalize.",
            )
        else:
            require(
                audio_encoder in (fmt.encoders if o.kind == "audio" else fmt.audio)
                and audio_encoder in caps.encoders,
                "The audio encoder is incompatible with the output container.",
            )
            enc = caps.encoders[audio_encoder]
            require(
                not o.sample_format or o.sample_format in enc.sample_formats,
                "Sample format is unsupported by this audio encoder.",
            )
            require(
                not o.sample_rate or not enc.sample_rates or o.sample_rate in enc.sample_rates,
                "Sample rate is unsupported by this audio encoder.",
            )
            require(
                o.audio_rate_control != "quality" or audio_encoder in {"libmp3lame", "libvorbis", "aac"},
                "Quality-based audio encoding is unsupported by this encoder.",
            )
            require(
                o.audio_rate_control not in {"vbr", "cbr"} or audio_encoder == "libopus",
                "Explicit VBR/CBR switching is only provided for Opus; use bitrate or quality for this encoder.",
            )
            require(0 <= o.audio_quality <= 9, "Audio quality must be between 0 and 9.")
    if o.subtitles != "remove" and source.subtitles:
        text_codecs = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
        if o.subtitles == "convert":
            require(
                o.format in {"mp4", "m4v", "mov", "mkv", "webm"},
                "Subtitle conversion is unsupported for this container.",
            )
            require(
                all(s.get("codec_name") in text_codecs for s in source.subtitles),
                "Image-based subtitles cannot be converted to text. Use MKV with copy, or remove subtitles.",
            )
            subtitle_encoder = (
                "mov_text" if o.format in {"mp4", "mov", "m4v"} else "webvtt" if o.format == "webm" else "srt"
            )
            require(subtitle_encoder in caps.encoders, "The required subtitle encoder is not installed.")
        else:
            allowed = (
                text_codecs | {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}
                if o.format == "mkv"
                else (
                    {"mov_text"}
                    if o.format in {"mp4", "mov", "m4v"}
                    else {"webvtt"}
                    if o.format == "webm"
                    else set()
                )
            )
            require(
                all(s.get("codec_name") in allowed for s in source.subtitles),
                "These subtitles cannot be copied to the output. Convert text subtitles, choose MKV, or remove them.",
            )
    require(not o.attachments or o.format == "mkv", "Attachments can only be preserved in MKV output.")
    require(o.cover in {"remove", "preserve", "replace"}, "Invalid cover artwork handling.")
    if o.kind == "audio" and o.cover != "remove":
        require(o.format in {"mp3", "m4a", "flac"}, "Artwork is supported for MP3, M4A and FLAC output.")
        if o.cover == "replace":
            require(Path(o.cover_path).expanduser().is_file(), "Select an existing cover image.")
            require("mjpeg" in caps.encoders, "Cover replacement requires the JPEG encoder.")
        else:
            artwork = [s for s in source.streams if s.get("disposition", {}).get("attached_pic")]
            require(
                all(s.get("codec_name") in {"mjpeg", "png"} for s in artwork),
                "This cover image codec cannot be copied into the selected audio format. Replace or remove it.",
            )
    require(
        all(
            k in {"title", "artist", "album", "track", "genre", "date", "comment"}
            and isinstance(v, str)
            and len(v) < 4096
            and "\0" not in v
            for k, v in o.tags.items()
        ),
        "Invalid metadata fields.",
    )
    expert_arguments(o.expert)
    needed = set()
    for enabled, filter_name in (
        (o.resize != "original", "scale"),
        (o.deinterlace, "yadif"),
        (o.denoise, "hqdn3d"),
        (o.sharpen, "unsharp"),
        (o.normalize, "loudnorm"),
        (o.alpha == "background" and o.kind == "image", "overlay"),
    ):
        if enabled:
            needed.add(filter_name)
    require(
        needed <= caps.filters,
        "A selected filter is unavailable in this FFmpeg installation: " + ", ".join(needed - caps.filters),
    )
    if filesystem:
        require(
            source.path.is_file() and os.access(source.path, os.R_OK),
            "The source no longer exists or is not readable.",
        )
        require(not output.is_symlink(), "Output is a symbolic link. Choose a new filename.")
        require(not output.exists() or output.is_file(), "The output path is not a regular file.")
        require(
            replace or not output.exists(),
            "The output already exists. Rename it or explicitly choose Replace.",
        )
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            require(os.access(output.parent, os.W_OK), "The output folder is not writable.")
            free = shutil.disk_usage(output.parent).free
            require(
                free >= 1024 * 1024, "The output disk has less than 1 MB free. Free up space before starting."
            )
            if o.target_mb:
                require(
                    free > o.target_mb * 1_000_000,
                    "The output disk does not have enough free space for the target size.",
                )
        except OSError as exc:
            raise MediaError("The output folder is inaccessible.", str(exc)) from exc
