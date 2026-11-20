"""API-key ring with round-robin rotation for LLM providers.

Free tiers throttle per key per minute, so the client's answer to a
429 is rotation: each key is tried once, exhausted keys are skipped,
and a reset reopens the ring when the rate window may have passed.
Keys are held as values here, but never rendered: the repr and str
show only counts, so no key material can leak through logging or
error formatting.
"""

from collections.abc import Sequence


class KeyRing:
    """Round-robin iterator over one provider's API keys.

    ``next_key`` returns the next key that is not exhausted (or
    ``None`` when every key is exhausted); ``mark_exhausted`` retires
    a key; ``reset`` clears the exhausted set because rate windows
    are per-minute, not permanent. The pointer keeps advancing across
    calls so successive rings start where the last one left off.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        self._keys: tuple[str, ...] = tuple(keys)
        self._exhausted: set[str] = set()
        self._position = 0

    def next_key(self) -> str | None:
        """Return the next usable key, or ``None`` if all exhausted."""
        for offset in range(len(self._keys)):
            index = (self._position + offset) % len(self._keys)
            key = self._keys[index]
            if key not in self._exhausted:
                self._position = (index + 1) % len(self._keys)
                return key
        return None

    def mark_exhausted(self, key: str) -> None:
        """Retire ``key`` (rate-limited now, or rejected permanently)."""
        self._exhausted.add(key)

    def reset(self) -> None:
        """Reopen every key — per-minute windows may have passed."""
        self._exhausted.clear()

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return (
            f"KeyRing({len(self._keys)} keys, "
            f"{len(self._exhausted)} exhausted)"
        )

    __str__ = __repr__
