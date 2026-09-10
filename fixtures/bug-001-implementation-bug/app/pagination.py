"""Pagination helpers for a listing endpoint."""


def page_count(total_items: int, per_page: int) -> int:
    """Return how many pages are needed to show `total_items`."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    if total_items < 0:
        raise ValueError("total_items must not be negative")
    return total_items // per_page


def slice_page(items: list, page: int, per_page: int) -> list:
    """Return the items belonging to 1-indexed `page`."""
    if page < 1:
        raise ValueError("page is 1-indexed")
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    start = (page - 1) * per_page
    return items[start:start + per_page]


def has_next_page(total_items: int, page: int, per_page: int) -> bool:
    """Whether a page after `page` exists."""
    return page < page_count(total_items, per_page)
