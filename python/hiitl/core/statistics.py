"""Statistics shared by the SDK, hosted analysis and their measurements."""

from collections.abc import Iterable


def percentile(samples: Iterable[float], p: float) -> float:
    """Interpolate at ``(n - 1) * p``; ``p`` is a fraction from zero to one.

    The caller owns output precision. An empty sample has no percentile.
    """
    ordered = sorted(samples)
    if not ordered:
        raise ValueError("A percentile requires a nonempty sample")

    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])
