"""Disk + memory cache for sync engine.

The cache provides fast in-memory reads for the evaluator hot path
while persisting data to disk for warm-start across SDK restarts.

Key properties:
- Thread-safe: Lock for writes, lock-free reads via reference swap
- Atomic disk writes: Write .tmp then os.rename() (POSIX atomic)
- TTL tracking: Each channel has independent freshness checks
- Warm start: Load from disk on init with actual file age preservation
- Integrity: SHA-256 hash verification on cached files
- Max-stale: Warning when cached data exceeds staleness threshold

Cache structure on disk:
    {cache_dir}/{org_id}/{environment}/
        policies.json        # Full policy data
        policies.json.sha256 # Content hash for integrity verification
        policies.etag        # ETag for conditional requests
        routes.json          # Route configurations
        routes.json.sha256   # Content hash
        routes.etag          # ETag for conditional requests
        kill_switches.json   # Active kill switch state
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

logger = logging.getLogger(__name__)


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

        self._routes: Optional[list] = None
        self._routes_etag: Optional[str] = None
        self._routes_updated_at: float = 0.0

        self._kill_switches: Optional[list] = None
        self._kill_switches_updated_at: float = 0.0

        # Health tracking
        self._disk_diverged = False
        self._stale_warned: dict[str, bool] = {}

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
            with self._lock:
                self._policies = policies
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

        kill_switches = self._read_json("kill_switches.json")
        if kill_switches is not None:
            with self._lock:
                self._kill_switches = kill_switches
                self._kill_switches_updated_at = self._file_mtime("kill_switches.json")
            loaded_any = True
            logger.info("Loaded cached kill switches from disk")

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

        with self._lock:
            self._policies = data
            self._policies_etag = etag
            self._policies_updated_at = time.monotonic()
            self._disk_diverged = not disk_ok

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
        """Get cached kill switch state (lock-free read via reference)."""
        data = self._kill_switches
        if data is not None:
            self._check_stale("kill_switches", self.get_kill_switches_age_seconds())
        return data

    def get_kill_switches_age_seconds(self) -> float:
        """Seconds since kill switches were last updated."""
        if self._kill_switches_updated_at == 0.0:
            return float("inf")
        return time.monotonic() - self._kill_switches_updated_at

    def update_kill_switches(self, data: list) -> None:
        """Atomically update kill switch cache (memory + disk).

        No ETag — kill switches always return full state.

        Args:
            data: Full kill switch response payload
        """
        disk_ok = self._try_disk_write("kill_switches.json", data)

        with self._lock:
            self._kill_switches = data
            self._kill_switches_updated_at = time.monotonic()
            self._disk_diverged = not disk_ok

        self._stale_warned.pop("kill_switches", None)
        logger.debug(
            "Updated kill switch cache (%d switches, disk_ok=%s)",
            len(data), disk_ok,
        )

    # ── Cache status ─────────────────────────────────────────────

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

        Uses write-to-temp-then-rename for POSIX atomicity.
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

        # Write integrity hash (best-effort — data is already persisted)
        content_hash = hashlib.sha256(content).hexdigest()
        hash_file = str(target) + ".sha256"
        try:
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
        except Exception as e:
            logger.warning("Failed to write hash file %s: %s", hash_file, e)

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

        Returns None if file is missing, invalid JSON, or hash mismatch.
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

        # Verify integrity hash if present
        hash_path = Path(str(path) + ".sha256")
        if hash_path.exists():
            try:
                expected = hash_path.read_text().strip()
                actual = hashlib.sha256(raw).hexdigest()
                if actual != expected:
                    logger.error(
                        "CACHE_INTEGRITY_VIOLATION: %s content hash mismatch "
                        "(expected=%s, got=%s). Discarding cached data.",
                        path, expected[:16] + "...", actual[:16] + "...",
                    )
                    return None
            except OSError as e:
                logger.warning("Failed to read hash file %s: %s", hash_path, e)

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
