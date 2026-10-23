"""Read-only presentation of an already fitted decision tree; no model fitting."""
from __future__ import annotations

import numpy as np


def decision_tree_view(result):
    if result.model_key != "decision_tree":
        return None
    model = result.pipeline.named_steps["model"]
    names = result.pipeline.named_steps["imputer"].get_feature_names_out(result.feature_names)
    tree = model.tree_
    nodes = []
    for i in range(tree.node_count):
        leaf = tree.children_left[i] == tree.children_right[i]
        values = tree.value[i].reshape(-1)
        positive = np.flatnonzero(model.classes_ == 1)
        nodes.append({
            "id": i,
            "feature": None if leaf else str(names[tree.feature[i]]),
            "threshold": None if leaf else float(tree.threshold[i]),
            "left": None if leaf else int(tree.children_left[i]),
            "right": None if leaf else int(tree.children_right[i]),
            "samples": int(tree.n_node_samples[i]),
            "predicted_class": int(model.classes_[int(np.argmax(values))]),
            "positive_share": float(values[positive[0]] / values.sum()) if positive.size else 0.0,
        })
    return {"nodes": nodes}
