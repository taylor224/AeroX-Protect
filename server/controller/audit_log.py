from datetime import datetime

from server.model import UTC
from server.model.audit_log import AuditLog


class AuditLogController:
    @classmethod
    def get_list(cls, page, items_per_page, action, q, date_from, date_to) -> tuple[int, list[dict]]:
        total, rows = AuditLog.get_list(
            page, items_per_page, action, q,
            cls._parse_epoch_ms(date_from), cls._parse_epoch_ms(date_to))
        return total, [r.to_dict() for r in rows]

    @staticmethod
    def _parse_epoch_ms(value) -> datetime | None:
        """Accept epoch-ms (int/str) from the API; return naive UTC datetime."""
        if value is None or value == '':
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
        except (ValueError, TypeError, OverflowError):
            return None
