"""Plotting utilities for score evolution tracking."""

import numpy as np
from typing import Dict, Any


def create_plot_data_point(data_item: Dict[str, Any], facet_name: str) -> Dict[str, Any]:
    """Create a standardized plot data point from iteration data.
    
    This function deduplicates the plot data creation logic used in ScoreEvolutionTracker.
    
    Args:
        data_item: Iteration data with overall and facets statistics
        facet_name: Name of the facet ("overall" or specific facet name)
        
    Returns:
        Dict with iteration, facet, mean, error, and confidence intervals
    """
    stats = data_item["facets"][facet_name] if facet_name != "overall" else data_item["overall"]
    error = stats["stdev"] / np.sqrt(max(1, stats["count"]))
    
    return {
        "iteration": data_item["iteration"],
        "facet": facet_name,
        "mean": stats["mean"],
        "error": error,
        "ci_lower": stats["mean"] - error,
        "ci_upper": stats["mean"] + error
    }