"""Disk + memory cache for sync engine.

The cache provides fast in-memory reads for the evaluator hot path
while persisting data to disk for warm-start across SDK restarts.

Key properties:
- Thread-safe: Lock for writes, lock-free reads via reference swap
- Atomic disk writes: Write .tmp then os.rename() (POSIX atomic)
- TTL tracking: Each channel has independent freshness checks
- Warm start: Load from disk on init with actual file age preservation
- Integrity: SHA-256 hash sidecar per file, written with it; a file whose sidecar is absent, unreadable or names
  another hash is discarded (sync_engine.md §4 "Integrity")
- Max-stale: Warning when cached data exceeds staleness threshold

Cache structure on disk:
    {cache_dir}/{org_id}/{environment}/
        policies.json        # Full policy data
        policies.json.sha256 # Content hash for integrity verification
        policies.etag        # ETag for conditional requests
        routes.json          # Route configurations
        routes.json.sha256   # Content hash
        routes.etag          # ETag for conditional requests
        kill_switches.json   # The last kill-switch tick, as received
        kill_switches.json.sha256  # Content hash
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from hiitl.core.evaluator import live_kill_switches
from hiitl.core.redaction import ORG_FIELDS
from hiitl.core.types import PolicySet

logger = logging.getLogger(__name__)


def cached_policy_set(cached: Optional[dict]) -> Optional[PolicySet]:
    """The version a policy pull's cached data holds for evaluation: its first active policy the model reads, a refused
    one skipped naming why (R-0872), or None when it holds none. The cache reads it once, where the pull is received or
    the disk cache loaded, and holds it: evaluate() reads the held reading, and the kill-switch tick compares the version
    it names with it (sync_engine.md 2.4 and Numeric domain; HTL-29 row 131; HTL-43 gap 295): one reading of the cached
    version."""
    if not isinstance(cached, dict):
        return None
    for p in cached.get("policies") or []:
        if p.get("active", True):
            try:
                return PolicySet(**p.get("content", {}))
            except Exception as e:
                logger.warning("Failed to parse cached policy '%s': %s. Trying next source.", p.get("name", "?"), e)
    return None


def version_difference(tick: Optional[dict], cached: Optional[PolicySet]) -> Optional[tuple[tuple, tuple]]:
    """The version the tick names and the cached version evaluate reads, each as (version, its live switches), when
    the two differ; None when they agree. "A version string names one policy content per organisation and environment"
    (policy_format.md "A version identifies what evaluates"), so the two are compared by it, never by the switches'
    names: the tick is the change signal and the version decides (sync_engine.md 2.4; HTL-29 row 131, condition 2).
    The engine pulls on a difference, and the cache holds the tick's part while it stands (row 240). A tick naming no
    version differs from a cached one: an unread version is never the same one."""
    held = (tick or {}).get("policy_set")
    named = held.get("version") if isinstance(held, dict) else None
    version = cached.version if cached is not None else None
    if named == version:
        return None
    switches = sorted(str(s.get("rule_name")) for s in (tick or {}).get("kill_switches") or [])
    return (named, switches), (version, live_kill_switches(cached) if cached is not None else [])


def _tick_part(tick: dict) -> Optional[PolicySet]:
    """A tick's `policy_set` read as a set, or None when it carries none or the model refuses it (logged): the set
    the tick names, as far as its switches go (sync_engine.md 2.4; HTL-29 row 240)."""
    held = tick.get("policy_set")
    if held is None:
        return None
    try:
        return PolicySet(**held)
    except Exception as e:
        logger.error("The kill-switch tick's policy_set cannot be read, so its switches bind only once the version's "
                     "pull lands: %s", e)
        return None


from hiitl.sdk.admission import admit_configuration
from hiitl.core.numeric_domain import validate_numeric_domain
from hiitl.sdk.admission import admit_sync, sync_channel
from hiitl.sdk.sync_numbers import sync_numeric_shape


class SyncCache:
    """Disk-backed memory cache for synced data.

    In-memory copies serve the evaluator's hot path with zero disk I/O.
    Disk copies provide warm-start capability across restarts.

    Args:
        cache_dir: Base cache directory (default: ~/.hiitl/cache/)
        org_id: Organization ID for cache scoping
        environment: Environment for cache scoping (dev/stage/prod)
        max_stale_age: Max seconds before CACHE_STALE warning (default: 24h)
    """

    def __init__(
        self,
        cache_dir: str,
        org_id: str,
        environment: str,
        max_stale_age: float = 86400.0,
    ):
        admit_configuration(type(self).__init__, {"max_stale_age": max_stale_age})
        self._base_dir = Path(cache_dir).expanduser() / org_id / environment
        self._org_id = org_id
        self._environment = environment
        self._lock = threading.Lock()
        self._max_stale_age = max_stale_age
        self._dir_created = False

        # In-memory state — the evaluator reads these directly
        self._policies: Optional[dict] = None
        self._policies_etag: Optional[str] = None
        self._policies_updated_at: float = 0.0
        # The cached version evaluate reads, read through the model where the policies were received or loaded
        # (sync_engine.md Numeric domain; HTL-43 gap 295). Computed, never stored.
        self._policy_set: Optional[PolicySet] = None

        self._routes: Optional[list] = None
        self._routes_etag: Optional[str] = None
        self._routes_updated_at: float = 0.0

        self._kill_switches: Optional[dict] = None     # the last tick, as received
        self._kill_switches_updated_at: float = 0.0
        # The tick's part: the set the last tick names, held from a tick naming a version other than the cached one
        # until a pull lands after it (sync_engine.md 2.4; HTL-29 row 240, condition 2). Computed, never stored.
        self._tick_part: Optional[PolicySet] = None

        # Health tracking
        self._disk_diverged = False
        self._stale_warned: dict[str, bool] = {}

        # TICKET-116: distinguish "loaded from disk on warm start" from
        # "populated by a successful sync this process." A disk-loaded
        # cache may be stale; an in-process synced cache is fresh.
        # Consumers use cache_status() to surface this on each Decision.
        self._synced_this_process = False

    def load_from_disk(self) -> bool:
        """Load cached data from disk (warm start).

        Cleans up orphaned .tmp files from previous crashes, then loads
        cached data with actual file age preservation.

        Returns:
            True if any cached data was loaded, False if cache dir empty/missing.
        """
        self._cleanup_orphans()
        loaded_any = False

        policies = self._read_json("policies.json")
        if policies is not None:
            policy_set = cached_policy_set(policies)
            with self._lock:
                self._policies = policies
                self._policy_set = policy_set
                self._policies_updated_at = self._file_mtime("policies.json")
                self._policies_etag = self._read_text("policies.etag")
            loaded_any = True
            logger.info("Loaded cached policies from disk")

        routes = self._read_json("routes.json")
        if routes is not None:
            with self._lock:
                self._routes = routes
                self._routes_updated_at = self._file_mtime("routes.json")
                self._routes_etag = self._read_text("routes.etag")
            loaded_any = True
            logger.info("Loaded cached routes from disk")

        tick = self._read_json("kill_switches.json")
        if isinstance(tick, dict):
            # A tick read at start has had no pull after it, so its part stands until the first one lands (row 240)
            with self._lock:
                self._hold_tick(tick)
                self._kill_switches_updated_at = self._file_mtime("kill_switches.json")
            loaded_any = True
            logger.info("Loaded cached kill switches from disk")
        elif tick is not None:
            logger.info("The cached kill-switch file holds an earlier SDK's list, which decides nothing: not read. The "
                        "next tick replaces it.")

        if loaded_any:
            logger.info("Warm start: loaded cache from %s", self._base_dir)
        else:
            logger.info("Cold start: no cached data at %s", self._base_dir)

        return loaded_any

    # ── Policy cache ─────────────────────────────────────────────

    def get_policies(self) -> Optional[dict]:
        """Get cached policy data (lock-free read via reference)."""
        data = self._policies
        if data is not None:
            self._check_stale("policies", self.get_policies_age_seconds())
        return data

    def get_policy_set(self) -> Optional[PolicySet]:
        """The cached version evaluate reads (lock-free read via reference): the set read through the model where the
        policies were received or loaded, or None when they hold none (sync_engine.md Numeric domain)."""
        policy_set = self._policy_set
        if policy_set is not None:
            self._check_stale("policies", self.get_policies_age_seconds())
        return policy_set

    def get_redaction_fields(self) -> list:
        """The org's declared fields from the last policy pull (event_format.md §Redaction, row 163(a)), which the
        local store redacts with its own. Empty until a pull carrying them lands."""
        data = self._policies or {}
        return list((data.get("redaction_policy") or {}).get(ORG_FIELDS) or ())

    def get_policies_etag(self) -> Optional[str]:
        """Get current policies ETag for conditional requests."""
        return self._policies_etag

    def get_policies_age_seconds(self) -> float:
        """Seconds since policies were last updated."""
        if self._policies_updated_at == 0.0:
            return float("inf")
        return time.monotonic() - self._policies_updated_at

    def update_policies(self, data: dict, etag: Optional[str] = None) -> None:
        """Atomically update policy cache (memory + disk).

        Memory is always updated even if disk write fails. Disk divergence
        is tracked and self-heals on the next successful sync cycle.

        Args:
            data: Full policy response payload
            etag: ETag value from server response
        """
        disk_ok = self._try_disk_write("policies.json", data, etag, "policies.etag")
        policy_set = cached_policy_set(data)

        with self._lock:
            self._policies = data
            self._policy_set = policy_set
            self._policies_etag = etag
            self._policies_updated_at = time.monotonic()
            self._disk_diverged = not disk_ok
            # TICKET-116: any successful update_policies — initial or
            # background — flips cache_status to "synced" from this
            # point forward in the process.
            self._synced_this_process = True
            # A pull that lands ends the tick's part (sync_engine.md 2.4; row 240)
            self._tick_part = None

        self._stale_warned.pop("policies", None)
        logger.debug("Updated policy cache (etag=%s, disk_ok=%s)", etag, disk_ok)

    # ── Route cache ──────────────────────────────────────────────

    def get_routes(self) -> Optional[list]:
        """Get cached route configurations (lock-free read via reference)."""
        data = self._routes
        if data is not None:
            self._check_stale("routes", self.get_routes_age_seconds())
        return data

    def get_routes_etag(self) -> Optional[str]:
        """Get current routes ETag for conditional requests."""
        return self._routes_etag

    def get_routes_age_seconds(self) -> float:
        """Seconds since routes were last updated."""
        if self._routes_updated_at == 0.0:
            return float("inf")
        return time.monotonic() - self._routes_updated_at

    def update_routes(self, data: list, etag: Optional[str] = None) -> None:
        """Atomically update route cache (memory + disk).

        Args:
            data: Full route response payload
            etag: ETag value from server response
        """
        disk_ok = self._try_disk_write("routes.json", data, etag, "routes.etag")

        with self._lock:
            self._routes = data
            self._routes_etag = etag
            self._routes_updated_at = time.monotonic()
            self._disk_diverged = not disk_ok

        self._stale_warned.pop("routes", None)
        logger.debug("Updated route cache (etag=%s, disk_ok=%s)", etag, disk_ok)

    # ── Kill switch cache ────────────────────────────────────────

    def get_kill_switches(self) -> Optional[list]:
        """The last tick's switch list (lock-free read via reference)."""
        tick = self._kill_switches
        if tick is None:
            return None
        self._check_stale("kill_switches", self.get_kill_switches_age_seconds())
        return tick.get("kill_switches")

    def tick_part(self) -> Optional[PolicySet]:
        """The set a tick no pull has followed names, as far as its switches go (lock-free read via reference):
        evaluate reads it first, and a switch it binds stands under its version (sync_engine.md 2.4; HTL-29 row 240).
        None when the last tick agrees with the cached version, or a pull has landed since it."""
        return self._tick_part

    def policies_landed(self) -> None:
        """A policy pull answered 304: the cached version is the server's as of the pull, so the tick's part ends,
        as it does when a new version lands (sync_engine.md 2.4)."""
        with self._lock:
            self._tick_part = None

    def get_kill_switches_age_seconds(self) -> float:
        """Seconds since kill switches were last updated."""
        if self._kill_switches_updated_at == 0.0:
            return float("inf")
        return time.monotonic() - self._kill_switches_updated_at

    def update_kill_switches(self, tick: dict) -> Optional[tuple[tuple, tuple]]:
        """Atomically update kill switch cache (memory + disk) with the tick as received.

        No ETag — kill switches always return full state. The engine runs its channels one at a time, so a pull that
        lands after this call was read after this tick.

        Args:
            tick: The kill switch response payload: `kill_switches`, `policy_set`, `server_time`

        Returns:
            The version the tick names and the cached version, each with its live switches, when they differ (the
            engine pulls), else None
        """
        disk_ok = self._try_disk_write("kill_switches.json", tick)

        with self._lock:
            difference = self._hold_tick(tick)
            self._kill_switches_updated_at = time.monotonic()
            self._disk_diverged = not disk_ok

        self._stale_warned.pop("kill_switches", None)
        logger.debug(
            "Updated kill switch cache (%d switches, disk_ok=%s)",
            len(tick.get("kill_switches") or []), disk_ok,
        )
        return difference

    def _hold_tick(self, tick: dict) -> Optional[tuple[tuple, tuple]]:
        """Hold the tick, and its part when the version it names is not the cached one; under the lock."""
        difference = version_difference(tick, self._policy_set)
        self._kill_switches = tick
        self._tick_part = _tick_part(tick) if difference is not None else None
        return difference

    # ── Cache status ─────────────────────────────────────────────

    def cache_status(self) -> str:
        """Return the per-decision cache status (TICKET-116).

        Returns one of:
          - 'synced'    — `update_policies()` has been called this process
                          (initial or background sync succeeded). Policies
                          in memory are fresh from the server.
          - 'from_disk' — Policies in memory came from the on-disk cache
                          loaded at startup; no successful sync has run
                          this process yet. May be stale.
          - 'empty'     — No policies in memory. Evaluator falls back to
                          OBSERVE_ALL on every action. Either cold start
                          with no disk cache, or sync has never succeeded.

        Consumers stamp this on every Decision so callers can detect
        "I'm running against a stale or empty cache" and adjust their
        own behavior (e.g. defer high-stakes actions until first sync).
        """
        if self._synced_this_process:
            return "synced"
        if self._policies is not None:
            return "from_disk"
        return "empty"

    def status(self) -> dict:
        """Return cache status for health reporting."""
        return {
            "cache_dir": str(self._base_dir),
            "disk_synced": not self._disk_diverged,
            "policies": {
                "cached": self._policies is not None,
                "age_seconds": round(self.get_policies_age_seconds(), 1),
                "etag": self._policies_etag,
            },
            "routes": {
                "cached": self._routes is not None,
                "age_seconds": round(self.get_routes_age_seconds(), 1),
                "etag": self._routes_etag,
            },
            "kill_switches": {
                "cached": self._kill_switches is not None,
                "age_seconds": round(self.get_kill_switches_age_seconds(), 1),
            },
        }

    # ── Staleness check ──────────────────────────────────────────

    def _check_stale(self, channel: str, age_seconds: float) -> None:
        """Log a CACHE_STALE warning once if data exceeds max stale age."""
        if age_seconds > self._max_stale_age and not self._stale_warned.get(channel):
            logger.warning(
                "CACHE_STALE: Cached %s are %.0f seconds old "
                "(max stale age: %.0f seconds). Sync may be failing. "
                "Continuing with stale data.",
                channel, age_seconds, self._max_stale_age,
            )
            self._stale_warned[channel] = True

    # ── Disk write helper ────────────────────────────────────────

    def _try_disk_write(
        self,
        filename: str,
        data: Any,
        etag: Optional[str] = None,
        etag_filename: Optional[str] = None,
    ) -> bool:
        """Attempt to write data to disk. Returns True on success."""
        admit_sync(sync_channel(filename), data, shape=sync_numeric_shape(sync_channel(filename), cache=True))
        try:
            self._write_json(filename, data)
            if etag and etag_filename:
                self._write_text(etag_filename, etag)
            return True
        except Exception as e:
            logger.warning(
                "Failed to persist %s to disk: %s. "
                "In-memory cache updated but on-disk cache is stale. "
                "Next successful sync will repair disk cache.",
                filename, e,
            )
            return False

    # ── Orphaned temp file cleanup ───────────────────────────────

    def _cleanup_orphans(self, max_age_seconds: float = 300.0) -> int:
        """Remove orphaned .tmp files older than max_age_seconds.

        Called during startup to clean up from previous crashes.
        Returns the number of files removed.
        """
        if not self._base_dir.exists():
            return 0

        removed = 0
        now = time.time()
        try:
            for entry in self._base_dir.iterdir():
                if entry.suffix == ".tmp" and entry.is_file():
                    try:
                        age = now - entry.stat().st_mtime
                        if age > max_age_seconds:
                            entry.unlink()
                            removed += 1
                    except OSError:
                        pass
        except OSError:
            pass

        if removed:
            logger.info("Cleaned up %d orphaned temp files", removed)
        return removed

    # ── Disk I/O helpers (atomic writes) ─────────────────────────

    def _ensure_dir(self) -> None:
        """Ensure cache directory exists (cached after first call)."""
        if self._dir_created:
            return
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._dir_created = True

    def _write_json(self, filename: str, data: Any) -> None:
        """Atomically write JSON + integrity hash to cache file.

        Uses write-to-temp-then-rename for POSIX atomicity. The sidecar is part of the write: a file without it is
        discarded on read (sync_engine.md §4 "Integrity"), so a sidecar that cannot be written fails the write.
        Raises on failure (callers handle via _try_disk_write).
        """
        self._ensure_dir()
        target = self._base_dir / filename
        content = json.dumps(data, separators=(",", ":")).encode()

        # Write data file atomically
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._base_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content.decode())
            os.rename(tmp_path, str(target))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Write integrity hash
        content_hash = hashlib.sha256(content).hexdigest()
        hash_file = str(target) + ".sha256"
        fd2, tmp_path2 = tempfile.mkstemp(
            dir=str(self._base_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd2, "w") as f:
                f.write(content_hash)
            os.rename(tmp_path2, hash_file)
        except Exception:
            try:
                os.unlink(tmp_path2)
            except OSError:
                pass
            raise

    def _write_text(self, filename: str, content: str) -> None:
        """Atomically write text to cache file.

        Raises on failure (callers handle via _try_disk_write).
        """
        self._ensure_dir()
        target = self._base_dir / filename

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._base_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.rename(tmp_path, str(target))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _read_json(self, filename: str) -> Optional[Any]:
        """Read JSON from cache file with integrity verification.

        Returns None if file is missing, invalid JSON, or its hash sidecar is absent, unreadable or names another
        hash: an absent hash proves nothing (sync_engine.md §4 "Integrity"; HTL-29 row 137).
        """
        path = self._base_dir / filename
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read cache file %s: %s", path, e)
            return None

        admit_sync(sync_channel(filename), data, shape=sync_numeric_shape(sync_channel(filename), cache=True))
        # Verify the integrity hash
        hash_path = Path(str(path) + ".sha256")
        try:
            expected = hash_path.read_text().strip()
        except (OSError, ValueError) as e:
            logger.error(
                "CACHE_INTEGRITY_VIOLATION: %s has no readable content hash (%s). Discarding cached data.",
                path, e,
            )
            return None
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            logger.error(
                "CACHE_INTEGRITY_VIOLATION: %s content hash mismatch "
                "(expected=%s, got=%s). Discarding cached data.",
                path, expected[:16] + "...", actual[:16] + "...",
            )
            return None

        return data

    def _read_text(self, filename: str) -> Optional[str]:
        """Read text from cache file, return None if missing."""
        path = self._base_dir / filename
        if not path.exists():
            return None
        try:
            return path.read_text().strip()
        except OSError as e:
            logger.warning("Failed to read cache file %s: %s", path, e)
            return None

    def _file_mtime(self, filename: str) -> float:
        """Get monotonic-compatible timestamp reflecting actual file age.

        Converts wall-clock file mtime to a monotonic timestamp by computing
        the age of the file and subtracting from monotonic now. This preserves
        age semantics while keeping all timestamps on the monotonic clock.
        """
        path = self._base_dir / filename
        try:
            file_mtime_wall = path.stat().st_mtime
            wall_now = time.time()
            age_seconds = max(0.0, wall_now - file_mtime_wall)
            return time.monotonic() - age_seconds
        except OSError:
            return 0.0
