# 🏀 March Madness Predictor

A neural network-powered NCAA tournament bracket simulator with a full Streamlit web UI. Predicts game outcomes, simulates full brackets, and tracks live results for the 2026 March Madness tournament.

---

## Features

- **Bracket Predictor** — Deterministic "best prediction" bracket plus random scenario simulations
- **Monte Carlo Simulation** — 10,000-run championship odds for every team
- **Live Bracket** — Tracks real 2026 tournament results scraped from Sports Reference, with game times pulled from ESPN
- **Game Predictions** — Head-to-head matchup predictor with stat comparison radar chart
- **Team Explorer** — Deep dive into team stats and tournament history
- **Model Insights** — Feature importance, accuracy, and calibration analysis
- **Injury Awareness** — Scrapes current injury reports from ESPN and factors them into predictions

---

## How It Works

### Data
- Team stats, player stats, and tournament results scraped from [Sports Reference](https://www.sports-reference.com/cbb) (2014–2025)
- Point spreads synthesized from SRS differentials
- Injury reports scraped live from ESPN

### Model
- **Architecture**: Dual-head PyTorch neural network
  - Shared backbone: 3 hidden layers (128 → 64 → 32) with BatchNorm, ReLU, Dropout
  - Win probability head → sigmoid output
  - Score margin head → regression output
- **Features**: 30 matchup differential features including offensive/defensive efficiency, seeding, spreads, player metrics, travel distance, and injury impact
- **Training**: Early stopping, Adam optimizer, combined BCE + MSE loss
- **Test Accuracy**: ~87%

### Simulation
- Deterministic mode: always picks the higher-probability winner
- Random mode: uses win probabilities as weighted coin flips
- Monte Carlo: 10,000 full bracket simulations for championship odds

---

## Quick Start

### Option 1 — Docker (recommended)

```bash
git clone https://github.com/ghillstr/march-madness.git
cd march-madness
docker compose up -d
```

Open **http://localhost:8501**

### Option 2 — Local

```bash
git clone https://github.com/ghillstr/march-madness.git
cd march-madness
pip install -r requirements.txt

# Collect data (~2-3 hours due to rate limits)
python scraping/run_all_scrapers.py

# Train the model
python model/train.py

# Run the app
streamlit run app.py
```

---

## Project Structure

```
march-madness/
├── app.py                        # Streamlit entry point
├── config.py                     # All configuration constants
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── scraping/
│   ├── tournament_scraper.py     # NCAA bracket results
│   ├── team_stats_scraper.py     # Team season stats
│   ├── player_stats_scraper.py   # Player per-game stats
│   ├── injury_scraper.py         # ESPN injury reports
│   ├── odds_scraper.py           # Synthetic point spreads
│   └── run_all_scrapers.py       # Orchestrator
│
├── db/
│   ├── schema.sql                # SQLite schema
│   └── database.py               # DB helpers
│
├── features/
│   ├── feature_engineering.py    # 30-feature matchup vectors
│   └── matchup_features.py       # Prediction-time feature builder
│
├── model/
│   ├── network.py                # MarchMadnessNet (PyTorch)
│   ├── dataset.py                # Dataset + normalization
│   ├── train.py                  # Training loop with early stopping
│   └── predict.py                # Inference wrapper
│
├── bracket/
│   ├── bracket_logic.py          # 68-team bracket structure
│   └── simulator.py              # Deterministic, random & Monte Carlo sims
│
└── pages/
    ├── 1_Bracket.py              # Predicted bracket visual
    ├── 2_Game_Predictions.py     # Head-to-head predictor
    ├── 3_Team_Explorer.py        # Team stats explorer
    ├── 4_Model_Insights.py       # Model performance analysis
    └── 5_Live_Bracket.py         # Live 2026 tournament tracker
```

---

## Bracket Layout

| Side | Top Region | Bottom Region |
|------|-----------|---------------|
| Left | East | South |
| Right | West | Midwest |

Final Four pairings: **East vs South** · **West vs Midwest**

---

## Retraining

After running scrapers to update data:

```bash
python model/train.py
```

The model checkpoint is saved to `model/saved/best_model.pt` and the app picks it up automatically on next load.
