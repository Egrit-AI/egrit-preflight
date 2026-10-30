"""The only place a subprocess is started. No shell is ever used, so no argument is interpreted by one.

Output is captured through reader threads that keep at most MAX_CAPTURE bytes of each stream and discard the rest, so a
process that floods its output (a hostile container, for example) cannot exhaust this process's memory.
"""

import subprocess
import threading
import time
from dataclasses import dataclass

MAX_CAPTURE = 1024 * 1024


@dataclass
class CmdResult:
    argv: list
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_s: float = 0.0
    not_found: bool = False
    truncated: bool = False

    def record(self, limit=2000, output=True):
        """What a report keeps of a command: argv, outcome and bounded output.

        output=False keeps no stdout or stderr. Use it for commands whose output describes the machine
        (for example 'docker info' lists the hostname and proxy settings), so a shared report cannot leak it.
        """
        rec = {"argv": list(self.argv), "returncode": self.returncode, "timed_out": self.timed_out}
        if output:
            rec["stdout"] = self.stdout[-limit:]
            rec["stderr"] = self.stderr[-limit:]
            if self.truncated:
                rec["output_truncated"] = True
        else:
            rec["output_omitted"] = True
        return rec


class _Drain(threading.Thread):
    """Reads a pipe to EOF, keeping only the first `limit` bytes."""

    def __init__(self, stream, limit):
        super().__init__(daemon=True)
        self.stream, self.limit = stream, limit
        self.chunks, self.kept, self.truncated = [], 0, False

    def run(self):
        try:
            while True:
                chunk = self.stream.read1(65536)
                if not chunk:
                    return
                room = self.limit - self.kept
                if room > 0:
                    self.chunks.append(chunk[:room])
                    self.kept += min(len(chunk), room)
                if len(chunk) > room:
                    self.truncated = True
        except (OSError, ValueError):
            return

    def text(self):
        return b"".join(self.chunks).decode(errors="replace")


def run(argv, timeout=30.0, limit=MAX_CAPTURE):
    start = time.monotonic()
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return CmdResult(argv, 127, stderr=f"{argv[0]}: command not found", not_found=True)
    except OSError as exc:
        return CmdResult(argv, 126, stderr=f"{argv[0]}: cannot execute ({exc.strerror or type(exc).__name__})")
    drains = [_Drain(p.stdout, limit), _Drain(p.stderr, limit)]
    for d in drains:
        d.start()
    timed_out = False
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        p.kill()
        p.wait()
    except BaseException:
        p.kill()
        p.wait()
        raise
    finally:
        for d in drains:
            d.join(5)
    return CmdResult(argv, 124 if timed_out else p.returncode, drains[0].text(), drains[1].text(),
                     timed_out=timed_out, duration_s=time.monotonic() - start, truncated=any(d.truncated for d in drains))
