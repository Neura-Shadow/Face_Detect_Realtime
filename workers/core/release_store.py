"""Phase 13G immutable release store with an atomic activation switch.

Layout::

    /opt/ma-vlna/
    ├── releases/<release-id>/     immutable after install
    ├── current -> releases/<active>
    ├── previous -> releases/<previous>
    ├── last-known-good -> releases/<confirmed>
    ├── staging/
    └── state/

The one property everything else depends on: **switching ``current`` is
atomic**. A symlink cannot be edited in place, so the switch is done by
creating a temporary symlink beside it and calling ``os.rename`` onto the
target name. ``rename(2)`` within a directory is atomic, so any observer — and
any crash — sees either the old target or the new one. There is no instant at
which ``current`` is missing, dangling, or pointing at half a release.

The obvious wrong version of this is ``unlink`` then ``symlink``: it works
almost always, and leaves no ``current`` at all if the process dies in the
microsecond between them. That window is exactly what a rollback test would
never reproduce and a power cut eventually would.

Releases are made read-only after installation. That is a guard against
accident, not against an attacker — anyone who can write the store can chmod it
back. This phase provides integrity and compatibility, not security.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tarfile
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

RELEASES_DIRNAME = "releases"
STAGING_DIRNAME = "staging"
STATE_DIRNAME = "state"
CURRENT_LINK = "current"
PREVIOUS_LINK = "previous"
LAST_KNOWN_GOOD_LINK = "last-known-good"

#: Links that pin a release against deletion. Cleanup must never remove a
#: release any of these point at.
PROTECTED_LINKS = (CURRENT_LINK, PREVIOUS_LINK, LAST_KNOWN_GOOD_LINK)

#: Never keep fewer than this many releases, whatever cleanup is asked for.
MIN_RETAINED_RELEASES = 2


class ReleaseStoreError(RuntimeError):
    def __init__(self, classification: str, message: str) -> None:
        super(ReleaseStoreError, self).__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


class ReleaseStore:
    """The on-disk release layout and its atomic operations."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)

    # ── layout ──────────────────────────────────────────────────────────────

    @property
    def releases_dir(self) -> str:
        return os.path.join(self.root, RELEASES_DIRNAME)

    @property
    def staging_dir(self) -> str:
        return os.path.join(self.root, STAGING_DIRNAME)

    @property
    def state_dir(self) -> str:
        return os.path.join(self.root, STATE_DIRNAME)

    def link_path(self, name: str) -> str:
        return os.path.join(self.root, name)

    def release_path(self, release_id: str) -> str:
        return os.path.join(self.releases_dir, release_id)

    def ensure_layout(self) -> Dict[str, Any]:
        created = []
        for path in (self.root, self.releases_dir, self.staging_dir, self.state_dir):
            if not os.path.isdir(path):
                os.makedirs(path, exist_ok=True)
                created.append(path)
        return {"root": self.root, "created": created, "layout_ready": True}

    # ── links ───────────────────────────────────────────────────────────────

    def resolve(self, name: str) -> Optional[str]:
        """The release id a link points at, or None when it is unset."""

        path = self.link_path(name)
        try:
            target = os.readlink(path)
        except OSError:
            return None
        return os.path.basename(target.rstrip("/")) or None

    def resolve_path(self, name: str) -> Optional[str]:
        release_id = self.resolve(name)
        return self.release_path(release_id) if release_id else None

    def link_is_valid(self, name: str) -> bool:
        """A link that points at a release that exists and is installed."""

        release_id = self.resolve(name)
        if not release_id:
            return False
        return self.is_installed(release_id)

    def set_link_atomic(self, name: str, release_id: str) -> Dict[str, Any]:
        """Point ``name`` at ``release_id`` atomically.

        Creates a uniquely named temporary symlink in the same directory and
        renames it onto the target. Same-directory rename is atomic, so a crash
        at any point leaves the previous target intact rather than no target.
        """

        target = self.release_path(release_id)
        if not os.path.isdir(target):
            raise ReleaseStoreError(
                "release_missing", "cannot link %s to absent release %s" % (name, release_id)
            )
        link = self.link_path(name)
        previous = self.resolve(name)
        # A unique temp name so two concurrent switches cannot collide on it.
        temporary = "%s.tmp.%d.%d" % (link, os.getpid(), int(time.time() * 1e6) % 1_000_000)
        relative_target = os.path.join(RELEASES_DIRNAME, release_id)
        try:
            os.symlink(relative_target, temporary)
        except OSError as exc:
            raise ReleaseStoreError(
                "symlink_failed", "%s: %s" % (type(exc).__name__, exc)
            )
        try:
            os.rename(temporary, link)
        except OSError as exc:
            # Clean up the temp link so a failed switch leaves nothing behind.
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise ReleaseStoreError("rename_failed", "%s: %s" % (type(exc).__name__, exc))
        self._fsync_dir(self.root)
        return {
            "link": name,
            "release_id": release_id,
            "previous_release_id": previous,
            "atomic": True,
            "method": "symlink+rename",
        }

    @staticmethod
    def _fsync_dir(path: str) -> None:
        """Persist the rename itself, not just the file data.

        Without this the directory entry can still be in page cache when power
        is lost, and the switch that was atomic in memory never reaches disk.
        """

        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    # ── releases ────────────────────────────────────────────────────────────

    def list_releases(self) -> List[str]:
        try:
            names = os.listdir(self.releases_dir)
        except OSError:
            return []
        return sorted(
            name for name in names if os.path.isdir(os.path.join(self.releases_dir, name))
        )

    def is_installed(self, release_id: str) -> bool:
        """A release is installed only once its completion marker exists.

        The marker is written last. A release interrupted mid-copy has files
        but no marker, so it can never be activated and is safe to discard.
        """

        return os.path.isfile(os.path.join(self.release_path(release_id), ".installed"))

    def mark_installed(self, release_id: str) -> None:
        path = os.path.join(self.release_path(release_id), ".installed")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("%s\n" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            handle.flush()
            os.fsync(handle.fileno())
        self._fsync_dir(self.release_path(release_id))

    def install_from_directory(
        self, release_id: str, source_dir: str, *, make_immutable: bool = True
    ) -> Dict[str, Any]:
        """Install a staged directory as an immutable release.

        The copy lands in a temporary directory and is renamed into place, so
        ``releases/<id>`` never exists in a half-copied state.
        """

        if self.is_installed(release_id):
            raise ReleaseStoreError(
                "release_exists", "release %s is already installed and immutable" % release_id
            )
        os.makedirs(self.releases_dir, exist_ok=True)
        final = self.release_path(release_id)
        staging = tempfile.mkdtemp(prefix=".incoming-%s-" % release_id, dir=self.releases_dir)
        try:
            inner = os.path.join(staging, "payload")
            shutil.copytree(source_dir, inner)
            if os.path.exists(final):
                shutil.rmtree(final)
            os.rename(inner, final)
            self._fsync_dir(self.releases_dir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self.mark_installed(release_id)
        if make_immutable:
            self.make_immutable(release_id)
        return {
            "release_id": release_id,
            "path": final,
            "installed": True,
            "immutable": make_immutable,
        }

    def install_from_package(
        self, release_id: str, package_path: str, *, make_immutable: bool = True
    ) -> Dict[str, Any]:
        """Unpack a release tarball into the store."""

        extract_dir = tempfile.mkdtemp(prefix=".unpack-%s-" % release_id, dir=self.staging_dir)
        try:
            with tarfile.open(package_path, "r:gz") as archive:
                _safe_extract(archive, extract_dir)
            entries = os.listdir(extract_dir)
            source = (
                os.path.join(extract_dir, entries[0])
                if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0]))
                else extract_dir
            )
            return self.install_from_directory(
                release_id, source, make_immutable=make_immutable
            )
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def make_immutable(self, release_id: str) -> Dict[str, Any]:
        """Drop write bits across the release.

        Accident protection, not security: anyone who can write the store can
        undo this. It exists so a release cannot be edited in place and then
        quietly disagree with the hash that was validated.
        """

        root = self.release_path(release_id)
        changed = 0
        for base, dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(base, name)
                try:
                    mode = os.stat(path).st_mode
                    os.chmod(path, mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
                    changed += 1
                except OSError:
                    continue
            for name in dirs:
                path = os.path.join(base, name)
                try:
                    mode = os.stat(path).st_mode
                    os.chmod(path, mode & ~stat.S_IWGRP & ~stat.S_IWOTH)
                except OSError:
                    continue
        return {"release_id": release_id, "files_write_protected": changed}

    def make_mutable(self, release_id: str) -> None:
        """Restore write permission so a release can be removed."""

        root = self.release_path(release_id)
        for base, dirs, files in os.walk(root):
            for name in dirs + files:
                path = os.path.join(base, name)
                try:
                    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
                except OSError:
                    continue
        try:
            os.chmod(root, os.stat(root).st_mode | stat.S_IWUSR)
        except OSError:
            pass

    # ── cleanup ─────────────────────────────────────────────────────────────

    def protected_release_ids(self) -> Dict[str, Optional[str]]:
        return {name: self.resolve(name) for name in PROTECTED_LINKS}

    def cleanup(self, *, keep: int = MIN_RETAINED_RELEASES, dry_run: bool = False) -> Dict[str, Any]:
        """Remove old releases, never one a protected link points at.

        Three independent guards, because deleting the running release is the
        one mistake this store must never make: a release is skipped if any
        protected link resolves to it, if it is within the newest ``keep``, or
        if removing it would drop the store below the retention floor.
        """

        keep = max(MIN_RETAINED_RELEASES, int(keep))
        protected = {value for value in self.protected_release_ids().values() if value}
        releases = self.list_releases()
        # Newest first by mtime, so "keep N" means the N most recent.
        by_recency = sorted(
            releases,
            key=lambda name: os.path.getmtime(self.release_path(name)),
            reverse=True,
        )
        retained = set(by_recency[:keep]) | protected
        candidates = [name for name in by_recency if name not in retained]

        removed = []  # type: List[str]
        skipped = []  # type: List[Dict[str, Any]]
        for name in candidates:
            remaining = len(releases) - len(removed)
            if remaining <= MIN_RETAINED_RELEASES:
                skipped.append({"release_id": name, "reason": "retention_floor"})
                continue
            if name in protected:
                skipped.append({"release_id": name, "reason": "protected_link"})
                continue
            if dry_run:
                removed.append(name)
                continue
            self.make_mutable(name)
            shutil.rmtree(self.release_path(name), ignore_errors=True)
            removed.append(name)
        for name in retained:
            if name in protected:
                skipped.append({"release_id": name, "reason": "protected_link"})
        return {
            "removed": removed,
            "removed_count": len(removed),
            "retained": sorted(retained),
            "skipped": skipped,
            "protected": sorted(protected),
            "keep": keep,
            "dry_run": bool(dry_run),
            "retention_floor": MIN_RETAINED_RELEASES,
        }

    def prune_staging(self, *, older_than_sec: float = 0.0) -> Dict[str, Any]:
        """Discard staging leftovers. Never touches installed releases."""

        removed = []
        now = time.time()
        try:
            entries = os.listdir(self.staging_dir)
        except OSError:
            return {"removed": [], "removed_count": 0}
        for name in entries:
            path = os.path.join(self.staging_dir, name)
            try:
                if older_than_sec and (now - os.path.getmtime(path)) < older_than_sec:
                    continue
            except OSError:
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.unlink(path)
                except OSError:
                    continue
            removed.append(name)
        return {"removed": removed, "removed_count": len(removed)}

    # ── reporting ───────────────────────────────────────────────────────────

    def partial_release_count(self) -> int:
        """Releases present on disk but never completed."""

        return sum(1 for name in self.list_releases() if not self.is_installed(name))

    def to_dict(self) -> Dict[str, Any]:
        links = {}
        for name in PROTECTED_LINKS:
            release_id = self.resolve(name)
            links[name] = {
                "release_id": release_id,
                "valid": self.link_is_valid(name),
                "path": self.link_path(name),
            }
        releases = self.list_releases()
        return {
            "release_root": self.root,
            "releases": releases,
            "release_count": len(releases),
            "installed_releases": [name for name in releases if self.is_installed(name)],
            "partial_release_count": self.partial_release_count(),
            "links": links,
            "current_release_id": self.resolve(CURRENT_LINK),
            "previous_release_id": self.resolve(PREVIOUS_LINK),
            "last_known_good_release_id": self.resolve(LAST_KNOWN_GOOD_LINK),
            "atomic_switch_method": "symlink+rename",
            "retention_floor": MIN_RETAINED_RELEASES,
        }


def _safe_extract(archive: tarfile.TarFile, destination: str) -> None:
    """Extract without letting a member escape the destination.

    A tarball is untrusted input even when we built it: a member named
    ``../../etc/something`` would otherwise be written outside the store.
    """

    destination = os.path.abspath(destination)
    for member in archive.getmembers():
        target = os.path.abspath(os.path.join(destination, member.name))
        if not (target == destination or target.startswith(destination + os.sep)):
            raise ReleaseStoreError(
                "package_path_traversal", "member escapes destination: %s" % member.name
            )
        if member.issym() or member.islnk():
            link_target = os.path.abspath(
                os.path.join(os.path.dirname(target), member.linkname)
            )
            if not link_target.startswith(destination + os.sep):
                raise ReleaseStoreError(
                    "package_link_traversal", "link escapes destination: %s" % member.name
                )
    archive.extractall(destination)
