"""Explosive Opportunity Finder feature."""

from .analysis import (
    ExpectedGainModel,
    fit_expected_gain_model,
    label_plays,
    overall_summary,
    score_plays,
    summarize_matchup,
)

__all__ = [
    "ExpectedGainModel",
    "fit_expected_gain_model",
    "label_plays",
    "overall_summary",
    "score_plays",
    "summarize_matchup",
]
