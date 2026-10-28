"""Measure duplicate-detection accuracy against the synthetic answer key."""

from __future__ import annotations

from itertools import combinations

import pandas as pd

from .pipeline import Result


def _pairs_from_groups(groups) -> set[frozenset]:
    out = set()
    for g in groups:
        out |= {frozenset(p) for p in combinations(sorted(g), 2)}
    return out


def evaluate(result: Result, truth: pd.DataFrame) -> pd.DataFrame:
    """Pairwise precision/recall, for High-only and High+Review clusters."""
    truth_groups = truth.groupby("Entity").apply(
        lambda d: list(zip(d["Module"], d["Record Id"])), include_groups=False)
    true_pairs = _pairs_from_groups(g for g in truth_groups if len(g) > 1)

    rows = []
    for label, bands in (("High confidence only", {"High"}), ("High + Review", {"High", "Review"})):
        pred = _pairs_from_groups(c.members for c in result.clusters if c.band in bands)
        tp = len(pred & true_pairs)
        precision = tp / len(pred) if pred else 1.0
        recall = tp / len(true_pairs) if true_pairs else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append({"Clusters used": label, "Predicted pairs": len(pred), "True pairs": len(true_pairs),
                     "Correct": tp, "Precision": round(precision, 3), "Recall": round(recall, 3),
                     "F1": round(f1, 3)})
    return pd.DataFrame(rows)
