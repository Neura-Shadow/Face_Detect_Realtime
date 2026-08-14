"""Phase 13G release manifest: what a candidate must prove before it may run.

A release is a claim — "this code, this engine, this protocol, on this kind of
machine". The manifest writes that claim down and the validator checks every
part of it against the machine actually in front of it. Nothing is trusted
because it is written down; hashes are recomputed and versions are compared to
what the target reports.

Scope, stated up front because it bounds what any of this means:

* SHA-256 **integrity** and **version compatibility** only.
* No signatures, no publisher identity, no Secure Boot, no anti-rollback
  security. A hash proves a file was not corrupted in transit; it proves
  nothing about who produced it. Anyone who can write the manifest can write
  the hash in it.

Version compatibility is deliberately asymmetric. Some fields must match
exactly because the wire format depends on them (protocol version, packet
sizes, CRC coverage). Others are floors — the target may have a newer CUDA than
the release was built against, but not an older one. Getting that distinction
wrong in either direction is how a compatibility check becomes theatre.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

RELEASE_MANIFEST_SCHEMA_VERSION = 1
HASH_CHUNK_BYTES = 1024 * 1024

#: Frozen Phase 13A/13B wire contract. A release that disagrees with any of
#: these cannot talk to the C Virtual Safety MCU or the PC, so a mismatch is
#: rejected rather than warned about.
FROZEN_PROTOCOL = {
    "protocol_version": 1,
    "command_packet_size": 64,
    "command_crc_coverage": "0..59",
    "jilf_version": 1,
    "jilf_header_size": 56,
    "jila_version": 1,
    "jila_packet_size": 48,
}

#: Every field a release manifest must carry.
REQUIRED_FIELDS = (
    "release_id",
    "source_git_sha",
    "created_at_utc",
    "package_sha256",
    "required_python",
    "required_arch",
    "required_jetpack",
    "required_l4t",
    "required_cuda",
    "required_tensorrt",
    "engine_path",
    "engine_sha256",
    "engine_manifest_sha256",
    "protocol_version",
    "command_packet_size",
    "command_crc_coverage",
    "jilf_version",
    "jilf_header_size",
    "jila_version",
    "jila_packet_size",
    "service_schema_version",
    "startup_manifest_version",
    "int8_authority_allowed",
)

#: A credential-shaped *assignment*: a secret-ish name given a **string
#: literal**. Requiring the literal is the whole point. ``self._api_key =
#: cfg.api_key`` moves a value that lives in the environment; ``token =
#: raw.strip().upper()`` is a parsed word. Neither ships a credential, and
#: flagging them made the scan refuse three ordinary source files during
#: Gate B -- including ``api_key=_env("VLM_API_KEY", "optional")``, which is
#: precisely the pattern we want people to use.
SECRET_NAME_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|private[_-]?key"
    r"|access[_-]?key|auth[_-]?token|client[_-]?secret)\b"
    r"[^\n'\"]{0,40}?[:=][^\n'\"]{0,24}?"
    r"(['\"])(?P<value>[^'\"\n]{0,256})\1"
)

#: Literals that are credentials whatever they are called. These are
#: name-independent, so they still catch ``FOO = \"sk-...\"`` -- a real gap in
#: name-based matching, and the reason relaxing the name rule is not a net
#: loosening.
CREDENTIAL_LITERAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
)

#: Below this, a literal is too short to be a usable credential.
MIN_SECRET_VALUE_LEN = 12

#: Values that name the absence of a secret rather than one.
PLACEHOLDER_SECRET_VALUES = frozenset({
    "", "optional", "none", "null", "unset", "disabled", "todo", "changeme",
    "change-me", "replace-me", "replaceme", "placeholder", "redacted",
    "example", "dummy", "fake", "test", "your-api-key", "your_api_key",
    "yourkeyhere", "xxx", "xxxx", "notset", "not-set", "n/a",
})

#: ``api_key=_env("VLM_API_KEY", ...)`` names a variable; it is not its value.
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: Interpolation markers mean the real value arrives from somewhere else.
_TEMPLATE_MARKERS = ("{", "}", "<", ">", "$", "%s", "...")

#: Files that may never appear inside a release package.
FORBIDDEN_PACKAGE_NAMES = (
    ".env",
    "id_rsa",
    "id_ed25519",
    ".netrc",
    "credentials.json",
)


class ManifestError(ValueError):
    def __init__(self, classification: str, message: str) -> None:
        super(ManifestError, self).__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


def sha256_file(path: str, *, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_version(text: str) -> Tuple[int, ...]:
    """Numeric version tuple, ignoring any trailing non-numeric parts.

    ``"8.5.2.2"`` -> ``(8, 5, 2, 2)``; ``"35.5.0"`` -> ``(35, 5, 0)``. Anything
    unparsable yields an empty tuple, which compares as "unknown" rather than
    as zero — a missing version must not silently satisfy a floor.
    """

    parts = []  # type: List[int]
    for chunk in re.split(r"[.\-_+]", str(text).strip()):
        if chunk.isdigit():
            parts.append(int(chunk))
        elif parts:
            break
    return tuple(parts)


class CompatibilityCheck:
    """One compatibility observation, with what it saw and what it wanted."""

    __slots__ = ("name", "passed", "required", "kind", "expected", "observed", "detail")

    def __init__(
        self,
        name: str,
        passed: bool,
        *,
        kind: str = "exact",
        expected: Any = None,
        observed: Any = None,
        required: bool = True,
        detail: str = "",
    ) -> None:
        self.name = name
        self.passed = bool(passed)
        self.kind = kind
        self.expected = expected
        self.observed = observed
        self.required = bool(required)
        self.detail = detail

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "kind": self.kind,
            "required": self.required,
            "expected": self.expected,
            "observed": self.observed,
            "detail": self.detail,
        }


class CompatibilityReport:
    def __init__(self, checks: List[CompatibilityCheck]) -> None:
        self.checks = list(checks)

    @property
    def failures(self) -> List[CompatibilityCheck]:
        return [item for item in self.checks if item.required and not item.passed]

    @property
    def compatible(self) -> bool:
        return not self.failures

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_compatible": self.compatible,
            "check_count": len(self.checks),
            "failed_checks": [item.name for item in self.failures],
            "checks": [item.to_dict() for item in self.checks],
        }


class ReleaseManifest:
    """A parsed, structurally valid release manifest."""

    def __init__(self, payload: Dict[str, Any], *, source_path: str = "") -> None:
        self.payload = dict(payload)
        self.source_path = source_path
        self._validate_structure()

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str) -> "ReleaseManifest":
        if not os.path.isfile(path):
            raise ManifestError("manifest_missing", "no release manifest at %s" % path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except ValueError as exc:
            raise ManifestError("manifest_unparsable", "%s: %s" % (path, exc))
        if not isinstance(payload, dict):
            raise ManifestError("manifest_unparsable", "manifest root must be an object")
        return cls(payload, source_path=path)

    def _validate_structure(self) -> None:
        missing = [name for name in REQUIRED_FIELDS if name not in self.payload]
        if missing:
            raise ManifestError(
                "manifest_incomplete",
                "missing required fields: %s" % ", ".join(sorted(missing)),
            )
        version = self.payload.get("schema_version", RELEASE_MANIFEST_SCHEMA_VERSION)
        if version != RELEASE_MANIFEST_SCHEMA_VERSION:
            raise ManifestError(
                "manifest_schema_mismatch",
                "schema_version %r is not the supported %d"
                % (version, RELEASE_MANIFEST_SCHEMA_VERSION),
            )
        # INT8 authority cannot be granted by a release. The Phase
        # 13D-MP-RECOVERY freeze is not a per-release decision.
        if bool(self.payload.get("int8_authority_allowed", False)):
            raise ManifestError(
                "manifest_int8_authority_forbidden",
                "int8_authority_allowed must be false under the Phase 13D-MP-RECOVERY freeze",
            )
        for field in ("package_sha256", "engine_sha256", "engine_manifest_sha256"):
            value = str(self.payload.get(field, ""))
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
                raise ManifestError(
                    "manifest_hash_malformed", "%s is not a SHA-256 digest" % field
                )
        release_id = str(self.payload["release_id"])
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", release_id):
            # The release id becomes a directory name and a symlink target.
            raise ManifestError(
                "manifest_release_id_invalid",
                "release_id %r is not a safe directory name" % release_id,
            )

    # ── accessors ───────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    @property
    def release_id(self) -> str:
        return str(self.payload["release_id"])

    @property
    def source_git_sha(self) -> str:
        return str(self.payload["source_git_sha"])

    @property
    def package_sha256(self) -> str:
        return str(self.payload["package_sha256"]).lower()

    @property
    def engine_path(self) -> str:
        return str(self.payload["engine_path"])

    @property
    def engine_sha256(self) -> str:
        return str(self.payload["engine_sha256"]).lower()

    @property
    def manifest_sha256(self) -> str:
        return sha256_text(canonical_json(self.payload))

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.payload)
        payload["manifest_sha256"] = self.manifest_sha256
        payload["manifest_source_path"] = self.source_path
        return payload


def target_facts(
    *,
    machine_provider: Optional[Callable[[], str]] = None,
    python_version: str = "",
    tegra_release_path: str = "/etc/nv_tegra_release",
    import_tensorrt: bool = True,
) -> Dict[str, Any]:
    """What the machine in front of us actually is."""

    facts = {
        "arch": (machine_provider or platform.machine)(),
        "python": python_version or platform.python_version(),
        "l4t": "",
        "jetpack": "",
        "cuda": "",
        "tensorrt": "",
    }  # type: Dict[str, Any]

    try:
        with open(tegra_release_path, "r", encoding="utf-8") as handle:
            line = handle.readline().strip()
        facts["tegra_release_line"] = line
        # "# R35 (release), REVISION: 5.0, ..." -> L4T 35.5.0
        match = re.search(r"R(\d+).*REVISION:\s*([0-9.]+)", line)
        if match:
            revision = match.group(2).strip().rstrip(".")
            facts["l4t"] = "%s.%s" % (match.group(1), revision)
            facts["jetpack"] = JETPACK_BY_L4T.get(facts["l4t"], "")
    except OSError:
        facts["tegra_release_line"] = ""

    facts["cuda"] = _cuda_version_text()
    if import_tensorrt:
        try:
            import tensorrt  # type: ignore[import-not-found]

            facts["tensorrt"] = str(tensorrt.__version__)
        except Exception:
            facts["tensorrt"] = ""
    return facts


#: L4T release to the JetPack version that shipped it. Only the entries this
#: project has actually run on are listed; an unknown L4T yields an empty
#: JetPack, which is reported rather than guessed.
JETPACK_BY_L4T = {
    "35.5.0": "5.1.3",
    "35.4.1": "5.1.2",
    "35.3.1": "5.1.1",
    "35.2.1": "5.1",
}


def _cuda_version_text() -> str:
    import ctypes

    for name in ("libcudart.so", "libcudart.so.11.0", "libcudart.so.10.2"):
        try:
            library = ctypes.CDLL(name)
        except OSError:
            continue
        try:
            value = ctypes.c_int()
            if library.cudaRuntimeGetVersion(ctypes.byref(value)) == 0:
                raw = int(value.value)
                return "%d.%d" % (raw // 1000, (raw % 1000) // 10)
        except AttributeError:
            continue
    return ""


def check_compatibility(
    manifest: ReleaseManifest,
    *,
    facts: Optional[Dict[str, Any]] = None,
    package_root: str = "",
    verify_package_hash: bool = True,
    package_path: str = "",
    expected_source_sha: str = "",
    runtime_dirs: Optional[List[str]] = None,
    engine_manifest_path: str = "",
) -> CompatibilityReport:
    """Check a candidate against this machine. Any failure blocks activation."""

    facts = facts or target_facts()
    checks = []  # type: List[CompatibilityCheck]

    # ── architecture and interpreter ────────────────────────────────────────
    checks.append(CompatibilityCheck(
        "arch_matches", facts.get("arch") == manifest.get("required_arch"),
        expected=manifest.get("required_arch"), observed=facts.get("arch"),
        detail="a release built for another architecture cannot run here",
    ))
    required_python = str(manifest.get("required_python", ""))
    observed_python = str(facts.get("python", ""))
    # Python is checked on major.minor: the interpreter ABI is what matters,
    # and pinning the patch level would reject a security update.
    checks.append(CompatibilityCheck(
        "python_matches", parse_version(observed_python)[:2] == parse_version(required_python)[:2],
        kind="major_minor", expected=required_python, observed=observed_python,
    ))

    # ── platform stack: floors, not equality ────────────────────────────────
    for name, key, manifest_key in (
        ("l4t_at_least", "l4t", "required_l4t"),
        ("cuda_at_least", "cuda", "required_cuda"),
        ("tensorrt_at_least", "tensorrt", "required_tensorrt"),
    ):
        required = str(manifest.get(manifest_key, ""))
        observed = str(facts.get(key, ""))
        required_tuple = parse_version(required)
        observed_tuple = parse_version(observed)
        # An unknown observed version fails: "we could not tell" is not
        # "new enough".
        passed = bool(observed_tuple) and bool(required_tuple) and observed_tuple >= required_tuple
        checks.append(CompatibilityCheck(
            name, passed, kind="minimum", expected=required, observed=observed,
            detail="target may be newer than the release requires, never older",
        ))

    # TensorRT additionally may not cross a major version: the Phase 13C/13D
    # binding API is TensorRT 8 only.
    required_trt = parse_version(str(manifest.get("required_tensorrt", "")))
    observed_trt = parse_version(str(facts.get("tensorrt", "")))
    checks.append(CompatibilityCheck(
        "tensorrt_major_matches",
        bool(required_trt) and bool(observed_trt) and required_trt[0] == observed_trt[0],
        expected=manifest.get("required_tensorrt"), observed=facts.get("tensorrt"),
        detail="the TensorRT 8 binding API is not source-compatible with 10",
    ))

    jetpack_required = str(manifest.get("required_jetpack", ""))
    jetpack_observed = str(facts.get("jetpack", ""))
    checks.append(CompatibilityCheck(
        "jetpack_at_least",
        bool(parse_version(jetpack_observed)) and bool(parse_version(jetpack_required))
        and parse_version(jetpack_observed) >= parse_version(jetpack_required),
        kind="minimum", expected=jetpack_required, observed=jetpack_observed,
        detail="derived from the L4T release on the target",
    ))

    # ── frozen wire contract: exact, no tolerance ───────────────────────────
    for field, expected in FROZEN_PROTOCOL.items():
        observed = manifest.get(field)
        checks.append(CompatibilityCheck(
            "protocol_%s" % field, observed == expected,
            expected=expected, observed=observed,
            detail="frozen by Phase 13A/13B; a mismatch cannot reach the MCU",
        ))

    # ── source identity ─────────────────────────────────────────────────────
    if expected_source_sha:
        checks.append(CompatibilityCheck(
            "source_git_sha_matches", manifest.source_git_sha == expected_source_sha,
            expected=expected_source_sha, observed=manifest.source_git_sha,
        ))

    # ── package integrity ───────────────────────────────────────────────────
    if verify_package_hash and package_path:
        if os.path.isfile(package_path):
            observed_hash = sha256_file(package_path)
            checks.append(CompatibilityCheck(
                "package_sha256_matches", observed_hash == manifest.package_sha256,
                expected=manifest.package_sha256, observed=observed_hash,
                detail="integrity only; this is not a signature",
            ))
        else:
            checks.append(CompatibilityCheck(
                "package_sha256_matches", False,
                expected=manifest.package_sha256, observed=None,
                detail="package file not found at %s" % package_path,
            ))

    # ── engine, referenced not copied ───────────────────────────────────────
    engine_path = manifest.engine_path
    engine_present = os.path.isfile(engine_path)
    checks.append(CompatibilityCheck(
        "engine_present", engine_present, expected=engine_path, observed=engine_present,
        detail="engines are referenced by validated path, never packaged",
    ))
    if engine_present:
        observed_engine = sha256_file(engine_path)
        checks.append(CompatibilityCheck(
            "engine_sha256_matches", observed_engine == manifest.engine_sha256,
            expected=manifest.engine_sha256, observed=observed_engine,
        ))
    else:
        checks.append(CompatibilityCheck(
            "engine_sha256_matches", False,
            expected=manifest.engine_sha256, observed=None,
        ))

    if engine_manifest_path:
        if os.path.isfile(engine_manifest_path):
            observed_em = sha256_file(engine_manifest_path)
            checks.append(CompatibilityCheck(
                "engine_manifest_sha256_matches",
                observed_em == str(manifest.get("engine_manifest_sha256", "")).lower(),
                expected=manifest.get("engine_manifest_sha256"), observed=observed_em,
            ))
        else:
            checks.append(CompatibilityCheck(
                "engine_manifest_sha256_matches", False,
                expected=manifest.get("engine_manifest_sha256"), observed=None,
                detail="startup manifest not found at %s" % engine_manifest_path,
            ))

    # ── authority policy ────────────────────────────────────────────────────
    checks.append(CompatibilityCheck(
        "int8_authority_forbidden", not bool(manifest.get("int8_authority_allowed", False)),
        expected=False, observed=manifest.get("int8_authority_allowed"),
        detail="Phase 13D-MP-RECOVERY freeze",
    ))

    # ── writable runtime directories ────────────────────────────────────────
    for directory in (runtime_dirs or []):
        checks.append(CompatibilityCheck(
            "runtime_dir_writable_%s" % os.path.basename(directory.rstrip("/")) or "root",
            _writable(directory), expected=directory, observed=_writable(directory),
        ))

    # ── no secrets in the package ───────────────────────────────────────────
    if package_root:
        offenders = scan_for_secrets(package_root)
        checks.append(CompatibilityCheck(
            "package_contains_no_secrets", not offenders,
            expected=[], observed=offenders[:10],
            detail="a release is copied and kept; credentials must never be in one",
        ))

    return CompatibilityReport(checks)


def _writable(path: str) -> bool:
    import tempfile

    try:
        os.makedirs(path, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=path, prefix=".phase13g-", delete=True)
        handle.close()
        return True
    except (OSError, ValueError):
        return False


def looks_like_secret_value(value: str) -> bool:
    """Whether a string literal could actually be a credential.

    Deliberately conservative about what counts as a secret, because the cost
    of a false positive here is a release that cannot be built at all. A short
    word, a placeholder, an environment-variable name or a template hole are
    none of them usable credentials.
    """

    stripped = value.strip()
    if len(stripped) < MIN_SECRET_VALUE_LEN:
        return False
    if stripped.lower() in PLACEHOLDER_SECRET_VALUES:
        return False
    if _ENV_NAME_RE.match(stripped):
        return False
    if any(marker in stripped for marker in _TEMPLATE_MARKERS):
        return False
    return True


def scan_for_secrets(root: str, *, max_bytes: int = 256 * 1024) -> List[str]:
    """Names and contents that look like credentials.

    Best-effort, not proof, and the limit is worth stating plainly: a
    credential assigned to an innocuously named constant is caught only if the
    literal itself matches ``CREDENTIAL_LITERAL_PATTERNS``. This scan reduces
    the chance of shipping a secret; it does not establish that none shipped.
    """

    offenders = []  # type: List[str]
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            relative = os.path.relpath(path, root)
            if name in FORBIDDEN_PACKAGE_NAMES or name.endswith(".pem"):
                offenders.append(relative)
                continue
            if name.endswith((".env",)):
                offenders.append(relative)
                continue
            # Only sniff small text files; a scan is not a guarantee, and
            # reading a whole release into memory to prove a negative is worse
            # than the risk it addresses.
            try:
                if os.path.getsize(path) > max_bytes:
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    text = handle.read()
            except OSError:
                continue
            # A credential literal is damning wherever it appears -- an example
            # file carrying a real key is the worst case, not an exempt one.
            if any(pattern.search(text) for pattern in CREDENTIAL_LITERAL_PATTERNS):
                offenders.append(relative)
                continue

            # Name-based matching is heuristic, so files whose job is to
            # document variable names are exempt from it (but not from the
            # literal patterns above).
            if relative.endswith((".example", ".template", ".md")):
                continue
            for match in SECRET_NAME_ASSIGNMENT.finditer(text):
                if looks_like_secret_value(match.group("value")):
                    offenders.append(relative)
                    break
    return sorted(set(offenders))


def build_release_manifest(
    *,
    release_id: str,
    source_git_sha: str,
    created_at_utc: str,
    package_sha256: str,
    engine_path: str,
    engine_sha256: str,
    engine_manifest_sha256: str,
    facts: Optional[Dict[str, Any]] = None,
    service_schema_version: int = 1,
    startup_manifest_version: int = 1,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose a manifest describing what this release requires."""

    facts = facts or target_facts()
    payload = {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_id": release_id,
        "source_git_sha": source_git_sha,
        "created_at_utc": created_at_utc,
        "package_sha256": package_sha256,
        "required_python": ".".join(str(part) for part in parse_version(facts.get("python", ""))[:2]),
        "required_arch": facts.get("arch", ""),
        "required_jetpack": facts.get("jetpack", ""),
        "required_l4t": facts.get("l4t", ""),
        "required_cuda": facts.get("cuda", ""),
        "required_tensorrt": facts.get("tensorrt", ""),
        "engine_path": engine_path,
        "engine_sha256": engine_sha256,
        "engine_manifest_sha256": engine_manifest_sha256,
        "service_schema_version": int(service_schema_version),
        "startup_manifest_version": int(startup_manifest_version),
        "int8_authority_allowed": False,
        # Recorded so the boundary of this phase travels with the artifact.
        "integrity_only": True,
        "signed": False,
        "secure_boot": False,
        "bootloader_ab": False,
        "anti_rollback_security": False,
    }  # type: Dict[str, Any]
    payload.update(FROZEN_PROTOCOL)
    if extra:
        for key, value in extra.items():
            payload.setdefault(key, value)
    return payload


def describe_schema() -> Dict[str, Any]:
    return {
        "release_manifest_schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "required_fields": list(REQUIRED_FIELDS),
        "frozen_protocol": dict(FROZEN_PROTOCOL),
        "exact_match_fields": sorted(FROZEN_PROTOCOL) + ["required_arch"],
        "minimum_version_fields": [
            "required_l4t", "required_cuda", "required_tensorrt", "required_jetpack",
        ],
        "integrity_only": True,
        "signed": False,
        "secure_boot": False,
        "anti_rollback_security": False,
    }
