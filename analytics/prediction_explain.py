from __future__ import annotations

from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analytics.prediction import MLResult, make_supervised_dataset


SUPPORTED_SHAP_MODEL_KEYS = {"random_forest", "hist_gradient_boosting"}


def shap_is_available() -> bool:
    try:
        import shap  # noqa: F401
    except Exception:
        return False
    return True


def supports_shap_explanations(model_key: str) -> bool:
    return model_key in SUPPORTED_SHAP_MODEL_KEYS


def _positive_class_shap_values(values: Any) -> np.ndarray:
    if isinstance(values, list):
        if len(values) >= 2:
            return np.asarray(values[1])
        return np.asarray(values[0])

    arr = np.asarray(values)
    if arr.ndim == 3:
        if arr.shape[-1] >= 2:
            return arr[:, :, 1]
        return arr[:, :, 0]
    return arr


def _prepare_shap_sample(
    result: MLResult,
    X: pd.DataFrame,
    y_current: pd.Series,
    max_rows: int,
) -> tuple[pd.DataFrame, np.ndarray]:
    if not supports_shap_explanations(result.model_key):
        raise ValueError("SHAP visualization is only enabled for random forest and hist gradient boosting.")
    if not shap_is_available():
        raise RuntimeError("SHAP is not available in the current environment.")

    import shap

    X_supervised, _ = make_supervised_dataset(X, y_current, horizon=result.horizon)
    if X_supervised.empty:
        raise ValueError("No supervised rows are available for SHAP explanations.")

    feature_names = list(result.feature_names)
    X_supervised = X_supervised.loc[:, feature_names].copy()
    X_sample = X_supervised.tail(min(int(max_rows), len(X_supervised))).copy()

    imputer = result.pipeline.named_steps["imputer"]
    model = result.pipeline.named_steps["model"]

    X_imputed = pd.DataFrame(
        imputer.transform(X_sample),
        index=X_sample.index,
        columns=feature_names,
    )

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_imputed)
    positive_values = _positive_class_shap_values(shap_values)
    if positive_values.ndim != 2:
        raise RuntimeError("Unexpected SHAP output shape.")

    return X_imputed, positive_values


def build_global_shap_beeswarm_figure(
    result: MLResult,
    X: pd.DataFrame,
    y_current: pd.Series,
    *,
    top_n: int = 10,
    max_rows: int = 200,
):
    import shap

    X_imputed, positive_values = _prepare_shap_sample(
        result=result,
        X=X,
        y_current=y_current,
        max_rows=max_rows,
    )

    plt.close("all")
    fig = plt.figure(figsize=(8.5, max(3.6, 0.32 * int(top_n) + 1.1)))
    shap.summary_plot(
        positive_values,
        X_imputed,
        plot_type="dot",
        max_display=int(top_n),
        show=False,
    )
    fig = plt.gcf()
    fig.tight_layout()
    return fig
