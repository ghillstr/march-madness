"""Inference wrapper for MarchMadnessNet."""

import os
import numpy as np
import torch

from model.network import MarchMadnessNet
from features.matchup_features import predict_matchup_features
from config import MODEL_DIR, CURRENT_SEASON


class Predictor:
    """Load trained model and make predictions."""

    def __init__(self, model_path=None):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model_path = model_path or os.path.join(MODEL_DIR, "best_model.pt")

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"No trained model found at {model_path}. Run train.py first."
            )

        checkpoint = torch.load(model_path, map_location=self.device,
                                weights_only=False)
        self.model = MarchMadnessNet().to(self.device)
        self.model.load_state_dict(checkpoint["model_state"])
        self.model.eval()

        self.mean = np.array(checkpoint["mean"], dtype=np.float32)
        self.std = np.array(checkpoint["std"], dtype=np.float32)
        self.std[self.std < 1e-8] = 1.0

    def predict(self, conn, team1_id, team2_id,
                seed1=None, seed2=None, season=None):
        """Predict win probability and margin for team1 vs team2.

        Returns:
            dict with win_prob, margin, confidence
        """
        season = season or CURRENT_SEASON
        features = predict_matchup_features(
            conn, team1_id, team2_id, seed1=seed1, seed2=seed2, season=season
        )
        if features is None:
            return {"win_prob": 0.5, "margin": 0.0, "confidence": "low"}

        # Normalize
        features = (features - self.mean) / self.std
        X = torch.tensor(features, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            win_prob, margin = self.model(X)

        wp = win_prob.item()
        mg = margin.item()

        # Confidence level
        if abs(wp - 0.5) > 0.3:
            conf = "high"
        elif abs(wp - 0.5) > 0.15:
            conf = "medium"
        else:
            conf = "low"

        return {
            "win_prob": wp,
            "margin": mg,
            "confidence": conf,
        }

    def predict_from_features(self, features):
        """Predict from a raw feature vector (already built)."""
        features = (features - self.mean) / self.std
        X = torch.tensor(features, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            win_prob, margin = self.model(X)

        return win_prob.item(), margin.item()
