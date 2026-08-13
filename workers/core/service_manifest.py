"""Phase 13F versioned startup manifest for the supervised Jetson service.

A service that restarts on its own needs a written statement of what it is
allowed to start with, because nobody is watching the moment it comes back.
The manifest is that statement: repository commit, engine file and its hash,
precision, protocol sizes, ports, and the paths it may write to.

Two rules shape the format:

* It is **versioned**. A manifest written for a different schema version is
  rejected rather than interpreted optimistically.
* It is **checked, not trusted**. Every hash in it is recomputed at startup
  against the file on disk, and a mismatch is a hard preflight failure. A
  manifest that merely records what was true once is a changelog, not a gate.

INT8 cannot be declared authoritative here. Phase 13D-MP-RECOVERY froze it as
``experimental_non_authoritative`` and this file is not the place to unfreeze
it, so the parser refuses such a manifest outright.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

MANIFEST_SCHEMA_VERSION = 1
AUTHORITATIVE_PRECISION = "fp16"
FROZEN_INT8_ROLE = "experimental_non_authoritative"
HASH_CHUNK_BYTES = 1024 * 1024


class ManifestError(ValueError):
    """Raised when a manifest is malformed, mis-versioned or unsafe."""

    def __init__(self, classification: str, message: str) -> None:
        super(ManifestError, self).__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


def sha256_file(path: str, *, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    """Stream a file through SHA-256 without reading it all into memory."""

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


class ServiceManifest:
    """Parsed, validated startup manifest."""

    REQUIRED_FIELDS = (
        "schema_version",
        "service_name",
        "repository_sha",
        "engine_path",
        "engine_sha256",
        "precision",
    )

    def __init__(self, payload: Dict[str, Any], *, source_path: str = "") -> None:
        self.payload = dict(payload)
        self.source_path = source_path
        self._validate()

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str) -> "ServiceManifest":
        if not os.path.isfile(path):
            raise ManifestError("manifest_missing", "no manifest at %s" % path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except ValueError as exc:
            raise ManifestError("manifest_unparsable", "%s: %s" % (path, exc))
        if not isinstance(payload, dict):
            raise ManifestError("manifest_unparsable", "manifest root must be an object")
        return cls(payload, source_path=path)

    def _validate(self) -> None:
        missing = [name for name in self.REQUIRED_FIELDS if name not in self.payload]
        if missing:
            raise ManifestError(
                "manifest_incomplete", "missing required fields: %s" % ", ".join(sorted(missing))
            )
        version = self.payload.get("schema_version")
        if version != MANIFEST_SCHEMA_VERSION:
            # Refuse rather than guess: a manifest from another schema may mean
            # something different by the same field names.
            raise ManifestError(
                "manifest_schema_mismatch",
                "schema_version %r is not the supported %d" % (version, MANIFEST_SCHEMA_VERSION),
            )
        precision = str(self.payload.get("precision", "")).lower()
        if precision != AUTHORITATIVE_PRECISION:
            raise ManifestError(
                "manifest_precision_forbidden",
                "precision %r may not hold command authority; only %r may"
                % (precision, AUTHORITATIVE_PRECISION),
            )
        # A manifest is not permitted to unfreeze INT8.
        int8_role = str(self.payload.get("int8_role", FROZEN_INT8_ROLE))
        if int8_role != FROZEN_INT8_ROLE:
            raise ManifestError(
                "manifest_int8_authority_forbidden",
                "int8_role %r contradicts the Phase 13D-MP-RECOVERY freeze" % int8_role,
            )
        if bool(self.payload.get("int8_authoritative", False)):
            raise ManifestError(
                "manifest_int8_authority_forbidden",
                "int8_authoritative must be false under the Phase 13D-MP-RECOVERY freeze",
            )
        sha = str(self.payload.get("engine_sha256", ""))
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha.lower()):
            raise ManifestError("manifest_hash_malformed", "engine_sha256 is not a SHA-256 digest")

    # ── accessors ───────────────────────────────────────────────────────────

    @property
    def schema_version(self) -> int:
        return int(self.payload["schema_version"])

    @property
    def service_name(self) -> str:
        return str(self.payload["service_name"])

    @property
    def repository_sha(self) -> str:
        return str(self.payload["repository_sha"])

    @property
    def engine_path(self) -> str:
        return str(self.payload["engine_path"])

    @property
    def engine_sha256(self) -> str:
        return str(self.payload["engine_sha256"]).lower()

    @property
    def precision(self) -> str:
        return str(self.payload["precision"]).lower()

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    @property
    def manifest_sha256(self) -> str:
        """Hash of the manifest's own canonical content."""

        return sha256_text(json.dumps(self.payload, sort_keys=True, separators=(",", ":")))

    # ── verification ────────────────────────────────────────────────────────

    def verify_engine(self) -> Dict[str, Any]:
        """Recompute the engine hash on disk and compare it to the manifest."""

        path = self.engine_path
        report = {
            "engine_path": path,
            "engine_present": os.path.isfile(path),
            "engine_sha256_expected": self.engine_sha256,
            "engine_sha256_observed": "",
            "engine_size_bytes": 0,
            "engine_hash_match": False,
        }  # type: Dict[str, Any]
        if not report["engine_present"]:
            report["classification"] = "engine_missing"
            return report
        try:
            report["engine_size_bytes"] = os.path.getsize(path)
            report["engine_sha256_observed"] = sha256_file(path)
        except OSError as exc:
            report["classification"] = "engine_unreadable"
            report["error"] = "%s: %s" % (type(exc).__name__, exc)
            return report
        report["engine_hash_match"] = (
            report["engine_sha256_observed"] == report["engine_sha256_expected"]
        )
        report["classification"] = "ok" if report["engine_hash_match"] else "engine_hash_mismatch"
        return report

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.payload)
        payload["manifest_sha256"] = self.manifest_sha256
        payload["manifest_source_path"] = self.source_path
        return payload


def build_manifest(
    *,
    service_name: str,
    repository_sha: str,
    engine_path: str,
    precision: str = AUTHORITATIVE_PRECISION,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose a manifest by hashing the engine that is actually on disk."""

    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "service_name": str(service_name),
        "repository_sha": str(repository_sha),
        "engine_path": str(engine_path),
        "engine_sha256": sha256_file(engine_path),
        "precision": str(precision).lower(),
        "int8_role": FROZEN_INT8_ROLE,
        "int8_authoritative": False,
    }  # type: Dict[str, Any]
    if extra:
        for key, value in extra.items():
            if key not in payload:
                payload[key] = value
    return payload


def describe_schema() -> Dict[str, Any]:
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "required_fields": list(ServiceManifest.REQUIRED_FIELDS),
        "authoritative_precision": AUTHORITATIVE_PRECISION,
        "int8_role": FROZEN_INT8_ROLE,
        "hashes_recomputed_at_startup": True,
    }
