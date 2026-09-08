from __future__ import annotations

import hashlib
import os
import shutil
import threading
from dataclasses import replace

import pytest

from media_studio.core.commands import build_plan
from media_studio.core.execution import Executor
from media_studio.core.probe import probe
from media_studio.core.process import capture
from media_studio.core.validation import expert_arguments, suggested_output, unique_output, validate
from media_studio.models import Job, MediaError
from media_studio.presets import recommended


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration
@pytest.mark.parametrize("kind,fmt", [("video", "mkv"), ("image", "jpg"), ("audio", "flac")])
@pytest.mark.parametrize("operation", ["convert", "compress"])
def test_six_workflows(caps, media, tmp_path, kind, fmt, operation):
    source = media[kind]
    before = digest(source.path)
    options = recommended(caps, kind, operation, fmt)
    output = tmp_path / f"résultat with spaces.{fmt}"
    job = Job(source, output, options)
    progress = []
    Executor(caps).run(job, threading.Event(), progress.append)
    assert job.status == "Completed", job.log
    assert output.exists() and job.output_size == output.stat().st_size > 0
    assert probe(output, caps.ffprobe).kind == kind
    assert digest(source.path) == before
    assert progress[-1].percent == 100
    assert not list(tmp_path.glob(".media-studio-*"))


@pytest.mark.integration
def test_image_content_is_detected_without_extension(caps, media, tmp_path):
    path = tmp_path / "actually-an-image.mp3"
    shutil.copyfile(media["image"].path, path)
    assert probe(path, caps.ffprobe).kind == "image"


@pytest.mark.integration
def test_dynamic_capabilities(caps):
    assert {"scale", "loudnorm", "overlay"} <= caps.filters
    for kind in ("image", "video", "audio"):
        for fmt in caps.formats(kind):
            assert fmt.muxer in caps.muxers
            assert caps.choices(fmt)
            assert all(enc.name in caps.encoders for enc in caps.choices(fmt))
    assert "rgb24" in caps.encoders["png"].pixels


@pytest.mark.integration
def test_lossless_png_preserves_decoded_pixels(caps, media, tmp_path):
    output = tmp_path / "optimized.png"
    o = recommended(caps, "image", "compress", "png")
    job = Executor(caps).run(Job(media["image"], output, o), threading.Event())
    assert job.status == "Completed", job.log

    def pixels(path):
        return capture(
            [caps.ffmpeg, "-v", "error", "-i", str(path), "-pix_fmt", "rgb24", "-f", "framemd5", "-"]
        ).splitlines()[-1]

    assert pixels(output) == pixels(media["image"].path)


@pytest.mark.integration
def test_lossless_flac_preserves_audio_samples(caps, media, tmp_path):
    output = tmp_path / "lossless.flac"
    job = Executor(caps).run(
        Job(media["audio"], output, recommended(caps, "audio", "compress", "flac")), threading.Event()
    )
    assert job.status == "Completed", job.log

    def samples(path):
        return capture(
            [caps.ffmpeg, "-v", "error", "-i", str(path), "-c:a", "pcm_s16le", "-f", "hash", "-"]
        ).strip()

    assert samples(output) == samples(media["audio"].path)


@pytest.mark.integration
def test_two_pass_target_size_and_resize(caps, media, tmp_path):
    output = tmp_path / "small.mp4"
    o = replace(
        recommended(caps, "video", "compress", "mp4"),
        rate_control="quality",
        two_pass=True,
        target_mb=0.13,
        resize="fit",
        width=100,
        height=100,
        fps="12",
        audio_bitrate=64,
    )
    job = Executor(caps).run(Job(media["video"], output, o), threading.Event())
    assert job.status == "Completed", job.log
    result = probe(output, caps.ffprobe)
    assert result.video["width"] <= 100 and result.video["height"] <= 100
    assert result.video["avg_frame_rate"] == "12/1"
    assert "-pass 1" in job.log and "-pass 2" in job.log
    assert not list(tmp_path.glob("*pass*"))


@pytest.mark.integration
def test_stream_copy_and_incompatible_copy(caps, media, tmp_path):
    o = replace(
        recommended(caps, "video", "convert", "mkv"), encoder="copy", pixel_format="", audio_mode="copy"
    )
    output = tmp_path / "remuxed.mkv"
    job = Executor(caps).run(Job(media["video"], output, o), threading.Event())
    assert job.status == "Completed", job.log
    assert probe(output, caps.ffprobe).video["codec_name"] == "h264"
    with pytest.raises(MediaError, match="cannot be copied"):
        validate(media["video"], tmp_path / "bad.webm", replace(o, format="webm"), caps)
    with pytest.raises(MediaError, match="Stream copy cannot"):
        validate(media["video"], output, replace(o, resize="fit"), caps)


@pytest.mark.integration
def test_source_aliases_and_existing_outputs_protected(caps, media, tmp_path):
    source = media["image"]
    o = recommended(caps, "image", "convert", "png")
    for alias_kind in ("hardlink", "symlink"):
        alias = tmp_path / f"{alias_kind}.png"
        (os.link if alias_kind == "hardlink" else os.symlink)(source.path, alias)
        with pytest.raises(MediaError, match="source file"):
            validate(source, alias, o, caps, replace=True)
    output = tmp_path / "existing.png"
    output.write_bytes(b"keep me")
    job = Executor(caps).run(Job(source, output, o), threading.Event())
    assert job.status == "Failed" and output.read_bytes() == b"keep me"
    assert suggested_output(source, source.path.parent, o) != source.path
    assert unique_output(output).name == "existing_2.png"


@pytest.mark.integration
def test_failed_replace_preserves_previous_output(caps, media, tmp_path):
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"existing output")
    o = replace(recommended(caps, "video", "convert", "mp4"), expert="-tune definitely_invalid")
    job = Executor(caps).run(Job(media["video"], output, o, replace=True), threading.Event())
    assert job.status == "Failed"
    assert output.read_bytes() == b"existing output"
    assert not list(tmp_path.glob(".media-studio-*"))


@pytest.mark.integration
def test_cancellation_removes_partial_output(caps, media, tmp_path):
    output = tmp_path / "cancelled.mp4"
    cancel = threading.Event()
    o = recommended(caps, "video", "convert", "mp4")

    def stop(_):
        cancel.set()

    job = Executor(caps).run(Job(media["video"], output, o), cancel, stop)
    assert job.status == "Cancelled"
    assert not output.exists()
    assert not list(tmp_path.glob(".media-studio-*"))


@pytest.mark.integration
def test_output_collision_during_processing_does_not_clobber(caps, media, tmp_path):
    output = tmp_path / "late.png"

    def race(_):
        output.write_bytes(b"created elsewhere")

    job = Executor(caps).run(
        Job(media["image"], output, recommended(caps, "image", "convert", "png")), threading.Event(), race
    )
    assert job.status == "Failed"
    assert output.read_bytes() == b"created elsewhere"


@pytest.mark.parametrize(
    "arguments",
    [
        "-i other.mp4",
        "-y",
        "-f mp4 other.mp4",
        "-filter_complex movie=/etc/passwd",
        "-passlogfile /tmp/x",
        "-aq-strength 0.8 output.mp4",
        "-tune 'unclosed",
    ],
)
def test_expert_arguments_cannot_add_io(arguments):
    with pytest.raises(MediaError):
        expert_arguments(arguments)


@pytest.mark.integration
@pytest.mark.parametrize(
    "changes",
    [
        dict(fps="nan"),
        dict(fps="1/0"),
        dict(width=0),
        dict(sample_rate=2),
        dict(target_mb=float("nan")),
        dict(pixel_format="rgba"),
        dict(audio_encoder="libopus"),
        dict(two_pass=True),
        dict(profile="baseline", b_frames=3),
    ],
)
def test_invalid_settings_fail_before_execution(caps, media, tmp_path, changes):
    o = replace(recommended(caps, "video", "convert", "mp4"), **changes)
    with pytest.raises(MediaError):
        build_plan(media["video"], tmp_path / "out.mp4", o, caps)


@pytest.mark.integration
def test_quoted_paths_are_arguments_not_shell_commands(caps, media, tmp_path):
    path = tmp_path / "a $(touch bad) `literal` ;.png"
    o = recommended(caps, "image", "convert", "png")
    plan = build_plan(media["image"], path, o, caps)
    assert plan.commands[0][-1] == str(path)
    job = Executor(caps).run(Job(media["image"], path, o), threading.Event())
    assert job.status == "Completed", job.log
    assert not (tmp_path / "bad").exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind,fmt",
    [("image", v) for v in ["png", "jpg", "webp", "avif", "tiff", "bmp", "gif", "jp2"]]
    + [("video", v) for v in ["mp4", "mkv", "mov", "webm", "avi", "mpg", "ts", "m4v"]]
    + [("audio", v) for v in ["mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "ac3", "wma"]],
)
def test_supported_format_defaults_execute(caps, media, tmp_path, kind, fmt):
    if not any(f.key == fmt for f in caps.formats(kind)):
        pytest.skip(f"{fmt} encoder unavailable in installed FFmpeg")
    o = recommended(caps, kind, "convert", fmt)
    output = tmp_path / f"output.{fmt}"
    job = Executor(caps).run(Job(media[kind], output, o), threading.Event())
    assert job.status == "Completed", job.log
    result = probe(output, caps.ffprobe)
    assert result.kind == kind


@pytest.mark.integration
def test_subtitle_conversion_and_metadata_removal(caps, media, tmp_path):
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello media\n")
    source_path = tmp_path / "subtitled.mkv"
    capture(
        [
            caps.ffmpeg,
            "-v",
            "error",
            "-i",
            str(media["video"].path),
            "-i",
            str(subtitle),
            "-map",
            "0",
            "-map",
            "1",
            "-c",
            "copy",
            "-metadata",
            "title=Private title",
            str(source_path),
        ]
    )
    source = probe(source_path, caps.ffprobe)
    o = replace(recommended(caps, "video", "convert", "mp4"), subtitles="convert", metadata="remove")
    output = tmp_path / "subtitles.mp4"
    job = Executor(caps).run(Job(source, output, o), threading.Event())
    assert job.status == "Completed", job.log
    result = probe(output, caps.ffprobe)
    assert result.subtitles[0]["codec_name"] == "mov_text"
    assert "title" not in result.tags


@pytest.mark.integration
def test_audio_metadata_artwork_and_normalization(caps, media, tmp_path):
    output = tmp_path / "tagged.mp3"
    o = replace(
        recommended(caps, "audio", "convert", "mp3"),
        tags={"title": "My tune", "artist": "Test artist"},
        cover="replace",
        cover_path=str(media["image"].path),
        normalize=True,
        sample_rate=48000,
    )
    job = Executor(caps).run(Job(media["audio"], output, o), threading.Event())
    assert job.status == "Completed", job.log
    result = probe(output, caps.ffprobe)
    assert result.kind == "audio"
    assert result.tags["title"] == "My tune"
    assert result.audio["sample_rate"] == "48000"
    assert any(s.get("disposition", {}).get("attached_pic") for s in result.streams)
