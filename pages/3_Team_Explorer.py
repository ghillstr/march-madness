"""Team stats drill-down: stats, key players, tournament history."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from db.database import get_db, get_all_teams
from config import CURRENT_SEASON

st.set_page_config(page_title="Team Explorer", page_icon="\U0001f3c0", layout="wide")
st.title("\U0001f3c0 Team Explorer")

with get_db() as conn:
    teams = get_all_teams(conn, season=CURRENT_SEASON)
    if not teams:
        teams = get_all_teams(conn)

if not teams:
    st.warning("No teams in database. Run scrapers first.")
    st.stop()

team_names = sorted([t["school_name"] for t in teams])
team_map = {t["school_name"]: t["team_id"] for t in teams}

selected = st.selectbox("Select a Team", team_names)
team_id = team_map[selected]

with get_db() as conn:
    # Team info
    team = conn.execute(
        "SELECT * FROM teams WHERE team_id = ?", (team_id,)
    ).fetchone()

    # Current season stats
    ts = conn.execute(
        "SELECT * FROM team_seasons WHERE team_id = ? AND season = ?",
        (team_id, CURRENT_SEASON),
    ).fetchone()
    if not ts:
        ts = conn.execute(
            "SELECT * FROM team_seasons WHERE team_id = ? ORDER BY season DESC LIMIT 1",
            (team_id,),
        ).fetchone()

    # Players
    players = conn.execute(
        """SELECT p.name, p.position, p.class_year, ps.*
           FROM player_stats ps
           JOIN players p ON ps.player_id = p.player_id
           WHERE ps.team_id = ? AND ps.season = ?
           ORDER BY ps.ppg DESC""",
        (team_id, CURRENT_SEASON),
    ).fetchall()
    if not players:
        players = conn.execute(
            """SELECT p.name, p.position, p.class_year, ps.*
               FROM player_stats ps
               JOIN players p ON ps.player_id = p.player_id
               WHERE ps.team_id = ?
               ORDER BY ps.season DESC, ps.ppg DESC
               LIMIT 15""",
            (team_id,),
        ).fetchall()

    # Tournament history
    tourn = conn.execute(
        """SELECT tr.season, tr.seed, tr.region, tr.round_reached
           FROM tournament_results tr
           WHERE tr.team_id = ?
           ORDER BY tr.season DESC""",
        (team_id,),
    ).fetchall()

    # Season-over-season stats
    all_seasons = conn.execute(
        "SELECT * FROM team_seasons WHERE team_id = ? ORDER BY season",
        (team_id,),
    ).fetchall()

# Display team header
st.markdown(f"## {selected}")
if team:
    conf = team["conference"] or "Unknown"
    st.caption(f"Conference: {conf}")

st.markdown("---")

# Current season stats
if ts:
    st.subheader("Current Season Stats")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Record", f"{ts['wins'] or 0}-{ts['losses'] or 0}")
    c1.metric("Win %", f"{(ts['win_pct'] or 0):.3f}")
    c2.metric("PPG", f"{ts['ppg'] or 0:.1f}")
    c2.metric("Opp PPG", f"{ts['opp_ppg'] or 0:.1f}")
    c3.metric("ORtg", f"{ts['ortg'] or 0:.1f}")
    c3.metric("DRtg", f"{ts['drtg'] or 0:.1f}")
    c4.metric("SRS", f"{ts['srs'] or 0:.1f}")
    c4.metric("SOS", f"{ts['sos'] or 0:.1f}")

    # Four factors
    st.subheader("Four Factors")
    ff_cols = st.columns(4)
    ff_cols[0].metric("eFG%", f"{(ts['efg_pct'] or 0):.3f}")
    ff_cols[1].metric("TOV%", f"{(ts['tov_pct'] or 0):.1f}")
    ff_cols[2].metric("ORB%", f"{(ts['orb_pct'] or 0):.1f}")
    ff_cols[3].metric("FT Rate", f"{(ts['ft_rate'] or 0):.3f}")

# Key players
if players:
    st.markdown("---")
    st.subheader("Roster")
    player_data = []
    for p in players:
        player_data.append({
            "Name": p["name"],
            "Pos": p["position"] or "",
            "Class": p["class_year"] or "",
            "PPG": p["ppg"] or 0,
            "RPG": p["rpg"] or 0,
            "APG": p["apg"] or 0,
            "FG%": p["fg_pct"] or 0,
            "3P%": p["fg3_pct"] or 0,
            "MPG": p["mpg"] or 0,
        })
    df = pd.DataFrame(player_data)
    st.dataframe(
        df.style.format({
            "PPG": "{:.1f}", "RPG": "{:.1f}", "APG": "{:.1f}",
            "FG%": "{:.3f}", "3P%": "{:.3f}", "MPG": "{:.1f}",
        }),
        use_container_width=True,
    )

# Tournament history
if tourn:
    st.markdown("---")
    st.subheader("Tournament History")
    th_data = [{"Season": t["season"], "Seed": t["seed"],
                "Region": t["region"] or "", "Round Reached": t["round_reached"] or ""}
               for t in tourn]
    st.dataframe(pd.DataFrame(th_data), use_container_width=True)

# Season trends
if all_seasons and len(all_seasons) > 1:
    st.markdown("---")
    st.subheader("Season Trends")

    seasons_list = [s["season"] for s in all_seasons]

    metric = st.selectbox("Metric", ["srs", "ortg", "drtg", "win_pct", "ppg", "pace"])
    values = [s[metric] for s in all_seasons]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=seasons_list, y=values, mode="lines+markers",
        name=metric.upper().replace("_", " "),
    ))
    fig.update_layout(
        xaxis_title="Season", yaxis_title=metric.upper().replace("_", " "),
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)
