"""Configuration constants for March Madness Predictor."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db", "march_madness.db")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
MODEL_DIR = os.path.join(BASE_DIR, "model", "saved")

# Sports Reference base URLs
SR_BASE = "https://www.sports-reference.com/cbb"
SR_SEASONS = f"{SR_BASE}/seasons/men"
SR_SCHOOLS = f"{SR_BASE}/schools"
SR_POSTSEASON = f"{SR_BASE}/postseason/men"

# Scraping settings
REQUEST_DELAY = 3.0  # seconds between requests
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Season range
HISTORICAL_START = 2014
HISTORICAL_END = 2025
CURRENT_SEASON = 2026
SKIP_SEASONS = {2020}  # COVID cancellation

# Training settings
TRAIN_END = 2023
VAL_SEASON = 2024
TEST_SEASON = 2025

# Neural network
NUM_FEATURES = 30
HIDDEN_SIZES = [128, 64, 32]
DROPOUT_RATES = [0.3, 0.3, 0.2]
LEARNING_RATE = 0.001
WEIGHT_DECAY = 1e-4
BATCH_SIZE = 256
MAX_EPOCHS = 500
EARLY_STOP_PATIENCE = 25
WIN_LOSS_WEIGHT = 0.6
MARGIN_LOSS_WEIGHT = 0.4

# Monte Carlo
MC_SIMULATIONS = 10000

# Feature names (for display/importance)
FEATURE_NAMES = [
    "ORtg_diff", "DRtg_diff", "NetRtg_diff", "Pace_diff",
    "SRS_diff", "SOS_diff", "eFG%_diff", "TOV%_diff",
    "ORB%_diff", "FTr_diff", "3PAr_diff", "TS%_diff",
    "OSRS_diff", "DSRS_diff",
    "seed_diff", "seed_sum", "seed_product", "hist_seed_win_rate",
    "spread", "over_under",
    "top_scorer_diff", "experience_diff", "roster_depth_diff", "star_power_diff",
    "win_pct_diff", "MOV_diff", "away_win_pct_diff",
    "distance_adv_diff", "home_region_flag",
    "injury_impact_diff",
]
