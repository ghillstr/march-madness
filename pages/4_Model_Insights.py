"""Model performance analysis: accuracy, AUC, feature importance, calibration."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import torch

from db.database import get_db
from model.network import MarchMadnessNet
from model.dataset import MarchMadnessDataset
from features.feature_engineering import build_training_data
from config import (
    MODEL_DIR, FEATURE_NAMES, TRAIN_END, VAL_SEASON, TEST_SEASON, BATCH_SIZE,
)

st.set_page_config(page_title="Model Insights", page_icon="\U0001f3c0", layout="wide")
st.title("\U0001f3c0 Model Insights")

model_path = os.path.join(MODEL_DIR, "best_model.pt")
metrics_path = os.path.join(MODEL_DIR, "metrics.json")

if not os.path.exists(model_path):
    st.warning("No trained model found. Train the model first.")
    st.stop()

# Load metrics
if os.path.exists(metrics_path):
    with open(metrics_path) as f:
        metrics = json.load(f)

    st.subheader("Training Metrics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Test Accuracy", f"{metrics.get('test_accuracy', 0):.1f}%")
    c2.metric("Margin MAE", f"{metrics.get('margin_mae', 0):.2f} pts")
    c3.metric("Best Epoch", metrics.get("best_epoch", 0))
    c4.metric("Val Accuracy", f"{metrics.get('val_accuracy', 0):.1f}%")

    st.caption(
        f"Train: {metrics.get('train_samples', 0)} samples | "
        f"Val: {metrics.get('val_samples', 0)} | "
        f"Test: {metrics.get('test_samples', 0)}"
    )

st.markdown("---")

# Load model and data for detailed analysis
@st.cache_data(ttl=3600)
def load_analysis_data():
    """Load model predictions on test data."""
    with get_db() as conn:
        features, win_labels, margin_labels, seasons = build_training_data(conn)

    if features is None:
        return None

    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    model = MarchMadnessNet()
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    mean = np.array(checkpoint["mean"])
    std = np.array(checkpoint["std"])
    std[std < 1e-8] = 1.0

    # Test set
    test_mask = seasons == TEST_SEASON
    X_test = features[test_mask]
    y_win_test = win_labels[test_mask]
    y_margin_test = margin_labels[test_mask]

    if len(X_test) == 0:
        # Fall back to validation
        test_mask = seasons == VAL_SEASON
        X_test = features[test_mask]
        y_win_test = win_labels[test_mask]
        y_margin_test = margin_labels[test_mask]

    X_norm = (X_test - mean) / std
    X_tensor = torch.tensor(X_norm, dtype=torch.float32)

    with torch.no_grad():
        probs, margins = model(X_tensor)

    return {
        "probs": probs.numpy().flatten(),
        "margins": margins.numpy().flatten(),
        "true_wins": y_win_test,
        "true_margins": y_margin_test,
        "features": features,
        "seasons": seasons,
        "mean": mean,
        "std": std,
    }


data = load_analysis_data()
if data is None:
    st.warning("No training data available. Run scrapers and retrain.")
    st.stop()

# Feature Importance (permutation-based approximation using weight magnitudes)
st.subheader("Feature Importance")

checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
model = MarchMadnessNet()
model.load_state_dict(checkpoint["model_state"])

# Use first layer weights as importance proxy
first_layer_weight = model.backbone[0].weight.data.abs().mean(dim=0).numpy()
importance = first_layer_weight / first_layer_weight.sum() * 100

feat_names = FEATURE_NAMES[:len(importance)]
sorted_idx = np.argsort(importance)[::-1]

fig = go.Figure(data=[go.Bar(
    x=[feat_names[i] for i in sorted_idx[:15]],
    y=[importance[i] for i in sorted_idx[:15]],
    marker_color="#3498db",
)])
fig.update_layout(
    title="Top 15 Most Important Features (Weight Magnitude)",
    xaxis_title="Feature",
    yaxis_title="Relative Importance (%)",
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

# Calibration plot
st.markdown("---")
st.subheader("Calibration Plot")

probs = data["probs"]
true_wins = data["true_wins"]

if len(probs) > 0:
    n_bins = 10
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = []
    bin_actual = []
    bin_counts = []

    for i in range(n_bins):
        mask = (probs >= bin_edges[i]) & (probs < bin_edges[i + 1])
        if mask.sum() > 0:
            bin_centers.append((bin_edges[i] + bin_edges[i + 1]) / 2)
            bin_actual.append(true_wins[mask].mean())
            bin_counts.append(mask.sum())

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=bin_centers, y=bin_actual, mode="markers+lines",
        name="Model", marker=dict(size=10),
    ))
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1], mode="lines",
        name="Perfect Calibration", line=dict(dash="dash", color="gray"),
    ))
    fig.update_layout(
        title="Calibration: Predicted vs Actual Win Rate",
        xaxis_title="Predicted Probability",
        yaxis_title="Actual Win Rate",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

# Prediction distribution
st.subheader("Prediction Distribution")
fig = go.Figure(data=[go.Histogram(
    x=probs, nbinsx=50, marker_color="#2ecc71",
)])
fig.update_layout(
    title="Distribution of Win Probabilities (Test Set)",
    xaxis_title="Predicted Win Probability",
    yaxis_title="Count",
    height=400,
)
st.plotly_chart(fig, use_container_width=True)

# Margin prediction scatter
st.subheader("Margin Prediction Accuracy")
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=data["true_margins"], y=data["margins"],
    mode="markers", opacity=0.5,
    marker=dict(color="#e74c3c", size=5),
))
fig.add_trace(go.Scatter(
    x=[-30, 30], y=[-30, 30], mode="lines",
    line=dict(dash="dash", color="gray"), name="Perfect",
))
fig.update_layout(
    title="Predicted vs Actual Score Margin",
    xaxis_title="Actual Margin",
    yaxis_title="Predicted Margin",
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

# Upset detection analysis
st.markdown("---")
st.subheader("Upset Analysis")
st.caption("Games where the lower-seeded team won (seed diff > 0 means team1 was lower seed)")

if len(probs) > 0:
    # Get seed diff feature (index 14)
    test_mask = data["seasons"] == TEST_SEASON
    if test_mask.sum() == 0:
        test_mask = data["seasons"] == VAL_SEASON
    test_features = data["features"][test_mask]

    if test_features.shape[1] > 14:
        seed_diffs = test_features[:, 14]  # seed_diff feature
        upsets = (true_wins == 1) & (seed_diffs > 0)  # Lower seed (higher number) won
        upset_pct = upsets.mean() * 100 if len(upsets) > 0 else 0

        predicted_upsets = (probs < 0.5) & (seed_diffs < 0)  # Model picked the underdog
        pred_upset_pct = predicted_upsets.mean() * 100 if len(predicted_upsets) > 0 else 0

        c1, c2 = st.columns(2)
        c1.metric("Actual Upset Rate", f"{upset_pct:.1f}%")
        c2.metric("Model-Predicted Upsets", f"{pred_upset_pct:.1f}%")
