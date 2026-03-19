"""Head-to-head matchup predictor for any two teams."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go
import numpy as np

from db.database import get_db, get_all_teams
from model.predict import Predictor
from config import CURRENT_SEASON, MODEL_DIR

st.set_page_config(page_title="Game Predictions", page_icon="\U0001f3c0", layout="wide")
st.title("\U0001f3c0 Head-to-Head Game Predictions")

model_path = os.path.join(MODEL_DIR, "best_model.pt")
if not os.path.exists(model_path):
    st.warning("No trained model found. Train the model first.")
    st.stop()

# Load teams
with get_db() as conn:
    teams = get_all_teams(conn, season=CURRENT_SEASON)
    if not teams:
        teams = get_all_teams(conn)

if not teams:
    st.warning("No teams in database. Run scrapers first.")
    st.stop()

team_names = [t["school_name"] for t in teams]
team_map = {t["school_name"]: t["team_id"] for t in teams}

# Team selection
col1, col2 = st.columns(2)
with col1:
    team1_name = st.selectbox("Team 1", team_names, index=0)
    seed1 = st.number_input("Seed (optional)", 1, 16, 8, key="seed1")
with col2:
    default_idx = min(1, len(team_names) - 1)
    team2_name = st.selectbox("Team 2", team_names, index=default_idx)
    seed2 = st.number_input("Seed (optional)", 1, 16, 8, key="seed2")

if st.button("Predict Game", type="primary"):
    t1_id = team_map[team1_name]
    t2_id = team_map[team2_name]

    predictor = Predictor()
    with get_db() as conn:
        result = predictor.predict(conn, t1_id, t2_id, seed1=seed1, seed2=seed2)

    wp = result["win_prob"]
    margin = result["margin"]
    conf = result["confidence"]

    st.markdown("---")

    # Main prediction display
    col1, col2, col3 = st.columns([2, 1, 2])

    with col1:
        st.markdown(f"### {team1_name}")
        st.metric("Win Probability", f"{wp:.1%}")
    with col2:
        st.markdown("### vs")
        st.metric("Predicted Margin", f"{abs(margin):.1f} pts")
        st.caption(f"Confidence: {conf.upper()}")
    with col3:
        st.markdown(f"### {team2_name}")
        st.metric("Win Probability", f"{1-wp:.1%}")

    # Win probability bar
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=["Win Probability"],
        x=[wp * 100],
        orientation="h",
        name=team1_name,
        marker_color="#3498db",
        text=f"{wp:.1%}",
        textposition="inside",
    ))
    fig.add_trace(go.Bar(
        y=["Win Probability"],
        x=[(1-wp) * 100],
        orientation="h",
        name=team2_name,
        marker_color="#e74c3c",
        text=f"{1-wp:.1%}",
        textposition="inside",
    ))
    fig.update_layout(
        barmode="stack",
        height=100,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=True,
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Radar chart comparison
    with get_db() as conn:
        ts1 = conn.execute(
            "SELECT * FROM team_seasons WHERE team_id = ? AND season = ?",
            (t1_id, CURRENT_SEASON),
        ).fetchone()
        ts2 = conn.execute(
            "SELECT * FROM team_seasons WHERE team_id = ? AND season = ?",
            (t2_id, CURRENT_SEASON),
        ).fetchone()

    if ts1 and ts2:
        categories = ["ORtg", "DRtg", "eFG%", "TOV%", "ORB%", "FT Rate",
                       "SRS", "Pace"]
        stat_keys = ["ortg", "drtg", "efg_pct", "tov_pct", "orb_pct",
                      "ft_rate", "srs", "pace"]

        vals1 = [ts1[k] or 0 for k in stat_keys]
        vals2 = [ts2[k] or 0 for k in stat_keys]

        # Normalize to 0-100 scale for radar
        all_vals = vals1 + vals2
        min_v = min(all_vals) if all_vals else 0
        max_v = max(all_vals) if all_vals else 1
        rng = max_v - min_v if max_v != min_v else 1

        norm1 = [(v - min_v) / rng * 100 for v in vals1]
        norm2 = [(v - min_v) / rng * 100 for v in vals2]

        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=norm1 + [norm1[0]], theta=categories + [categories[0]],
            fill="toself", name=team1_name, opacity=0.6,
        ))
        fig.add_trace(go.Scatterpolar(
            r=norm2 + [norm2[0]], theta=categories + [categories[0]],
            fill="toself", name=team2_name, opacity=0.6,
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            title="Team Comparison (Normalized)",
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Stats table
        st.subheader("Stat Comparison")
        import pandas as pd
        stat_display = {
            "Wins": "wins", "Losses": "losses", "PPG": "ppg",
            "Opp PPG": "opp_ppg", "ORtg": "ortg", "DRtg": "drtg",
            "eFG%": "efg_pct", "SRS": "srs", "SOS": "sos",
            "Pace": "pace", "Win %": "win_pct", "MOV": "mov",
        }
        data = {"Stat": [], team1_name: [], team2_name: [], "Advantage": []}
        for label, key in stat_display.items():
            v1 = ts1[key] if ts1[key] is not None else "N/A"
            v2 = ts2[key] if ts2[key] is not None else "N/A"
            adv = ""
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                # For DRtg, lower is better
                if key == "drtg":
                    adv = team1_name if v1 < v2 else team2_name
                else:
                    adv = team1_name if v1 > v2 else team2_name
            data["Stat"].append(label)
            data[team1_name].append(v1 if isinstance(v1, str) else f"{v1:.1f}" if isinstance(v1, float) else v1)
            data[team2_name].append(v2 if isinstance(v2, str) else f"{v2:.1f}" if isinstance(v2, float) else v2)
            data["Advantage"].append(adv)

        st.dataframe(pd.DataFrame(data), use_container_width=True)
