"""Stable failures raised by recording archive readers and writers."""


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
    pass


class ArchiveClosedError(RecordingArchiveError):
    pass


class CaptureAnomalyJournalUnavailableError(RecordingArchiveError):
    """The selected session predates capture-anomaly diagnostics."""
