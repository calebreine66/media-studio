from __future__ import annotations

import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from media_studio.core.capabilities import Capabilities
from media_studio.core.commands import build_plan
from media_studio.core.process import process_kwargs
from media_studio.core.validation import same_file, validate
from media_studio.models import Job, MediaError, Progress


class Cancelled(Exception):
    pass


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except PermissionError:
                # Some desktop sandboxes permit signalling a child, but not its process group.
                process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except PermissionError:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()
    except ProcessLookupError:
        pass


def explain_error(details: str) -> str:
    lower = details.lower()
    if "no space left" in lower:
        return "The output disk is full. Free up space and try again."
    if "permission denied" in lower:
        return "Permission denied. Choose a writable output folder."
    if "videotoolbox" in lower or "device" in lower and "failed" in lower:
        return "The hardware encoder could not run. Choose a software encoder and try again."
    if "not divisible by" in lower or "invalid size" in lower:
        return "The encoder cannot use these dimensions. Choose an even width and height."
    return "FFmpeg could not process this file with the selected settings. Review the detailed log or restore recommended settings."


class Executor:
    """Run a validated job. Originals and existing outputs survive failure or cancellation."""

    def __init__(self, caps: Capabilities):
        self.caps = caps

    def run(
        self, job: Job, cancel: threading.Event, on_progress: Callable[[Progress], None] = lambda _: None
    ) -> Job:
        started = time.monotonic()
        temporary: Path | None = None
        log = deque(maxlen=600)
        try:
            if cancel.is_set():
                raise Cancelled()
            validate(job.source, job.output, job.options, self.caps, replace=job.replace)
            fd, name = tempfile.mkstemp(
                prefix=".media-studio-", suffix=job.output.suffix, dir=job.output.parent
            )
            os.close(fd)
            temporary = Path(name)
            with tempfile.TemporaryDirectory(prefix="media-studio-pass-") as pass_dir:
                plan = build_plan(job.source, temporary, job.options, self.caps, Path(pass_dir) / "pass")
                log.append(self.caps.version + "\n" + plan.preview)
                job.status = "Compressing" if job.options.operation == "compress" else "Converting"
                for index, args in enumerate(plan.commands):
                    self._run_command(args, job, cancel, on_progress, started, index, len(plan.commands), log)
            if cancel.is_set():
                raise Cancelled()
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise MediaError("FFmpeg finished without producing a usable output file.")
            # Recheck source aliasing at commit time; replace must have been explicitly authorized.
            if same_file(job.source.path, job.output) or job.output.is_symlink():
                raise MediaError(
                    "The destination changed while processing. The source and destination were preserved."
                )
            if job.replace:
                os.replace(temporary, job.output)
            else:
                # Atomic no-clobber publication on the same filesystem, including late filename races.
                try:
                    os.link(temporary, job.output)
                except FileExistsError as exc:
                    raise MediaError(
                        "Another file appeared at the destination. It was preserved; retry with a new filename."
                    ) from exc
                temporary.unlink()
            job.output_size = job.output.stat().st_size
            job.status, job.progress = "Completed", 100
            on_progress(Progress(100, time.monotonic() - started, job.source.duration, "", 0, "Completed"))
        except Cancelled:
            job.status, job.error = (
                "Cancelled",
                "Processing was cancelled. The incomplete output was removed.",
            )
        except MediaError as exc:
            job.status, job.error = "Failed", str(exc)
            log.append(exc.details)
        except Exception as exc:
            job.status, job.error = "Failed", "The job could not finish. See the diagnostic details."
            log.append(f"{type(exc).__name__}: {exc}")
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    log.append(f"Could not remove temporary output {temporary}: {exc}")
            job.elapsed = time.monotonic() - started
            job.log = "\n".join(log)
        return job

    def _run_command(self, args, job, cancel, notify, started, index, total, log):
        if cancel.is_set():
            raise Cancelled()
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **process_kwargs(),
        )
        events: queue.Queue[str | None] = queue.Queue()

        def read_stdout():
            try:
                for line in process.stdout:
                    events.put(line.rstrip())
            finally:
                events.put(None)

        def read_stderr():
            for line in process.stderr:
                log.append(line.rstrip())

        readers = [
            threading.Thread(target=read_stdout, daemon=True),
            threading.Thread(target=read_stderr, daemon=True),
        ]
        for reader in readers:
            reader.start()
        values = {}
        try:
            while True:
                if cancel.is_set():
                    stop_process(process)
                    raise Cancelled()
                try:
                    line = events.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                key, _, value = line.partition("=")
                values[key] = value
                if key == "progress":
                    try:
                        timestamp = max(0, float(values.get("out_time_us", "0")) / 1_000_000)
                    except ValueError:
                        timestamp = 0
                    fraction = min(0.995, timestamp / job.source.duration) if job.source.duration > 0 else 0
                    percent = min(99.5, (index + fraction) / total * 100)
                    elapsed = time.monotonic() - started
                    remaining = elapsed * (100 - percent) / percent if percent > 1 else None
                    job.progress = max(job.progress, percent)
                    notify(
                        Progress(
                            job.progress,
                            elapsed,
                            timestamp,
                            values.get("speed", ""),
                            remaining,
                            f"Pass {index + 1} of {total}" if total > 1 else job.status,
                        )
                    )
            code = process.wait()
            for reader in readers:
                reader.join(timeout=2)
            log.append(f"Exit code: {code}")
            if cancel.is_set():
                raise Cancelled()
            if code:
                details = "\n".join(log)
                raise MediaError(explain_error(details), details)
        finally:
            stop_process(process)
            for reader in readers:
                reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()
