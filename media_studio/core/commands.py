from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, replace
from pathlib import Path

from media_studio.core.capabilities import Capabilities
from media_studio.core.validation import expert_arguments, validate, video_bitrate
from media_studio.models import MediaInfo, Options
from media_studio.presets import LOSSLESS, QUALITY_VIDEO


@dataclass(frozen=True)
class Plan:
    commands: tuple[list[str], ...]
    output: Path

    @property
    def preview(self) -> str:
        return "\n\n".join(shlex.join(command) for command in self.commands)


def video_filters(o: Options) -> list[str]:
    result = []
    if o.deinterlace:
        result.append("yadif")
    if o.crop:
        result.append("crop=" + o.crop)
    if o.rotate == "clockwise":
        result.append("transpose=clock")
    elif o.rotate == "counterclockwise":
        result.append("transpose=cclock")
    elif o.rotate == "180":
        result.extend(["hflip", "vflip"])
    if o.flip != "none":
        result.append("hflip" if o.flip == "horizontal" else "vflip")
    if o.resize == "percent":
        divisor = 2 if o.kind == "video" else 1
        result.append(
            f"scale=trunc(iw*{o.scale_percent}/100/{divisor})*{divisor}:"
            f"trunc(ih*{o.scale_percent}/100/{divisor})*{divisor}:flags={o.scaler}"
        )
    elif o.resize in {"custom", "fit"}:
        if o.keep_aspect or o.resize == "fit":
            even = ":force_divisible_by=2" if o.kind == "video" else ""
            result.append(
                f"scale={o.width}:{o.height}:force_original_aspect_ratio=decrease{even}:flags={o.scaler}"
            )
        else:
            result.append(f"scale={o.width}:{o.height}:flags={o.scaler}")
    if o.denoise:
        result.append("hqdn3d")
    if o.sharpen:
        result.append("unsharp=5:5:0.7:5:5:0")
    if o.grayscale:
        result.append("format=gray")
    if o.kind == "video" and o.encoder not in {"copy", "ffv1", "prores_ks"}:
        result.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
    if o.kind == "image" and o.alpha == "remove":
        result.append("format=rgb24")
    return result


def video_encoding(o: Options, source: MediaInfo) -> list[str]:
    encoder = o.encoder
    result = ["-c:v", encoder]
    if encoder == "copy":
        return result
    if o.kind == "image":
        if encoder == "png":
            result += ["-compression_level", str(min(9, o.compression_level))]
        elif encoder in {"libwebp", "libwebp_anim"}:
            result += [
                "-lossless",
                str(int(o.lossless)),
                "-quality",
                str(o.quality),
                "-compression_level",
                str(min(6, o.compression_level)),
            ]
        elif encoder == "mjpeg":
            result += ["-q:v", str(max(2, min(31, round(31 - o.quality * 0.29))))]
        elif encoder in {"libaom-av1", "libsvtav1"}:
            result += ["-crf", str(round((100 - o.quality) * 0.63)), "-b:v", "0"]
            result += ["-cpu-used" if encoder == "libaom-av1" else "-preset", o.preset]
        elif encoder == "tiff":
            result += ["-compression_algo", "deflate"]
        elif encoder in {"jpeg2000", "libopenjpeg"}:
            # Native JPEG 2000 uses a reversible transform only when explicitly selected.
            result += ["-pred", "1"] if encoder == "jpeg2000" else []
        return result
    if encoder in {"libx264", "libx265"}:
        result += ["-preset", o.preset]
    elif encoder == "libsvtav1":
        result += ["-preset", o.preset]
    elif encoder in {"libvpx-vp9", "libaom-av1"}:
        result += ["-cpu-used", o.preset]
    if o.lossless and encoder == "libx264":
        result += ["-qp", "0"]
    elif o.lossless and encoder == "libx265":
        result += ["-x265-params", "lossless=1"]
    elif encoder not in LOSSLESS and encoder != "prores_ks":
        if o.rate_control == "quality" and not o.target_mb and encoder in QUALITY_VIDEO:
            result += ["-crf", str(o.quality)]
            if encoder in {"libvpx-vp9", "libaom-av1"}:
                result += ["-b:v", "0"]
        else:
            bitrate = video_bitrate(source, o)
            result += ["-b:v", f"{bitrate}k"]
            if o.rate_control == "cbr":
                result += [
                    "-minrate",
                    f"{bitrate}k",
                    "-maxrate",
                    f"{bitrate}k",
                    "-bufsize",
                    f"{o.buffer_size or bitrate * 2}k",
                ]
            elif o.max_bitrate:
                result += [
                    "-maxrate",
                    f"{o.max_bitrate}k",
                    "-bufsize",
                    f"{o.buffer_size or o.max_bitrate * 2}k",
                ]
            elif o.buffer_size:
                result += ["-bufsize", f"{o.buffer_size}k"]
    if o.profile:
        result += ["-profile:v", o.profile]
    if o.level:
        result += ["-level:v", o.level]
    if o.gop:
        result += ["-g", str(o.gop)]
    if o.b_frames >= 0:
        result += ["-bf", str(o.b_frames)]
    return result


def audio_encoding(o: Options, encoder: str) -> list[str]:
    result = ["-c:a", encoder]
    if encoder == "copy":
        return result
    if encoder == "flac":
        result += ["-compression_level", str(o.compression_level)]
    elif encoder not in LOSSLESS:
        if o.audio_rate_control == "quality" and encoder in {"libmp3lame", "libvorbis", "aac"}:
            result += ["-q:a", str(o.audio_quality)]
        else:
            result += ["-b:a", f"{o.audio_bitrate}k"]
        if encoder == "libopus":
            result += ["-vbr", "off" if o.audio_rate_control == "cbr" else "on"]
    if o.sample_rate:
        result += ["-ar", str(o.sample_rate)]
    if o.channels:
        result += ["-ac", str(o.channels)]
    if o.sample_format:
        result += ["-sample_fmt", o.sample_format]
    filters = []
    if o.volume_db:
        filters.append(f"volume={o.volume_db}dB")
    if o.normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if filters:
        result += ["-af", ",".join(filters)]
    return result


def command(
    source: MediaInfo,
    output: Path,
    o: Options,
    caps: Capabilities,
    pass_number: int = 0,
    passlog: Path | None = None,
) -> list[str]:
    fmt = caps.format(o.kind, o.format)
    args = [
        caps.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        "-protocol_whitelist",
        "file,pipe,crypto,data",
        "-i",
        str(source.path),
    ]
    if o.kind == "audio" and o.cover == "replace" and pass_number != 1:
        args += [
            "-protocol_whitelist",
            "file,pipe,crypto,data",
            "-i",
            str(Path(o.cover_path).expanduser().resolve()),
        ]
    if o.kind in {"video", "image"}:
        filters = video_filters(o)
        if o.kind == "image" and o.alpha == "background":
            graph = (
                f"[0:V:0]split[foreground][background];[background]drawbox=color=0x{o.background[1:]}:"
                "t=fill:replace=1[base];[base][foreground]overlay=shortest=1:format=auto,format=rgb24"
            )
            if filters:
                graph += "," + ",".join(filters)
            args += ["-filter_complex", graph + "[image]", "-map", "[image]"]
        else:
            args += ["-map", "0:V:0"]
            if filters:
                args += ["-vf", ",".join(filters)]
        args += video_encoding(o, source)
        if o.pixel_format and o.encoder != "copy":
            args += ["-pix_fmt", o.pixel_format]
        if o.fps and o.encoder != "copy":
            args += ["-r", o.fps]
        for value, flag in (
            (o.color_space, "-colorspace"),
            (o.color_range, "-color_range"),
            (o.color_primaries, "-color_primaries"),
            (o.color_transfer, "-color_trc"),
        ):
            if value and o.encoder != "copy":
                args += [flag, value]
        if o.kind == "image":
            args += ["-frames:v", "1", "-an"]
            if fmt.muxer == "image2":
                args += ["-update", "1"]
    if o.kind == "audio":
        args += ["-map", "0:a:0", *audio_encoding(o, o.encoder)]
        if o.cover == "preserve":
            args += ["-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic"]
        elif o.cover == "replace":
            args += ["-map", "1:v:0", "-c:v", "mjpeg", "-frames:v", "1", "-disposition:v", "attached_pic"]
        else:
            args += ["-vn"]
    elif o.kind == "video" and o.audio_mode != "remove" and source.audio and pass_number != 1:
        args += ["-map", "0:a:0?", *audio_encoding(o, "copy" if o.audio_mode == "copy" else o.audio_encoder)]
    else:
        args += ["-an"]
    if o.kind == "video" and o.subtitles != "remove" and pass_number != 1:
        subtitle_encoder = (
            "copy"
            if o.subtitles == "copy"
            else (
                "mov_text" if o.format in {"mp4", "mov", "m4v"} else "webvtt" if o.format == "webm" else "srt"
            )
        )
        args += ["-map", "0:s?", "-c:s", subtitle_encoder]
    else:
        args += ["-sn"]
    if o.attachments and o.format == "mkv" and pass_number != 1:
        args += ["-map", "0:t?", "-c:t", "copy"]
    args += [
        "-map_metadata",
        "0" if o.metadata == "preserve" else "-1",
        "-map_chapters",
        "0" if o.chapters and o.kind != "image" else "-1",
    ]
    for key, val in o.tags.items():
        args += ["-metadata", f"{key}={val}"]
    if o.threads:
        args += ["-threads", str(o.threads)]
    if o.format in {"mp4", "m4v", "mov", "m4a"} and pass_number != 1:
        args += ["-movflags", "+faststart"]
        if o.encoder in {"libx265", "hevc_videotoolbox"}:
            args += ["-tag:v", "hvc1"]
    args += expert_arguments(o.expert)
    if pass_number:
        args += ["-pass", str(pass_number), "-passlogfile", str(passlog)]
    args += ["-f", "null" if pass_number == 1 else fmt.muxer, os.devnull if pass_number == 1 else str(output)]
    return args


def build_plan(
    source: MediaInfo, output: Path, options: Options, caps: Capabilities, passlog: Path | None = None
) -> Plan:
    validate(source, output, options, caps, filesystem=False)
    if options.two_pass:
        passlog = passlog or output.parent / ".media-studio-passlog"
        first = replace(options, audio_mode="remove", subtitles="remove", attachments=False, chapters=False)
        # Keep the calculated second-pass bitrate in pass one when target size includes audio.
        first = replace(
            first,
            target_mb=0,
            bitrate=video_bitrate(source, options),
            rate_control="bitrate" if options.rate_control == "quality" else options.rate_control,
        )
        return Plan(
            (
                command(source, output, first, caps, 1, passlog),
                command(source, output, options, caps, 2, passlog),
            ),
            output,
        )
    return Plan((command(source, output, options, caps),), output)
