"""Capture-anomaly contracts persisted with interrupted recordings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
)

from .market import MarketIdentity
from .payloads import (
    RECORDED_PAYLOAD_TYPES,
    RecordedPayload,
    validate_event_identity,
)
from .validation import (
    normalize_optional_text_fields,
    normalize_required_text_fields,
    validate_decimal,
    validate_nonnegative_int,
)


class CaptureFailureKind(StrEnum):
    SPLIT_REVISION_MISMATCH = "split_revision_mismatch"
    SPLIT_REVISION_TIMEOUT = "split_revision_timeout"
    SPLIT_REVISION_END = "split_revision_end"
    SDK_HANDLE_DROP = "sdk_handle_drop"


class CaptureFragmentRole(StrEnum):
    INITIAL = "initial"
    MATCHING_CONTINUATION = "matching_continuation"
    MISMATCHING_CONTINUATION = "mismatching_continuation"


@dataclass(frozen=True, slots=True)
class RevisionFingerprint:
    condition_id: str
    source_timestamp_ms: int
    source_hashes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("condition_id",))
        validate_nonnegative_int(
            self.source_timestamp_ms,
            "revision source timestamp",
        )
        if not isinstance(self.source_hashes, tuple) or not self.source_hashes:
            raise ValueError("revision source hashes must be a non-empty tuple")
        normalized_hashes: list[tuple[str, str]] = []
        for value in self.source_hashes:
            if not isinstance(value, tuple) or len(value) != 2:
                raise ValueError("revision source hash entries must be pairs")
            token_id, source_hash = value
            if not isinstance(token_id, str) or not token_id.strip():
                raise ValueError("revision source hash token ID must not be empty")
            if not isinstance(source_hash, str) or not source_hash.strip():
                raise ValueError("revision source hash must not be empty")
            normalized_hashes.append((token_id.strip(), source_hash.strip()))
        normalized_hashes.sort()
        if len({token_id for token_id, _ in normalized_hashes}) != len(
            normalized_hashes
        ):
            raise ValueError("revision source hashes contain duplicate token IDs")
        object.__setattr__(self, "source_hashes", tuple(normalized_hashes))

    def accepts_continuation(
        self,
        actual: RevisionFingerprint | None,
        *,
        known_source_hashes: dict[str, str],
    ) -> bool:
        if (
            actual is None
            or actual.condition_id != self.condition_id
            or actual.source_timestamp_ms != self.source_timestamp_ms
        ):
            return False
        actual_hashes = dict(actual.source_hashes)
        required_hashes_match = all(
            actual_hashes.get(token_id) == source_hash
            for token_id, source_hash in self.source_hashes
        )
        known_hashes_match = all(
            known_source_hashes.get(token_id, source_hash) == source_hash
            for token_id, source_hash in actual.source_hashes
        )
        return required_hashes_match and known_hashes_match


@dataclass(frozen=True, slots=True)
class CaptureAnomalyFragment:
    role: CaptureFragmentRole
    source_timestamp_ms: int | None
    identity: MarketIdentity
    payload: RecordedPayload

    def __post_init__(self) -> None:
        if not isinstance(self.role, CaptureFragmentRole):
            raise ValueError("capture anomaly fragment role is invalid")
        if self.source_timestamp_ms is not None:
            validate_nonnegative_int(
                self.source_timestamp_ms,
                "capture fragment source timestamp",
            )
        if not isinstance(self.identity, MarketIdentity):
            raise ValueError("capture anomaly fragment identity is invalid")
        if not isinstance(self.payload, RECORDED_PAYLOAD_TYPES):
            raise ValueError("capture anomaly fragment payload type is unsupported")
        validate_event_identity(self.identity, self.payload)


@dataclass(frozen=True, slots=True)
class CaptureBookDiagnostics:
    token_id: str
    projected_best_bid: Decimal | None
    projected_best_ask: Decimal | None
    advertised_best_bid: Decimal | None
    advertised_best_ask: Decimal | None

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("token_id",))
        for name in (
            "projected_best_bid",
            "projected_best_ask",
            "advertised_best_bid",
            "advertised_best_ask",
        ):
            value = getattr(self, name)
            if value is not None:
                validate_decimal(
                    value,
                    name.replace("_", " "),
                    minimum=OUTCOME_PRICE_FLOOR,
                    maximum=OUTCOME_PRICE_CEILING,
                )


@dataclass(frozen=True, slots=True)
class CaptureAnomalyPayload:
    failure_kind: CaptureFailureKind
    expected_fingerprint: RevisionFingerprint | None
    actual_fingerprint: RevisionFingerprint | None
    fragments: tuple[CaptureAnomalyFragment, ...]
    book_diagnostics: tuple[CaptureBookDiagnostics, ...]
    dropped_count_before: int
    dropped_count_after: int
    elapsed_ms: int
    details: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.failure_kind, CaptureFailureKind):
            raise ValueError("capture anomaly failure kind is invalid")
        for name in ("expected_fingerprint", "actual_fingerprint"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, RevisionFingerprint):
                raise ValueError(f"capture anomaly {name.replace('_', ' ')} is invalid")
        if (
            not isinstance(self.fragments, tuple)
            or not self.fragments
            or not all(
                isinstance(fragment, CaptureAnomalyFragment)
                for fragment in self.fragments
            )
        ):
            raise ValueError("capture anomaly requires normalized fragments")
        if self.fragments[0].role is not CaptureFragmentRole.INITIAL:
            raise ValueError("capture anomaly must begin with its initial fragment")
        remaining_roles = tuple(fragment.role for fragment in self.fragments[1:])
        if CaptureFragmentRole.INITIAL in remaining_roles:
            raise ValueError("capture anomaly can contain only one initial fragment")
        mismatch_indexes = tuple(
            index
            for index, role in enumerate(remaining_roles, start=1)
            if role is CaptureFragmentRole.MISMATCHING_CONTINUATION
        )
        if len(mismatch_indexes) > 1 or (
            mismatch_indexes and mismatch_indexes[0] != len(self.fragments) - 1
        ):
            raise ValueError("capture anomaly mismatching continuation must be last")
        if not isinstance(self.book_diagnostics, tuple) or not all(
            isinstance(diagnostics, CaptureBookDiagnostics)
            for diagnostics in self.book_diagnostics
        ):
            raise ValueError("capture anomaly book diagnostics are invalid")
        diagnostic_tokens = tuple(
            diagnostics.token_id for diagnostics in self.book_diagnostics
        )
        if len(diagnostic_tokens) != len(set(diagnostic_tokens)):
            raise ValueError("capture anomaly has duplicate book diagnostics")
        object.__setattr__(
            self,
            "book_diagnostics",
            tuple(sorted(self.book_diagnostics, key=lambda value: value.token_id)),
        )
        validate_nonnegative_int(
            self.dropped_count_before,
            "capture anomaly initial drop count",
        )
        validate_nonnegative_int(
            self.dropped_count_after,
            "capture anomaly final drop count",
        )
        if self.dropped_count_after < self.dropped_count_before:
            raise ValueError("capture anomaly drop count cannot decrease")
        validate_nonnegative_int(self.elapsed_ms, "capture anomaly elapsed time")
        normalize_optional_text_fields(self, ("details",))

    @property
    def initial_identity(self) -> MarketIdentity:
        return self.fragments[0].identity

    def matches_index_identity(self, identity: MarketIdentity) -> bool:
        initial = self.initial_identity
        return (
            initial.condition_id == identity.condition_id
            and initial.market_slug == identity.market_slug
            and (identity.token_id is None or identity.token_id == initial.token_id)
        )
