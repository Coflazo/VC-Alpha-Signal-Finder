"""Background jobs for the app.

Collection and scoring take minutes, so the UI cannot block on them. Jobs run in a
thread, append to a bounded log, and report progress the page polls for.

Deliberately a thread and a dict rather than a task queue. One user, one machine,
one job at a time is the actual requirement, and Celery plus Redis to run a scraper
on a laptop would be infrastructure for its own sake.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MAX_LINES = 400


@dataclass
class Job:
    name: str
    argv: list[str]
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    returncode: int | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LINES))

    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "running": self.running,
            "returncode": self.returncode,
            "elapsed": round(self.elapsed, 1),
            "lines": list(self.lines),
        }


class JobRunner:
    """One job at a time. A second request while one runs is refused, not queued.

    Refused rather than queued because the jobs all write to the same SQLite file,
    and because a user who clicks twice means 'did that work?' rather than 'do it
    twice'.
    """

    def __init__(self) -> None:
        self._current: Job | None = None
        self._lock = threading.Lock()

    @property
    def current(self) -> Job | None:
        return self._current

    def start(self, name: str, argv: list[str]) -> Job:
        with self._lock:
            if self._current and self._current.running:
                raise RuntimeError(f"{self._current.name} is still running")
            job = Job(name=name, argv=argv)
            self._current = job

        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        job.lines.append(f"$ {' '.join(job.argv)}")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", *job.argv],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                # httpx logs every request at INFO; useful in a terminal, noise here.
                if line.startswith("HTTP Request:"):
                    continue
                job.lines.append(line)
            job.returncode = proc.wait()
        except Exception as e:  # pragma: no cover - defensive
            job.lines.append(f"failed to start: {e}")
            job.returncode = -1
            log.exception("job %s crashed", job.name)
        finally:
            job.finished_at = time.time()
            job.lines.append(
                f"— finished in {job.elapsed:.0f}s (exit {job.returncode})"
            )


runner = JobRunner()
