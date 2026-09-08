"""Bounded durable-event read policy."""


MIN_EVENT_PAGE_LIMIT = 1
DEFAULT_EVENT_PAGE_LIMIT = 100
MAX_EVENT_PAGE_LIMIT = 500
NEXT_EVENT_PAGE_CURSOR_EVENT_INDEX = 0


def next_event_page_cursor(
    ascending_event_ids: tuple[int, ...],
    *,
    has_more: bool,
) -> int | None:
    if not has_more or not ascending_event_ids:
        return None
    return ascending_event_ids[NEXT_EVENT_PAGE_CURSOR_EVENT_INDEX]
