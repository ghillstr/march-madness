"""March Madness Predictor - Streamlit Entry Point."""

import streamlit as st

st.set_page_config(
    page_title="March Madness Predictor",
    page_icon="\U0001f3c0",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("\U0001f3c0 March Madness Predictor 2026")
st.markdown("---")

st.markdown("""
### Welcome to the NCAA Tournament Prediction App

This app uses a neural network trained on 10+ years of NCAA tournament data
to predict game outcomes and simulate the 2026 March Madness bracket.

**Navigate using the sidebar to explore:**

- **Bracket** - Full tournament bracket with win probabilities and championship odds
- **Game Predictions** - Head-to-head matchup predictor for any two teams
- **Team Explorer** - Deep dive into team stats, key players, and tournament history
- **Model Insights** - Model accuracy, feature importance, and calibration analysis

### How It Works

1. **Data**: Team stats, player stats, and tournament results scraped from Sports Reference (2014-2025)
2. **Features**: 29 matchup differential features including efficiency, seeding, spreads, player metrics, and location
3. **Model**: Dual-head PyTorch neural network predicting win probability and score margin
4. **Simulation**: Monte Carlo simulation (10,000 runs) for championship odds

### Quick Start

```bash
# Collect data (takes ~2-3 hours due to rate limits)
python scraping/run_all_scrapers.py

# Train the model
python model/train.py

# Run the app
streamlit run app.py
```
""")

# Show data status
try:
    from db.database import get_db
    with get_db() as conn:
        stats = {}
        for table in ["teams", "team_seasons", "players", "player_stats",
                       "tournament_games", "point_spreads"]:
            try:
                count = conn.execute(f"SELECT COUNT(*) as n FROM {table}").fetchone()["n"]
                stats[table] = count
            except Exception:
                stats[table] = 0

        st.markdown("### Database Status")
        cols = st.columns(3)
        cols[0].metric("Teams", stats["teams"])
        cols[0].metric("Team Seasons", stats["team_seasons"])
        cols[1].metric("Players", stats["players"])
        cols[1].metric("Player Stats", stats["player_stats"])
        cols[2].metric("Tournament Games", stats["tournament_games"])
        cols[2].metric("Point Spreads", stats["point_spreads"])

        if stats["teams"] == 0:
            st.warning("No data found. Run `python scraping/run_all_scrapers.py` to collect data.")
except Exception as e:
    st.info(f"Database not initialized yet. Run the scrapers first. ({e})")

# Check model status
import os
from config import MODEL_DIR
model_path = os.path.join(MODEL_DIR, "best_model.pt")
if os.path.exists(model_path):
    st.success("Trained model found! Navigate to the pages to see predictions.")
else:
    st.info("No trained model found. Run `python model/train.py` after collecting data.")
