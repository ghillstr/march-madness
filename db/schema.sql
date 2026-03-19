-- March Madness Predictor Database Schema

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_name TEXT NOT NULL UNIQUE,
    sports_ref_slug TEXT UNIQUE,
    conference TEXT,
    latitude REAL,
    longitude REAL
);

CREATE TABLE IF NOT EXISTS team_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    wins INTEGER, losses INTEGER,
    ppg REAL, opp_ppg REAL,
    fg_pct REAL, fg3_pct REAL, ft_pct REAL,
    orb_per_game REAL, drb_per_game REAL, trb_per_game REAL,
    ast_per_game REAL, stl_per_game REAL, blk_per_game REAL,
    tov_per_game REAL,
    ortg REAL, drtg REAL, net_rtg REAL,
    pace REAL,
    efg_pct REAL, tov_pct REAL, orb_pct REAL, ft_rate REAL,
    opp_efg_pct REAL, opp_tov_pct REAL, opp_orb_pct REAL, opp_ft_rate REAL,
    srs REAL, sos REAL, osrs REAL, dsrs REAL,
    three_par REAL, ts_pct REAL,
    win_pct REAL, mov REAL, away_win_pct REAL,
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    UNIQUE(team_id, season)
);

CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    team_id INTEGER,
    sports_ref_slug TEXT,
    position TEXT,
    height_inches INTEGER,
    weight INTEGER,
    class_year TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

CREATE TABLE IF NOT EXISTS player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    games INTEGER, games_started INTEGER,
    mpg REAL, ppg REAL, rpg REAL, apg REAL,
    spg REAL, bpg REAL, tov REAL,
    fg_pct REAL, fg3_pct REAL, ft_pct REAL,
    efg_pct REAL, ts_pct REAL,
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    UNIQUE(player_id, team_id, season)
);

CREATE TABLE IF NOT EXISTS tournament_games (
    game_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    round TEXT NOT NULL,
    region TEXT,
    team1_id INTEGER NOT NULL,
    team2_id INTEGER NOT NULL,
    seed1 INTEGER, seed2 INTEGER,
    score1 INTEGER, score2 INTEGER,
    winner_id INTEGER,
    margin INTEGER,
    venue TEXT,
    venue_city TEXT,
    venue_state TEXT,
    venue_lat REAL,
    venue_lon REAL,
    game_time TEXT,
    FOREIGN KEY (team1_id) REFERENCES teams(team_id),
    FOREIGN KEY (team2_id) REFERENCES teams(team_id),
    FOREIGN KEY (winner_id) REFERENCES teams(team_id),
    UNIQUE(season, team1_id, team2_id, round)
);

CREATE TABLE IF NOT EXISTS tournament_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    seed INTEGER,
    region TEXT,
    round_reached TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    UNIQUE(team_id, season)
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    round TEXT NOT NULL,
    region TEXT,
    city TEXT,
    state TEXT,
    latitude REAL,
    longitude REAL,
    venue_name TEXT
);

CREATE TABLE IF NOT EXISTS point_spreads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    season INTEGER NOT NULL,
    team1_id INTEGER NOT NULL,
    team2_id INTEGER NOT NULL,
    spread REAL,
    over_under REAL,
    is_synthetic INTEGER DEFAULT 1,
    FOREIGN KEY (game_id) REFERENCES tournament_games(game_id),
    FOREIGN KEY (team1_id) REFERENCES teams(team_id),
    FOREIGN KEY (team2_id) REFERENCES teams(team_id)
);

CREATE TABLE IF NOT EXISTS player_injuries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER,
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    status TEXT NOT NULL,
    injury_type TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    UNIQUE(team_id, season, player_name)
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    round TEXT,
    team1_id INTEGER NOT NULL,
    team2_id INTEGER NOT NULL,
    win_prob_team1 REAL,
    predicted_margin REAL,
    predicted_winner_id INTEGER,
    actual_winner_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team1_id) REFERENCES teams(team_id),
    FOREIGN KEY (team2_id) REFERENCES teams(team_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_team_seasons_team ON team_seasons(team_id, season);
CREATE INDEX IF NOT EXISTS idx_player_stats_team ON player_stats(team_id, season);
CREATE INDEX IF NOT EXISTS idx_tournament_games_season ON tournament_games(season);
CREATE INDEX IF NOT EXISTS idx_tournament_results_season ON tournament_results(team_id, season);
CREATE INDEX IF NOT EXISTS idx_point_spreads_season ON point_spreads(season);
