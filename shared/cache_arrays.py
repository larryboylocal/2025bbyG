"""Reusable numeric ring buffer.

This is the only shared runtime structure. It stores plain numbers.
It does not know symbols, orders, balances, or which terminal filled it.
"""

from __future__ import annotations


class RingCache:
    """Fixed-capacity cache of plain values, oldest dropped first."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = int(capacity)
        self._values: list[float] = []

    def push(self, value: float) -> None:
        self._values.append(float(value))
        if len(self._values) > self.capacity:
            self._values = self._values[-self.capacity :]

    def values(self) -> list[float]:
        return list(self._values)

    def __len__(self) -> int:
        return len(self._values)
