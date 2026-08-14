"""Phase 13G release store, manifest and state-machine tests.

The property everything else rests on is that switching ``current`` is atomic,
so it is tested by observing the link at every point a crash could occur rather
than by reading the implementation and agreeing with it.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13g_package import collect_payload, worktree_provenance  # noqa: E402
from workers.core.deployment_state import (  # noqa: E402
    ACTIVATING,
    CONFIRMED,
    FAILED,
    IDLE,
    PROBATION,
    ROLLED_BACK,
    ROLLING_BACK,
    STAGED,
    VALIDATED,
    DeploymentState,
    DeploymentStateError,
    describe_state_machine,
)
from workers.core.release_manifest import (  # noqa: E402
    FROZEN_PROTOCOL,
    ManifestError,
    ReleaseManifest,
    build_release_manifest,
    check_compatibility,
    parse_version,
    scan_for_secrets,
    sha256_file,
)
from workers.core.release_store import (  # noqa: E402
    CURRENT_LINK,
    LAST_KNOWN_GOOD_LINK,
    MIN_RETAINED_RELEASES,
    PREVIOUS_LINK,
    ReleaseStore,
    ReleaseStoreError,
)

HAS_SYMLINK = hasattr(os, "symlink")


def fake_credential(prefix: str, body: str) -> str:
    """Assemble a credential-shaped literal at test time.

    Passed as fragments deliberately. A verbatim ``ghp_...`` or ``sk-...``
    string committed to the repository can trip provider-side secret scanning
    and push protection, and a test fixture is a poor reason to teach a scanner
    that this repository ships tokens. None of these are real credentials; they
    exist only to be written into a temporary directory and scanned.
    """

    return prefix + body


def make_release(store: ReleaseStore, release_id: str, *, content: str = "x") -> str:
    source = tempfile.mkdtemp(prefix="rel-src-")
    with open(os.path.join(source, "marker.txt"), "w", encoding="utf-8") as handle:
        handle.write(content)
    os.makedirs(os.path.join(source, "scripts"), exist_ok=True)
    with open(os.path.join(source, "scripts", "run.py"), "w", encoding="utf-8") as handle:
        handle.write("# %s\n" % release_id)
    store.install_from_directory(release_id, source)
    return release_id


def _symlinks_supported() -> bool:
    if not HAS_SYMLINK:
        return False
    probe = tempfile.mkdtemp(prefix="symlink-probe-")
    try:
        target = os.path.join(probe, "target")
        os.makedirs(target)
        os.symlink("target", os.path.join(probe, "link"))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        import shutil

        shutil.rmtree(probe, ignore_errors=True)


SYMLINKS_OK = _symlinks_supported()
requires_symlinks = unittest.skipUnless(
    SYMLINKS_OK,
    "symlinks unavailable on this host (Windows needs Developer Mode or admin); "
    "the store is Linux-targeted and these run on the Jetson in Gate A",
)


@requires_symlinks
class TestAtomicSwitch(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-store-")
        self.addCleanup(self._dir.cleanup)
        self.store = ReleaseStore(self._dir.name)
        self.store.ensure_layout()

    def test_switch_points_current_at_the_release(self) -> None:
        make_release(self.store, "relA")
        result = self.store.set_link_atomic(CURRENT_LINK, "relA")
        self.assertTrue(result["atomic"])
        self.assertEqual(self.store.resolve(CURRENT_LINK), "relA")
        self.assertTrue(self.store.link_is_valid(CURRENT_LINK))

    def test_switch_leaves_no_temporary_links_behind(self) -> None:
        make_release(self.store, "relA")
        make_release(self.store, "relB")
        self.store.set_link_atomic(CURRENT_LINK, "relA")
        self.store.set_link_atomic(CURRENT_LINK, "relB")
        leftovers = [name for name in os.listdir(self.store.root) if ".tmp." in name]
        self.assertEqual(leftovers, [], "a temporary switch link survived")

    def test_current_is_never_absent_during_a_switch(self) -> None:
        # The failure this design exists to avoid is unlink-then-symlink, which
        # leaves no `current` at all for an instant. Hammer the link from
        # another thread while switching repeatedly and assert it always
        # resolves to one of the two releases.
        make_release(self.store, "relA")
        make_release(self.store, "relB")
        self.store.set_link_atomic(CURRENT_LINK, "relA")
        observed = []
        stop = threading.Event()

        def observer() -> None:
            while not stop.is_set():
                observed.append(self.store.resolve(CURRENT_LINK))

        watcher = threading.Thread(target=observer)
        watcher.start()
        try:
            for index in range(40):
                self.store.set_link_atomic(CURRENT_LINK, "relB" if index % 2 else "relA")
        finally:
            stop.set()
            watcher.join(timeout=5)

        self.assertGreater(len(observed), 10, "observer did not sample enough")
        self.assertNotIn(None, observed, "current was missing at some point during a switch")
        self.assertTrue(set(observed) <= {"relA", "relB"})

    def test_switching_to_a_missing_release_is_refused(self) -> None:
        with self.assertRaises(ReleaseStoreError) as ctx:
            self.store.set_link_atomic(CURRENT_LINK, "does-not-exist")
        self.assertEqual(ctx.exception.classification, "release_missing")
        self.assertIsNone(self.store.resolve(CURRENT_LINK))

    def test_a_failed_switch_leaves_the_previous_target(self) -> None:
        make_release(self.store, "relA")
        self.store.set_link_atomic(CURRENT_LINK, "relA")
        try:
            self.store.set_link_atomic(CURRENT_LINK, "absent")
        except ReleaseStoreError:
            pass
        self.assertEqual(self.store.resolve(CURRENT_LINK), "relA")


@requires_symlinks
class TestReleaseImmutability(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-imm-")
        self.addCleanup(self._dir.cleanup)
        self.store = ReleaseStore(self._dir.name)
        self.store.ensure_layout()

    def test_installed_release_files_are_not_writable(self) -> None:
        make_release(self.store, "relA")
        path = os.path.join(self.store.release_path("relA"), "marker.txt")
        mode = os.stat(path).st_mode
        self.assertFalse(mode & stat.S_IWUSR, "release file remained writable")

    def test_reinstalling_an_existing_release_is_refused(self) -> None:
        make_release(self.store, "relA")
        source = tempfile.mkdtemp(prefix="again-")
        with self.assertRaises(ReleaseStoreError) as ctx:
            self.store.install_from_directory("relA", source)
        self.assertEqual(ctx.exception.classification, "release_exists")

    def test_a_release_without_its_marker_is_not_installed(self) -> None:
        make_release(self.store, "relA")
        os.chmod(self.store.release_path("relA"), 0o755)
        os.unlink(os.path.join(self.store.release_path("relA"), ".installed"))
        self.assertFalse(self.store.is_installed("relA"))
        self.assertEqual(self.store.partial_release_count(), 1)

    def test_interrupted_install_leaves_no_installed_release(self) -> None:
        # Simulate a crash mid-copy: files present, marker never written.
        target = self.store.release_path("relPartial")
        os.makedirs(target)
        with open(os.path.join(target, "half.txt"), "w", encoding="utf-8") as handle:
            handle.write("incomplete")
        self.assertFalse(self.store.is_installed("relPartial"))
        with self.assertRaises(ReleaseStoreError):
            self.store.set_link_atomic(CURRENT_LINK, "relPartialX")


@requires_symlinks
class TestCleanupProtections(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-clean-")
        self.addCleanup(self._dir.cleanup)
        self.store = ReleaseStore(self._dir.name)
        self.store.ensure_layout()
        for index in range(6):
            make_release(self.store, "rel%d" % index)
            time.sleep(0.01)

    def test_cleanup_never_removes_current_previous_or_last_known_good(self) -> None:
        self.store.set_link_atomic(CURRENT_LINK, "rel0")
        self.store.set_link_atomic(PREVIOUS_LINK, "rel1")
        self.store.set_link_atomic(LAST_KNOWN_GOOD_LINK, "rel2")
        report = self.store.cleanup(keep=2)
        for protected in ("rel0", "rel1", "rel2"):
            self.assertNotIn(protected, report["removed"])
            self.assertTrue(os.path.isdir(self.store.release_path(protected)))

    def test_at_least_two_releases_always_remain(self) -> None:
        self.store.set_link_atomic(CURRENT_LINK, "rel5")
        report = self.store.cleanup(keep=1)
        self.assertGreaterEqual(len(self.store.list_releases()), MIN_RETAINED_RELEASES)
        self.assertEqual(report["retention_floor"], MIN_RETAINED_RELEASES)

    def test_keep_below_the_floor_is_raised_to_it(self) -> None:
        self.assertEqual(self.store.cleanup(keep=0, dry_run=True)["keep"], MIN_RETAINED_RELEASES)

    def test_dry_run_removes_nothing(self) -> None:
        before = set(self.store.list_releases())
        self.store.cleanup(keep=2, dry_run=True)
        self.assertEqual(set(self.store.list_releases()), before)


class TestReleaseManifest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-man-")
        self.addCleanup(self._dir.cleanup)
        self.tmp = self._dir.name
        self.engine = os.path.join(self.tmp, "engine.plan")
        with open(self.engine, "wb") as handle:
            handle.write(b"engine-bytes")
        self.startup = os.path.join(self.tmp, "startup.json")
        with open(self.startup, "w", encoding="utf-8") as handle:
            handle.write("{}")

    def payload(self, **overrides) -> Dict[str, Any]:
        base = build_release_manifest(
            release_id="relA",
            source_git_sha="a" * 40,
            created_at_utc="2026-01-01T00:00:00Z",
            package_sha256="b" * 64,
            engine_path=self.engine,
            engine_sha256=sha256_file(self.engine),
            engine_manifest_sha256=sha256_file(self.startup),
            facts={"arch": "aarch64", "python": "3.8.10", "l4t": "35.5.0",
                   "jetpack": "5.1.3", "cuda": "11.4", "tensorrt": "8.5.2.2"},
        )
        base.update(overrides)
        return base

    def test_a_complete_manifest_parses(self) -> None:
        manifest = ReleaseManifest(self.payload())
        self.assertEqual(manifest.release_id, "relA")
        self.assertEqual(manifest.get("protocol_version"), 1)
        self.assertFalse(manifest.get("int8_authority_allowed"))

    def test_int8_authority_cannot_be_granted(self) -> None:
        with self.assertRaises(ManifestError) as ctx:
            ReleaseManifest(self.payload(int8_authority_allowed=True))
        self.assertEqual(ctx.exception.classification, "manifest_int8_authority_forbidden")

    def test_missing_field_is_named(self) -> None:
        payload = self.payload()
        del payload["engine_sha256"]
        with self.assertRaises(ManifestError) as ctx:
            ReleaseManifest(payload)
        self.assertEqual(ctx.exception.classification, "manifest_incomplete")

    def test_malformed_hash_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as ctx:
            ReleaseManifest(self.payload(package_sha256="nope"))
        self.assertEqual(ctx.exception.classification, "manifest_hash_malformed")

    def test_unsafe_release_id_is_refused(self) -> None:
        # A release id becomes a directory name and a symlink target.
        for bad in ("../escape", "rel/A", "", "a" * 200):
            with self.assertRaises(ManifestError) as ctx:
                ReleaseManifest(self.payload(release_id=bad))
            self.assertEqual(ctx.exception.classification, "manifest_release_id_invalid")

    def test_schema_mismatch_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as ctx:
            ReleaseManifest(self.payload(schema_version=99))
        self.assertEqual(ctx.exception.classification, "manifest_schema_mismatch")

    def test_manifest_declares_what_it_is_not(self) -> None:
        payload = self.payload()
        self.assertTrue(payload["integrity_only"])
        for claim in ("signed", "secure_boot", "bootloader_ab", "anti_rollback_security"):
            self.assertFalse(payload[claim], "%s must never be claimed by this phase" % claim)


class TestCompatibilityMatrix(unittest.TestCase):
    """Exact fields must match exactly; version floors must be floors."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-compat-")
        self.addCleanup(self._dir.cleanup)
        self.tmp = self._dir.name
        self.engine = os.path.join(self.tmp, "engine.plan")
        with open(self.engine, "wb") as handle:
            handle.write(b"engine-bytes")

    def manifest(self, **overrides) -> ReleaseManifest:
        payload = build_release_manifest(
            release_id="relA", source_git_sha="a" * 40,
            created_at_utc="2026-01-01T00:00:00Z", package_sha256="b" * 64,
            engine_path=self.engine, engine_sha256=sha256_file(self.engine),
            engine_manifest_sha256="c" * 64,
            facts={"arch": "aarch64", "python": "3.8.10", "l4t": "35.5.0",
                   "jetpack": "5.1.3", "cuda": "11.4", "tensorrt": "8.5.2.2"},
        )
        payload.update(overrides)
        return ReleaseManifest(payload)

    def facts(self, **overrides) -> Dict[str, Any]:
        base = {"arch": "aarch64", "python": "3.8.10", "l4t": "35.5.0",
                "jetpack": "5.1.3", "cuda": "11.4", "tensorrt": "8.5.2.2"}
        base.update(overrides)
        return base

    def report(self, manifest=None, facts=None):
        return check_compatibility(
            manifest or self.manifest(), facts=facts or self.facts(),
            verify_package_hash=False,
        )

    def test_matching_target_is_compatible(self) -> None:
        report = self.report()
        self.assertTrue(report.compatible, report.to_dict()["failed_checks"])

    def test_wrong_architecture_is_rejected(self) -> None:
        report = self.report(facts=self.facts(arch="x86_64"))
        self.assertFalse(report.compatible)
        self.assertIn("arch_matches", report.to_dict()["failed_checks"])

    def test_wrong_python_minor_is_rejected(self) -> None:
        report = self.report(facts=self.facts(python="3.10.14"))
        self.assertIn("python_matches", report.to_dict()["failed_checks"])

    def test_python_patch_difference_is_accepted(self) -> None:
        # Pinning the patch level would reject a security update.
        report = self.report(facts=self.facts(python="3.8.19"))
        self.assertNotIn("python_matches", report.to_dict()["failed_checks"])

    def test_newer_target_stack_is_accepted(self) -> None:
        report = self.report(facts=self.facts(cuda="11.8", l4t="35.6.0"))
        failed = report.to_dict()["failed_checks"]
        self.assertNotIn("cuda_at_least", failed)
        self.assertNotIn("l4t_at_least", failed)

    def test_older_target_stack_is_rejected(self) -> None:
        report = self.report(facts=self.facts(cuda="10.2", l4t="32.7.1"))
        failed = report.to_dict()["failed_checks"]
        self.assertIn("cuda_at_least", failed)
        self.assertIn("l4t_at_least", failed)

    def test_unknown_target_version_is_not_treated_as_new_enough(self) -> None:
        report = self.report(facts=self.facts(cuda=""))
        self.assertIn("cuda_at_least", report.to_dict()["failed_checks"])

    def test_tensorrt_major_change_is_rejected(self) -> None:
        # TensorRT 10 is not source-compatible with the Phase 13C binding API.
        report = self.report(facts=self.facts(tensorrt="10.0.1"))
        self.assertIn("tensorrt_major_matches", report.to_dict()["failed_checks"])

    def test_protocol_mismatch_is_rejected_field_by_field(self) -> None:
        for field, good in FROZEN_PROTOCOL.items():
            bad = 999 if isinstance(good, int) else "0..99"
            report = self.report(manifest=self.manifest(**{field: bad}))
            self.assertIn(
                "protocol_%s" % field, report.to_dict()["failed_checks"],
                "%s mismatch was not rejected" % field,
            )

    def test_engine_hash_mismatch_is_rejected(self) -> None:
        report = self.report(manifest=self.manifest(engine_sha256="d" * 64))
        self.assertIn("engine_sha256_matches", report.to_dict()["failed_checks"])

    def test_missing_engine_is_rejected(self) -> None:
        # Build the manifest while the engine still exists, then remove it:
        # the case under test is "the manifest names an engine that is gone".
        manifest = self.manifest()
        os.unlink(self.engine)
        report = self.report(manifest=manifest)
        failed = report.to_dict()["failed_checks"]
        self.assertIn("engine_present", failed)
        self.assertIn("engine_sha256_matches", failed)

    def test_source_sha_mismatch_is_rejected(self) -> None:
        report = check_compatibility(
            self.manifest(), facts=self.facts(), verify_package_hash=False,
            expected_source_sha="f" * 40,
        )
        self.assertIn("source_git_sha_matches", report.to_dict()["failed_checks"])

    def test_package_hash_mismatch_is_rejected(self) -> None:
        package = os.path.join(self.tmp, "pkg.tar.gz")
        with open(package, "wb") as handle:
            handle.write(b"not-the-package-that-was-hashed")
        report = check_compatibility(
            self.manifest(), facts=self.facts(), package_path=package,
        )
        self.assertIn("package_sha256_matches", report.to_dict()["failed_checks"])

    def test_version_parsing(self) -> None:
        self.assertEqual(parse_version("8.5.2.2"), (8, 5, 2, 2))
        self.assertEqual(parse_version("35.5.0"), (35, 5, 0))
        self.assertEqual(parse_version(""), ())
        self.assertEqual(parse_version("unknown"), ())


class TestSecretScan(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-secret-")
        self.addCleanup(self._dir.cleanup)
        self.tmp = self._dir.name

    def write(self, name: str, text: str) -> None:
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def flagged(self) -> list:
        """Offenders with forward slashes, so assertions read the same on both
        hosts -- ``scan_for_secrets`` returns native separators."""

        return [entry.replace(os.sep, "/") for entry in scan_for_secrets(self.tmp)]

    def test_env_file_is_flagged(self) -> None:
        self.write(".env", "MA_VLNA_PC_HOST=1.2.3.4")
        self.assertIn(".env", scan_for_secrets(self.tmp))

    def test_assigned_secret_is_flagged(self) -> None:
        self.write("config/app.py", "API_KEY = 'live-secret-value'")
        self.assertTrue(scan_for_secrets(self.tmp))

    def test_example_documenting_a_variable_name_is_not_flagged(self) -> None:
        self.write("deployment/node.env.example", "MA_VLNA_TOKEN=replace-me")
        self.assertEqual(self.flagged(), [])

    def test_private_key_is_flagged(self) -> None:
        self.write("keys/id_rsa", "-----BEGIN RSA PRIVATE KEY-----\nabc\n")
        self.assertTrue(scan_for_secrets(self.tmp))

    # --- Real credential shapes must still be refused -----------------------
    #
    # These come first because the rest of this class relaxes the scan, and a
    # relaxation is only legitimate if the cases that matter still fail.

    def test_long_literal_assigned_to_a_secret_name_is_flagged(self) -> None:
        self.write("workers/core/thing.py", 'API_KEY = "aB3xQ91zLmPk04Rt"\n')
        self.assertEqual(self.flagged(), ["workers/core/thing.py"])

    def test_annotated_assignment_of_a_real_value_is_flagged(self) -> None:
        """The annotation must not smuggle a literal past the check."""

        self.write("workers/core/thing.py", 'api_key: str = "aB3xQ91zLmPk04Rt"\n')
        self.assertEqual(self.flagged(), ["workers/core/thing.py"])

    def test_credential_literal_is_flagged_under_an_innocent_name(self) -> None:
        """Name-independent patterns close the obvious hole in name matching."""

        secret = fake_credential("sk-", "live91zLmPk04RtQxA7")
        self.write("workers/core/thing.py", 'DEFAULT = "%s"\n' % secret)
        self.assertEqual(self.flagged(), ["workers/core/thing.py"])

    def test_credential_literal_is_flagged_even_in_an_example_file(self) -> None:
        """Exemption covers heuristic name matching, never a real key."""

        secret = fake_credential("ghp_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5")
        self.write("deployment/node.env.example", "TOKEN=%s\n" % secret)
        self.assertEqual(self.flagged(), ["deployment/node.env.example"])

    # --- The Gate B false positives -----------------------------------------
    #
    # Three ordinary source files, refused by the previous rule because it
    # matched any assignment whose name contained a secret-ish word.

    def test_placeholder_default_is_not_flagged(self) -> None:
        self.write("workers/core/config.py", '    api_key: str = "optional"\n')
        self.assertEqual(self.flagged(), [])

    def test_reading_a_secret_from_the_environment_is_not_flagged(self) -> None:
        """This is the pattern we want; flagging it punished correct code."""

        self.write("workers/core/config.py", '    api_key=_env("VLM_API_KEY", "optional"),\n')
        self.assertEqual(self.flagged(), [])

    def test_assignment_from_an_expression_is_not_flagged(self) -> None:
        self.write(
            "workers/core/vlm_reasoner.py",
            "        self._api_key = cfg.api_key\n",
        )
        self.assertEqual(self.flagged(), [])

    def test_unrelated_use_of_the_word_token_is_not_flagged(self) -> None:
        """``token`` here is a parsed word from a layer-group spec."""

        self.write(
            "workers/core/int8_layer_groups.py",
            '        token = raw.strip().upper()\n        if token == "CONV":\n',
        )
        self.assertEqual(self.flagged(), [])

    def test_interpolated_value_is_not_flagged(self) -> None:
        self.write("workers/core/thing.py", 'AUTH_TOKEN = "${MA_VLNA_AUTH_TOKEN}"\n')
        self.assertEqual(self.flagged(), [])

    def test_real_repository_sources_are_accepted(self) -> None:
        """The actual files Gate B refused, read from the repository itself.

        A synthetic reproduction can drift from the code it stands for, so this
        asserts against the real thing.
        """

        for relative in (
            "workers/core/config.py",
            "workers/core/int8_layer_groups.py",
            "workers/core/vlm_reasoner.py",
        ):
            source = REPO_ROOT / relative
            self.assertTrue(source.is_file(), "%s is missing" % relative)
            self.write(relative, source.read_text(encoding="utf-8", errors="ignore"))
        self.assertEqual(self.flagged(), [])


class TestReleaseProvenanceWithoutGit(unittest.TestCase):
    """A release has no .git, so provenance comes from its manifest.

    Found before Gate C rather than during it: the Phase 13F preflight asks
    git for HEAD, and an immutable release directory has no repository. Without
    this, repository_sha_match would fail for every release and no release
    could ever hold authority.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-prov-")
        self.addCleanup(self._dir.cleanup)
        self.root = self._dir.name

    def test_source_sha_is_read_from_the_release_manifest(self) -> None:
        from workers.core.service_preflight import _git_sha

        with open(os.path.join(self.root, "release.manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"source_git_sha": "b" * 40}, handle)
        self.assertEqual(_git_sha(self.root), "b" * 40)

    def test_a_directory_with_neither_git_nor_manifest_reports_nothing(self) -> None:
        from workers.core.service_preflight import _git_sha

        # Empty string, not a guess: the preflight then fails the check, which
        # is the correct outcome for a tree of unknown provenance.
        self.assertEqual(_git_sha(self.root), "")

    def test_a_corrupt_release_manifest_reports_nothing(self) -> None:
        from workers.core.service_preflight import _git_sha

        with open(os.path.join(self.root, "release.manifest.json"), "w", encoding="utf-8") as handle:
            handle.write("{truncated")
        self.assertEqual(_git_sha(self.root), "")

    def test_preflight_accepts_a_release_with_a_matching_manifest_sha(self) -> None:
        from workers.core.service_preflight import run_preflight
        from workers.core.service_manifest import build_manifest

        engine = os.path.join(self.root, "engine.plan")
        with open(engine, "wb") as handle:
            handle.write(b"engine")
        startup = os.path.join(self.root, "startup.json")
        with open(startup, "w", encoding="utf-8") as handle:
            json.dump(build_manifest(
                service_name="svc", repository_sha="c" * 40, engine_path=engine,
            ), handle)
        with open(os.path.join(self.root, "release.manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"source_git_sha": "c" * 40}, handle)
        report = run_preflight(
            manifest_path=startup, repo_root=self.root, expected_repo_sha="c" * 40,
            check_ports=False, import_tensorrt=False,
            machine_provider=lambda: "aarch64",
        )
        failed = report.to_dict()["failed_required_checks"]
        self.assertNotIn("repository_sha_match", failed)


class TestDeploymentState(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-state-")
        self.addCleanup(self._dir.cleanup)
        self.path = os.path.join(self._dir.name, "state", "deployment.json")

    def test_default_state_is_idle(self) -> None:
        self.assertEqual(DeploymentState(self.path).state, IDLE)

    def test_state_survives_reload(self) -> None:
        state = DeploymentState(self.path)
        state.transition(STAGED, "staged", candidate_release_id="relB")
        reloaded = DeploymentState(self.path)
        self.assertEqual(reloaded.state, STAGED)
        self.assertEqual(reloaded.candidate_release_id, "relB")

    def test_illegal_transition_is_refused(self) -> None:
        state = DeploymentState(self.path)
        with self.assertRaises(DeploymentStateError) as ctx:
            state.transition(CONFIRMED, "skipping the whole sequence")
        self.assertEqual(ctx.exception.classification, "illegal_transition")
        self.assertEqual(state.state, IDLE)

    def test_full_successful_sequence(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING, PROBATION, CONFIRMED):
            state.transition(target, "step")
        self.assertEqual(state.state, CONFIRMED)

    def test_authority_fails_closed_during_transition(self) -> None:
        state = DeploymentState(self.path)
        state.transition(STAGED, "s")
        self.assertFalse(state.authority_fail_closed)
        state.transition(VALIDATED, "v")
        self.assertFalse(state.authority_fail_closed)
        state.transition(ACTIVATING, "a")
        self.assertTrue(state.authority_fail_closed)
        state.transition(PROBATION, "p")
        self.assertTrue(state.authority_fail_closed)
        state.transition(CONFIRMED, "c")
        self.assertFalse(state.authority_fail_closed)

    def test_rolling_back_also_fails_closed(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING):
            state.transition(target, "step")
        state.transition(ROLLING_BACK, "rollback")
        self.assertTrue(state.authority_fail_closed)

    def test_corrupt_state_file_is_not_read_as_idle(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{truncated")
        state = DeploymentState(self.path)
        self.assertEqual(state.state, FAILED)
        self.assertTrue(state.payload.get("recovered_from_corrupt_state"))

    def test_state_file_is_never_partially_written(self) -> None:
        # Every save must leave a parsable document, because a reader may
        # arrive at any moment.
        state = DeploymentState(self.path)
        state.transition(STAGED, "s")
        for index in range(60):
            state.set(candidate_release_id="rel%d" % index)
            with open(self.path, "r", encoding="utf-8") as handle:
                json.load(handle)

    def test_history_is_bounded(self) -> None:
        state = DeploymentState(self.path, history_limit=5)
        for _ in range(20):
            state.transition(STAGED, "s")
            state.transition(IDLE, "i")
        self.assertLessEqual(len(state.payload["history"]), 5)

    def test_reboot_during_staging_discards_the_candidate(self) -> None:
        state = DeploymentState(self.path)
        state.transition(STAGED, "staged", candidate_release_id="relB")
        decision = DeploymentState(self.path).recovery_decision()
        self.assertEqual(decision["action"], "discard_candidate")

    def test_reboot_after_switch_before_confirm_rolls_back(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING):
            state.transition(target, "step", candidate_release_id="relB")
        state.set(switch_completed=True)
        decision = DeploymentState(self.path).recovery_decision()
        self.assertEqual(decision["action"], "rollback_to_last_known_good")

    def test_reboot_during_probation_rolls_back_by_default(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING, PROBATION):
            state.transition(target, "step", candidate_release_id="relB")
        self.assertEqual(
            DeploymentState(self.path).recovery_decision()["action"],
            "rollback_to_last_known_good",
        )

    def test_resume_policy_can_continue_probation(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING, PROBATION):
            state.transition(target, "step", candidate_release_id="relB")
        decision = DeploymentState(self.path).recovery_decision(policy="resume")
        self.assertEqual(decision["action"], "resume_probation")

    def test_interrupted_rollback_is_resumed(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING, ROLLING_BACK):
            state.transition(target, "step")
        self.assertEqual(
            DeploymentState(self.path).recovery_decision()["action"], "resume_rollback"
        )

    def test_confirmed_state_needs_no_recovery(self) -> None:
        state = DeploymentState(self.path)
        for target in (STAGED, VALIDATED, ACTIVATING, PROBATION, CONFIRMED):
            state.transition(target, "step")
        self.assertEqual(DeploymentState(self.path).recovery_decision()["action"], "none")

    def test_state_machine_is_described(self) -> None:
        described = describe_state_machine()
        self.assertIn(ACTIVATING, described["unconfirmed_states"])
        self.assertIn(PROBATION, described["fail_closed_states"])
        self.assertEqual(described["default_reboot_policy"], "rollback_to_last_known_good")


class TestPackagePayloadExclusions(unittest.TestCase):
    """Generated host state must not travel inside an immutable release."""

    def setUp(self) -> None:
        self.src = tempfile.mkdtemp(prefix="phase13g-src-")
        self.dst = tempfile.mkdtemp(prefix="phase13g-dst-")
        self.addCleanup(shutil.rmtree, self.src, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.dst, ignore_errors=True)

    def write(self, relative: str, content: str = "x") -> None:
        path = os.path.join(self.src, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def packaged(self) -> set:
        collect_payload(self.src, self.dst)
        found = set()
        for base, _dirs, files in os.walk(self.dst):
            for name in files:
                found.add(
                    os.path.relpath(os.path.join(base, name), self.dst).replace(os.sep, "/")
                )
        return found

    def test_the_generated_startup_manifest_is_not_packaged(self) -> None:
        """It pins an absolute engine path and the commit *it* was built for.

        A copy inside a release contradicts that release's own source_git_sha.
        The release manifest references it by path and hash instead.
        """

        self.write("config/phase13f_service_manifest.json", '{"repository_sha": "dabbbaba"}')
        self.write("config/keep_me.json", "{}")
        packaged = self.packaged()
        self.assertNotIn("config/phase13f_service_manifest.json", packaged)
        self.assertIn("config/keep_me.json", packaged)

    def test_a_release_manifest_is_not_packaged_inside_itself(self) -> None:
        """Its value includes the package's own hash."""

        self.write("config/release.manifest.json", "{}")
        self.assertNotIn("config/release.manifest.json", self.packaged())

    def test_ordinary_runtime_files_are_packaged(self) -> None:
        self.write("scripts/run_thing.py", "print(1)\n")
        self.write("workers/core/mod.py", "X = 1\n")
        packaged = self.packaged()
        self.assertIn("scripts/run_thing.py", packaged)
        self.assertIn("workers/core/mod.py", packaged)

    def test_engines_tests_and_caches_are_excluded(self) -> None:
        self.write("scripts/tests/test_thing.py", "pass\n")
        self.write("workers/__pycache__/mod.pyc", "junk")
        self.write("config/model.engine", "weights")
        self.write("config/.env", "SECRET=1")
        packaged = self.packaged()
        self.assertEqual(
            [name for name in packaged if "test" in name or name.endswith((".pyc", ".engine"))],
            [],
        )
        self.assertNotIn("config/.env", packaged)


class TestWorktreeProvenance(unittest.TestCase):
    """The packager's cleanliness rule, on real git repositories.

    The rule exists to guarantee the package matches ``source_git_sha``, so the
    tests are written against that guarantee: dirt that can reach a package must
    be refused, and dirt that cannot must not block a release. A rule that only
    refused would be trivially "safe" and useless, so both directions are
    asserted.
    """

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="phase13g-git-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._git("init", "--quiet")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Phase 13G Test")
        # One packaged tree and one unpackaged one, both tracked.
        self._write("workers/core/thing.py", "VALUE = 1\n")
        self._write("docs/notes.md", "notes\n")
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "base")

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ("git",) + args, cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
        )
        output = completed.stdout.decode("utf-8", "replace")
        if completed.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(args), output))
        return output

    def _write(self, relative: str, content: str) -> None:
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_committed_tree_is_clean(self) -> None:
        report = worktree_provenance(self.root)
        self.assertTrue(report["clean_for_packaging"])
        self.assertEqual(report["tracked_modifications"], [])
        self.assertEqual(report["untracked_in_package"], [])

    def test_untracked_outside_packaged_trees_does_not_block(self) -> None:
        """The Gate B case: a CTest leftover at the repo root.

        ``Testing/`` is not inside any packaged tree, so no byte of it can enter
        the tarball. Refusing here would block a release for a file the package
        does not contain.
        """

        self._write("Testing/Temporary/LastTest.log", "ctest output\n")
        report = worktree_provenance(self.root)
        self.assertTrue(report["clean_for_packaging"])
        self.assertIn("Testing/Temporary/LastTest.log", report["untracked_outside_package"])
        self.assertEqual(report["untracked_in_package"], [])

    def test_untracked_inside_packaged_tree_blocks(self) -> None:
        """This one really would ship: the packager copies whole trees."""

        self._write("workers/core/local_hack.py", "SECRET_TWEAK = True\n")
        report = worktree_provenance(self.root)
        self.assertFalse(report["clean_for_packaging"])
        self.assertIn("workers/core/local_hack.py", report["untracked_in_package"])

    def test_modified_tracked_file_blocks_even_outside_packaged_trees(self) -> None:
        """A modified tracked file means the commit no longer describes the tree."""

        self._write("docs/notes.md", "edited\n")
        report = worktree_provenance(self.root)
        self.assertFalse(report["clean_for_packaging"])
        self.assertEqual(
            [entry["path"] for entry in report["tracked_modifications"]], ["docs/notes.md"]
        )

    def test_modified_packaged_file_blocks(self) -> None:
        self._write("workers/core/thing.py", "VALUE = 999\n")
        report = worktree_provenance(self.root)
        self.assertFalse(report["clean_for_packaging"])
        self.assertTrue(report["tracked_modifications"])

    def test_staged_and_deleted_tracked_files_block(self) -> None:
        self._write("workers/core/staged.py", "X = 1\n")
        self._git("add", "workers/core/staged.py")
        os.unlink(os.path.join(self.root, "workers", "core", "thing.py"))
        report = worktree_provenance(self.root)
        self.assertFalse(report["clean_for_packaging"])
        paths = [entry["path"] for entry in report["tracked_modifications"]]
        self.assertIn("workers/core/staged.py", paths)
        self.assertIn("workers/core/thing.py", paths)

    def test_non_repository_reports_error_and_is_not_clean(self) -> None:
        """Absence of git is not cleanliness -- provenance is unverifiable."""

        outside = tempfile.mkdtemp(prefix="phase13g-nogit-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        report = worktree_provenance(outside)
        self.assertFalse(report["clean_for_packaging"])
        self.assertIn("error", report)


if __name__ == "__main__":
    unittest.main()
