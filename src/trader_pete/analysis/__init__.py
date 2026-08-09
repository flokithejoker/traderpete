"""Deterministic feature and narrative scoring."""

from trader_pete.analysis.context import build_research_context
from trader_pete.analysis.landscape import (
    analyze_landscape,
    load_narrative_registry,
    registry_asset_ids,
)
from trader_pete.analysis.scoring import finalize_research, score_signals

__all__ = [
    "analyze_landscape",
    "build_research_context",
    "finalize_research",
    "load_narrative_registry",
    "registry_asset_ids",
    "score_signals",
]
