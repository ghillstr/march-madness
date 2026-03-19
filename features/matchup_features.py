"""Convenience functions for generating matchup features for prediction."""

import numpy as np
from features.feature_engineering import build_matchup_features
from config import CURRENT_SEASON


def predict_matchup_features(conn, team1_id, team2_id,
                             seed1=None, seed2=None,
                             season=None):
    """Build feature vector for a new prediction (no game result needed).

    Uses current season data and generates synthetic spread from SRS.
    """
    season = season or CURRENT_SEASON

    # Get SRS for synthetic spread
    ts1 = conn.execute(
        "SELECT srs, ppg FROM team_seasons WHERE team_id = ? AND season = ?",
        (team1_id, season),
    ).fetchone()
    ts2 = conn.execute(
        "SELECT srs, ppg FROM team_seasons WHERE team_id = ? AND season = ?",
        (team2_id, season),
    ).fetchone()

    spread = None
    over_under = None
    if ts1 and ts2 and ts1["srs"] is not None and ts2["srs"] is not None:
        spread = ts2["srs"] - ts1["srs"]
    if ts1 and ts2 and ts1["ppg"] is not None and ts2["ppg"] is not None:
        over_under = (ts1["ppg"] + ts2["ppg"]) * 0.97

    return build_matchup_features(
        conn, team1_id, team2_id, season,
        seed1=seed1, seed2=seed2,
        spread=spread, over_under=over_under,
    )


def get_feature_stats(conn, season=None):
    """Get mean and std of features for normalization (from training data)."""
    from features.feature_engineering import build_training_data
    features, _, _, seasons = build_training_data(conn)
    if features is None:
        return None, None
    # Use only training seasons for normalization stats
    if season:
        mask = seasons < season
        features = features[mask]
    mean = np.mean(features, axis=0)
    std = np.std(features, axis=0)
    std[std < 1e-8] = 1.0  # Avoid division by zero
    return mean, std
