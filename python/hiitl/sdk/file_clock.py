"""Read the file timestamp clock, not a wall-clock estimate of its granularity."""
import os
import tempfile


def read_file_clock(source_stat):
    """A temporary inode on the same filesystem timestamps the read's start.

    Linux inode times may be coarse even when time.time_ns() is precise. The
    marker uses the same clock and filesystem as the policy. If that cannot be
    observed (including a read-only or distinct filesystem), content remains the
    confirmation; there is no new permission requirement on the policy source.
    Windows ctime is creation time, not change time, so it cannot settle this.
    """
    if os.name == 'nt':
        return None
    try:
        with tempfile.TemporaryFile() as clock:
            stamp = os.fstat(clock.fileno())
            return stamp.st_ctime_ns if stamp.st_dev == source_stat.st_dev else None
    except OSError:
        return None
