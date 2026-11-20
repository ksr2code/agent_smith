"""API-key ring with round-robin rotation for LLM providers.

Free tiers throttle per key per minute, so the client's answer to a
429 is rotation: each key is tried once, exhausted keys are skipped,
and a reset reopens rate-limited keys when the rate window may have
passed. Auth rejections (401/402/403) are permanent — a reset never
reopens them. Keys are held as values here, but never rendered: the
repr and str show only counts, so no key material can leak through
logging or error formatting.
"""

from collections.abc import Sequence


class KeyRing:
    """Round-robin iterator over one provider's API keys.

    ``next_key`` returns the next key that is neither rate-limited
    nor permanently retired (or ``None`` when no usable key remains);
    ``mark_exhausted`` benches a key — rate-limited by default, or
    permanently with ``permanent=True``; ``reset`` clears ONLY the
    rate-limited set, because rate windows are per-minute while an
    auth rejection is forever. The pointer keeps advancing across
    calls so successive rings start where the last one left off.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        self._keys: tuple[str, ...] = tuple(keys)
        self._rate_limited: set[str] = set()
        self._retired: set[str] = set()
        self._position = 0

    def next_key(self) -> str | None:
        """Return the next usable key, or ``None`` if none remains."""
        for offset in range(len(self._keys)):
            index = (self._position + offset) % len(self._keys)
            key = self._keys[index]
            if key not in self._rate_limited and key not in self._retired:
                self._position = (index + 1) % len(self._keys)
                return key
        return None

    def mark_exhausted(self, key: str, *, permanent: bool = False) -> None:
        """Bench ``key``: rate-limited (default) or retired forever."""
        if permanent:
            self._retired.add(key)
        else:
            self._rate_limited.add(key)

    def reset(self) -> None:
        """Reopen rate-limited keys — per-minute windows may have
        passed; permanently retired keys stay out."""
        self._rate_limited.clear()

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        exhausted = len(self._rate_limited) + len(self._retired)
        return f"KeyRing({len(self._keys)} keys, {exhausted} exhausted)"

    __str__ = __repr__
