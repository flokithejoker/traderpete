"""Deterministic feature and narrative scoring."""

from trader_pete.analysis.context import build_research_context
from trader_pete.analysis.scoring import finalize_research, score_signals

__all__ = ["build_research_context", "finalize_research", "score_signals"]
