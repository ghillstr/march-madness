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
- **AI Analyst** — Claude-powered scouting reports on any matchup, team or bracket, plus a chat
  analyst that queries the database and runs the model to answer questions

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

### AI Layer
- **Model**: Claude (`claude-opus-5` by default) via the Anthropic API
- **Grounding**: every report is written from a context pack built out of this database — team
  stats, roster aggregates, injuries, tournament history — plus the network's own prediction and
  the ranked model inputs behind it. The analyst is instructed to use nothing else
- **Chat**: the Ask the Analyst page gives Claude tools that read the same database and run the
  same network, so a chat answer and a page can't disagree
- **Optional**: with no API key the app behaves exactly as it did before — AI sections show a
  notice and every existing page is untouched

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

## AI Layer

The AI features are optional and off until you provide a key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

With Docker, the key is passed through from your shell:

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose up -d
```

**What you get**

| Page | AI feature |
|------|-----------|
| Game Predictions | Scouting report on the matchup: the pick, why, the case against, an X-factor |
| Team Explorer | Scouting report on the selected team's profile |
| Bracket | Walkthrough of the predicted bracket, and an upset watch list |
| Ask the Analyst | Chat — it searches teams, pulls stats, runs the model, and simulates odds |

**How it stays honest**

Every report is generated from a JSON context pack assembled in `llm/context.py`, and the system
prompt (`llm/prompts.py`) restricts the analyst to those facts. It cannot pull in half-remembered
college basketball trivia, and it can't override the network — the win probability it quotes is the
one the model produced. Missing data is reported as missing.

**Cost control**

- Reports are generated only when you click the button, never on page load
- Generated reports are cached on disk (`cache/llm/`) keyed by their grounding data, so
  re-rendering a page is free
- The frozen system prompt is sent as a cached prefix, so repeat calls only pay for the new context

**Tuning**

| Variable | Default | Meaning |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Enables the AI layer |
| `LLM_MODEL` | `claude-opus-5` | Model to use |
| `LLM_EFFORT` | `low` | Thinking effort for reports |
| `LLM_AGENT_EFFORT` | `medium` | Thinking effort for chat (it plans tool calls) |
| `LLM_MAX_TOOL_ROUNDS` | `12` | Tool-call budget per chat answer |

---

## Retraining

After running scrapers to update data:

```bash
python model/train.py
```

The model checkpoint is saved to `model/saved/best_model.pt` and the app picks it up automatically on next load.
