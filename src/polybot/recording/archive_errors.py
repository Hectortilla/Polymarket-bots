"""Stable failures raised by recording archive readers and writers."""

from __future__ import annotations


class RecordingArchiveError(RuntimeError):
    """Base error for recording persistence failures."""


class ArchiveExistsError(RecordingArchiveError):
    pass


class ArchiveLockedError(RecordingArchiveError):
    pass


class ArchiveFormatError(RecordingArchiveError):
    pass


class ArchiveIntegrityError(RecordingArchiveError):
    pass


class ArchiveCoverageError(RecordingArchiveError):
    @classmethod
    def for_gap_ids(cls, gap_ids: tuple[int, ...]) -> ArchiveCoverageError:
        ordered_gap_ids = tuple(sorted(gap_ids))
        prefix = "selected recording interval crosses known coverage gaps"
        if len(ordered_gap_ids) <= 20:
            listed_ids = ", ".join(str(gap_id) for gap_id in ordered_gap_ids)
            return cls(f"{prefix}: {listed_ids}")

        ranges: list[tuple[int, int]] = []
        range_start = range_end = ordered_gap_ids[0]
        for gap_id in ordered_gap_ids[1:]:
            if gap_id == range_end + 1:
                range_end = gap_id
                continue
            ranges.append((range_start, range_end))
            range_start = range_end = gap_id
        ranges.append((range_start, range_end))

        displayed_ranges = ranges[:8]
        summary = ", ".join(
            str(start) if start == end else f"{start}-{end}"
            for start, end in displayed_ranges
        )
        if len(ranges) > len(displayed_ranges):
            summary = f"{summary}, ..."
        return cls(
            f"{prefix}: {len(ordered_gap_ids):,} gaps (IDs {summary})"
        )


class ArchiveClosedError(RecordingArchiveError):
    pass


class CaptureAnomalyJournalUnavailableError(RecordingArchiveError):
    """The selected session predates capture-anomaly diagnostics."""
