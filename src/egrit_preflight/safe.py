"""Small helpers for handling untrusted input: JSON from a registry or an image, files named on the command line,
and text that came from a container before it reaches a terminal."""

import json
import os
import re
import stat

MAX_FILE_BYTES = 1024 * 1024
# Control characters other than tab and newline, including ESC (so no terminal escape sequence survives).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(text):
    """Make text safe to print: control characters become '?'."""
    return _CONTROL.sub("?", str(text))


def loads(text):
    """json.loads that returns None instead of raising on malformed or absurdly nested input."""
    try:
        return json.loads(text)
    except (ValueError, TypeError, RecursionError):
        return None


def as_str(value, limit=200):
    """A short, printable string, or None if the value is not a string."""
    return clean(value)[:limit] if isinstance(value, str) else None


def read_small_file(path, limit=MAX_FILE_BYTES):
    """Bytes of a regular file of at most `limit` bytes. Refuses FIFOs, devices and directories without blocking."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        data = os.read(fd, limit + 1)
        while len(data) <= limit:
            more = os.read(fd, limit + 1 - len(data))
            if not more:
                break
            data += more
    finally:
        os.close(fd)
    if len(data) > limit:
        raise OSError(f"file is larger than {limit} bytes")
    return data


def output_path_problem(path):
    """Why a report cannot be written to `path`, or None. Checked before any work is done."""
    if os.path.islink(path):
        return f"{path} is a symbolic link; refusing to write through it"
    if os.path.exists(path) and not os.path.isfile(path):
        return f"{path} exists and is not a regular file"
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        return f"directory {parent} does not exist"
    if not os.access(parent, os.W_OK | os.X_OK):
        return f"directory {parent} is not writable"
    return None


def write_private(path, text):
    """Write text to `path` without following a symbolic link; a new file is created with mode 0600."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
