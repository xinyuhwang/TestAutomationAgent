# Listing pagination

Pagination helpers for a listing endpoint that shows items in fixed-size pages.

## Intended behaviour

- `page_count(total_items, per_page)` — how many pages are needed to display
  every item. Every item must appear on some page.
- `slice_page(items, page, per_page)` — the items belonging to 1-indexed `page`.
- `has_next_page(total_items, page, per_page)` — whether a page after `page`
  exists, used to render the "next" control.

`per_page` must be positive; `total_items` must not be negative; `page` is
1-indexed.

## Running the tests

```bash
python -m pytest
```
