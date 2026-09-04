"""Pure adjudication core: no filesystem, network, clock, randomness, or model calls."""

from .accumulators import apply_delta, negate_delta
from .engine import ENGINE_VERSION, adjudicate

__all__ = ["ENGINE_VERSION", "adjudicate", "apply_delta", "negate_delta"]
