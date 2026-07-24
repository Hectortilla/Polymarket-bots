"""Official SDK pagination-handle contracts."""

SDK_PAGE_ITEMS_ATTRIBUTE = "items"


def sdk_page_items(
    page: object,
    *,
    malformed_error: Exception,
) -> tuple[object, ...]:
    items = getattr(page, SDK_PAGE_ITEMS_ATTRIBUTE, None)
    if not isinstance(items, (list, tuple)):
        raise malformed_error
    return tuple(items)
