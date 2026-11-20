"""Post-hoc usage sanity checks against the visible reply (T15).

Providers can under-report usage or hide reasoning tokens from the
counters while burning them server-side. Comparing the reported
output tokens with the visible reply length catches both directions
of divergence; the check runs once per model at real-call time and
the outcome is recorded in ``docs/log.md`` (deferred — real calls
are out of scope for this dispatch).
"""

from llm.client import LLMResponse

_DIVERGENCE_RATIO = 5.0


def sanity_check_usage(text: str, usage: LLMResponse) -> str | None:
    """Return a note when reported output tokens diverge >5x from
    the visible reply length, else ``None``.

    The implied token count is ``len(text) / 4``. A ratio above the
    threshold in either direction means hidden reasoning (reported
    far above visible) or under-reporting (visible far above
    reported); an empty reply with reported tokens is the extreme
    hidden-reasoning signature. The note names the canonical model
    so the real-call log can be attributed.
    """
    output_tokens = usage.output_tokens
    implied = len(text) / 4.0
    if implied == 0.0:
        divergent = output_tokens > 5
        ratio_text = "infinite"
    elif output_tokens == 0:
        divergent = True
        ratio_text = "infinite"
    else:
        ratio = max(output_tokens / implied, implied / output_tokens)
        divergent = ratio > _DIVERGENCE_RATIO
        ratio_text = f"{ratio:.1f}"
    if not divergent:
        return None
    return (
        f"usage divergence >5x for '{usage.model_name}': reported "
        f"{output_tokens} output tokens vs ~{int(implied)} implied "
        f"by {len(text)} visible chars (ratio {ratio_text}; hidden "
        f"reasoning or under-reporting) — verify on a real call and "
        f"record in docs/log.md"
    )
