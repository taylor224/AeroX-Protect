"""Pagination contract (SSOT — all list APIs share this).

Query params: `page` (1-based), `items_per_page`, `sort`, `order` (asc|desc), `q`.
Response: ``{"items": [...], "pagination": {page, items_per_page, total, total_pages}}``.
"""
from server.util.tool import safe_int

DEFAULT_ITEMS_PER_PAGE = 20
MAX_ITEMS_PER_PAGE = 200


def parse_pagination(args) -> dict:
    """Parse Flask ``request.args`` into normalized pagination params."""
    page = max(1, safe_int(args.get('page'), 1))
    items_per_page = safe_int(args.get('items_per_page'), DEFAULT_ITEMS_PER_PAGE)
    items_per_page = max(1, min(items_per_page, MAX_ITEMS_PER_PAGE))

    order = (args.get('order') or 'desc').lower()
    if order not in ('asc', 'desc'):
        order = 'desc'

    return {
        'page': page,
        'items_per_page': items_per_page,
        'sort': args.get('sort') or None,
        'order': order,
        'q': (args.get('q') or '').strip() or None,
    }


def build_page(items: list, total: int, page: int, items_per_page: int) -> dict:
    """Build the standard ``{items, pagination}`` payload."""
    total_pages = (total + items_per_page - 1) // items_per_page if items_per_page else 0
    return {
        'items': items,
        'pagination': {
            'page': page,
            'items_per_page': items_per_page,
            'total': total,
            'total_pages': total_pages,
        },
    }
