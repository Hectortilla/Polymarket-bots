"""Provenance section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..files import PerformanceProvenanceField
from ..parsing import (
    optional_text,
    required_mapping,
    required_text,
    require_exact_keys,
)
from ..run import PerformanceRunKind, RunProvenance


@dataclass(frozen=True, slots=True)
class PerformanceProvenanceSummary:
    """Sanitized inputs that identify how a performance run was produced."""

    kind: PerformanceRunKind
    bot_spec: str
    configuration: Mapping[str, object]
    seed: int | None
    archive_sha256: str | None
    archive_schema_version: int | None
    archive_target_identity: str | None

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> PerformanceProvenanceSummary:
        """Decode provenance through the shared run-provenance contract."""
        require_exact_keys(payload, PerformanceProvenanceField, "provenance")
        seed = payload.get(PerformanceProvenanceField.SEED)
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise ValueError("performance provenance seed must be an integer or null")
        archive_schema_version = payload.get(
            PerformanceProvenanceField.ARCHIVE_SCHEMA_VERSION
        )
        if archive_schema_version is not None and (
            isinstance(archive_schema_version, bool)
            or not isinstance(archive_schema_version, int)
            or archive_schema_version <= 0
        ):
            raise ValueError(
                "performance provenance archive schema version must be positive or null"
            )
        try:
            provenance = RunProvenance(
                kind=PerformanceRunKind(
                    required_text(payload, PerformanceProvenanceField.KIND)
                ),
                bot_spec=required_text(
                    payload,
                    PerformanceProvenanceField.BOT_SPEC,
                ),
                configuration=required_mapping(
                    payload,
                    PerformanceProvenanceField.CONFIGURATION,
                ),
                seed=seed,
                archive_sha256=optional_text(
                    payload,
                    PerformanceProvenanceField.ARCHIVE_SHA256,
                ),
                archive_schema_version=archive_schema_version,
                archive_target_identity=optional_text(
                    payload,
                    PerformanceProvenanceField.ARCHIVE_TARGET_IDENTITY,
                ),
            )
        except ValueError as error:
            raise ValueError("performance summary provenance is invalid") from error
        return cls(
            kind=provenance.kind,
            bot_spec=provenance.bot_spec,
            configuration=provenance.configuration,
            seed=provenance.seed,
            archive_sha256=provenance.archive_sha256,
            archive_schema_version=provenance.archive_schema_version,
            archive_target_identity=provenance.archive_target_identity,
        )

    def to_dict(self) -> dict[str, object]:
        """Encode the stable provenance section."""
        return {
            PerformanceProvenanceField.KIND: self.kind.value,
            PerformanceProvenanceField.BOT_SPEC: self.bot_spec,
            PerformanceProvenanceField.CONFIGURATION: dict(self.configuration),
            PerformanceProvenanceField.SEED: self.seed,
            PerformanceProvenanceField.ARCHIVE_SHA256: self.archive_sha256,
            PerformanceProvenanceField.ARCHIVE_SCHEMA_VERSION: (
                self.archive_schema_version
            ),
            PerformanceProvenanceField.ARCHIVE_TARGET_IDENTITY: (
                self.archive_target_identity
            ),
        }
