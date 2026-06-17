"""Snowflake ID generator (application-side BIGINT PK).

Layout (63 bits, fits signed & unsigned BIGINT):
    | 41 bits ms since AXP_EPOCH | 10 bits instance | 12 bits sequence |

`instance` = ``config.SNOWFLAKE_INSTANCE`` (MUST differ per process:
backend=1, worker=2, ...). Seed/bootstrap rows reserve ids 1..999 and are
never produced here. Monotonic within a process; thread-safe.
"""
import threading
import time

import config

# Custom epoch: 2024-01-01T00:00:00Z (ms). Keeps ids small for ~69 years.
AXP_EPOCH = 1704067200000

INSTANCE_BITS = 10
SEQUENCE_BITS = 12

MAX_INSTANCE = (1 << INSTANCE_BITS) - 1      # 1023
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1      # 4095

INSTANCE_SHIFT = SEQUENCE_BITS               # 12
TIMESTAMP_SHIFT = SEQUENCE_BITS + INSTANCE_BITS  # 22

# Seed/bootstrap rows reserve this range; runtime ids are always far above it.
SEED_ID_MAX = 999


class SnowflakeGenerator:
    def __init__(self, instance: int):
        if instance < 0 or instance > MAX_INSTANCE:
            raise ValueError(
                'SNOWFLAKE_INSTANCE must be in 0..%d (got %r)' % (MAX_INSTANCE, instance)
            )
        self._instance = instance
        self._lock = threading.Lock()
        self._last_ts = -1
        self._sequence = 0

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _wait_next_ms(self, last_ts: int) -> int:
        ts = self._now_ms()
        while ts <= last_ts:
            ts = self._now_ms()
        return ts

    def next_id(self) -> int:
        with self._lock:
            ts = self._now_ms()

            if ts < self._last_ts:
                # Clock moved backwards — wait it out rather than emit a dupe.
                ts = self._wait_next_ms(self._last_ts)

            if ts == self._last_ts:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    # Sequence exhausted for this ms — advance to next ms.
                    ts = self._wait_next_ms(self._last_ts)
            else:
                self._sequence = 0

            self._last_ts = ts

            return (
                ((ts - AXP_EPOCH) << TIMESTAMP_SHIFT)
                | (self._instance << INSTANCE_SHIFT)
                | self._sequence
            )


_generator = SnowflakeGenerator(config.SNOWFLAKE_INSTANCE)


def generate_snowflake_id() -> int:
    """Return a new unique Snowflake id for the current process instance."""
    return _generator.next_id()
