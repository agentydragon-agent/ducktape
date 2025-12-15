"""Fitness computation utilities for GEPA optimization.

Shared between gepa_adapter and warm_start to avoid circular imports.
"""

from adgn.props.db.snapshots import DBGraderOutput, DBGraderSuccess


def compute_fitness(grader_output: DBGraderOutput | None) -> float:
    """Compute fitness score from grader output.

    Single-run recall: average found_credit across all occurrences.
    Returns 0.0 if grader failed (max_turns_exceeded, context_length_exceeded)
    or if no occurrences were graded.

    Args:
        grader_output: Grader output (success or failure variant)

    Returns:
        Fitness score in [0.0, 1.0]
    """
    if grader_output is None:
        return 0.0
    if not isinstance(grader_output, DBGraderSuccess):
        return 0.0
    if not grader_output.occurrence_results:
        return 0.0
    return sum(o.found_credit for o in grader_output.occurrence_results) / len(grader_output.occurrence_results)
