"""Build feature vectors from database for model training."""

import math
import numpy as np
from db.database import get_db

# Historical seed win rates (1-seed beats 16-seed ~99%, etc.)
SEED_WIN_RATES = {
    1: 0.99, 2: 0.94, 3: 0.85, 4: 0.79, 5: 0.64, 6: 0.63,
    7: 0.61, 8: 0.50, 9: 0.50, 10: 0.39, 11: 0.37, 12: 0.36,
    13: 0.21, 14: 0.15, 15: 0.06, 16: 0.01,
}


def get_team_features(conn, team_id, season):
    """Get all features for a team in a given season."""
    ts = conn.execute(
        "SELECT * FROM team_seasons WHERE team_id = ? AND season = ?",
        (team_id, season),
    ).fetchone()
    if not ts:
        return None
    return dict(ts)


def get_injury_impact(conn, team_id, season):
    """Return fraction of team scoring that is currently compromised by injuries.

    Looks up player_injuries for the team, weights each injured player's PPG
    contribution by severity, then divides by the team's total PPG from
    player_stats.  Returns 0.0 when no injury data exists (historical games).
    """
    from scraping.injury_scraper import STATUS_WEIGHTS

    injuries = conn.execute(
        """SELECT pi.player_name, pi.status, ps.ppg
           FROM player_injuries pi
           LEFT JOIN players p ON pi.player_id = p.player_id
           LEFT JOIN player_stats ps ON ps.player_id = p.player_id
               AND ps.team_id = pi.team_id AND ps.season = pi.season
           WHERE pi.team_id = ? AND pi.season = ?""",
        (team_id, season),
    ).fetchall()

    if not injuries:
        return 0.0

    team_total = conn.execute(
        """SELECT SUM(ppg) as total FROM player_stats
           WHERE team_id = ? AND season = ?""",
        (team_id, season),
    ).fetchone()
    total_ppg = (team_total["total"] or 0) if team_total else 0
    if total_ppg <= 0:
        return 0.0

    lost = sum(
        (row["ppg"] or 0) * STATUS_WEIGHTS.get(row["status"], 0.5)
        for row in injuries
    )
    return min(lost / total_ppg, 1.0)


def get_player_features(conn, team_id, season):
    """Compute aggregate player-based features for a team."""
    players = conn.execute(
        """SELECT ps.*, p.class_year, p.height_inches
           FROM player_stats ps
           JOIN players p ON ps.player_id = p.player_id
           WHERE ps.team_id = ? AND ps.season = ?
           ORDER BY ps.ppg DESC""",
        (team_id, season),
    ).fetchall()

    if not players:
        return {"top_scorer": 0, "experience": 0, "roster_depth": 0, "star_power": 0}

    players = [dict(p) for p in players]

    # Top scorer PPG
    top_scorer = players[0].get("ppg", 0) or 0

    # Experience: weighted by class year
    class_weights = {"FR": 1, "Fr": 1, "SO": 2, "So": 2, "JR": 3, "Jr": 3, "SR": 4, "Sr": 4}
    exp_scores = []
    for p in players:
        cy = p.get("class_year", "")
        w = class_weights.get(cy, 2) if cy else 2
        mpg = p.get("mpg", 0) or 0
        exp_scores.append(w * min(mpg / 40, 1))  # Weight by minutes
    experience = sum(exp_scores) / max(len(exp_scores), 1)

    # Roster depth: number of players averaging > 5 PPG
    roster_depth = sum(1 for p in players if (p.get("ppg") or 0) > 5)

    # Star power: sum of PPG for top 3 players
    star_power = sum(p.get("ppg", 0) or 0 for p in players[:3])

    return {
        "top_scorer": top_scorer,
        "experience": experience,
        "roster_depth": roster_depth,
        "star_power": star_power,
    }


def compute_distance(lat1, lon1, lat2, lon2):
    """Haversine distance in miles."""
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return None
    R = 3959  # Earth radius in miles
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def build_matchup_features(conn, team1_id, team2_id, season,
                           seed1=None, seed2=None,
                           spread=None, over_under=None,
                           venue_lat=None, venue_lon=None):
    """Build the full 29-feature vector for a matchup (team1 perspective).

    Returns numpy array of shape (29,) or None if insufficient data.
    """
    ts1 = get_team_features(conn, team1_id, season)
    ts2 = get_team_features(conn, team2_id, season)
    if not ts1 or not ts2:
        return None

    pf1 = get_player_features(conn, team1_id, season)
    pf2 = get_player_features(conn, team2_id, season)

    def diff(key, d1=ts1, d2=ts2):
        v1 = d1.get(key)
        v2 = d2.get(key)
        if v1 is None or v2 is None:
            return 0.0
        return float(v1) - float(v2)

    features = []

    # Efficiency differentials (14)
    for key in ["ortg", "drtg", "net_rtg", "pace", "srs", "sos",
                "efg_pct", "tov_pct", "orb_pct", "ft_rate",
                "three_par", "ts_pct", "osrs", "dsrs"]:
        features.append(diff(key))

    # Seed features (4)
    s1 = seed1 or 8  # Default to 8-seed if unknown
    s2 = seed2 or 8
    features.append(float(s1 - s2))                    # seed_diff
    features.append(float(s1 + s2))                    # seed_sum
    features.append(float(s1 * s2))                    # seed_product
    wr1 = SEED_WIN_RATES.get(s1, 0.5)
    wr2 = SEED_WIN_RATES.get(s2, 0.5)
    features.append(wr1 - wr2)                         # hist_seed_win_rate

    # Spread features (2)
    features.append(float(spread) if spread is not None else 0.0)
    features.append(float(over_under) if over_under is not None else 140.0)

    # Player features (4)
    features.append(pf1["top_scorer"] - pf2["top_scorer"])
    features.append(pf1["experience"] - pf2["experience"])
    features.append(pf1["roster_depth"] - pf2["roster_depth"])
    features.append(pf1["star_power"] - pf2["star_power"])

    # Injury impact (1) — positive means team2 is more hurt (good for team1)
    inj1 = get_injury_impact(conn, team1_id, season)
    inj2 = get_injury_impact(conn, team2_id, season)
    features.append(inj2 - inj1)

    # Record features (3)
    features.append(diff("win_pct"))
    features.append(diff("mov"))
    features.append(diff("away_win_pct"))

    # Location features (2)
    t1_loc = conn.execute(
        "SELECT latitude, longitude FROM teams WHERE team_id = ?", (team1_id,)
    ).fetchone()
    t2_loc = conn.execute(
        "SELECT latitude, longitude FROM teams WHERE team_id = ?", (team2_id,)
    ).fetchone()

    dist_adv = 0.0
    home_region = 0.0
    if venue_lat and venue_lon and t1_loc and t2_loc:
        d1 = compute_distance(t1_loc["latitude"], t1_loc["longitude"],
                              venue_lat, venue_lon)
        d2 = compute_distance(t2_loc["latitude"], t2_loc["longitude"],
                              venue_lat, venue_lon)
        if d1 is not None and d2 is not None:
            dist_adv = d2 - d1  # Positive = team1 closer
            home_region = 1.0 if d1 < 300 else 0.0
            home_region -= 1.0 if d2 < 300 else 0.0

    features.append(dist_adv)
    features.append(home_region)

    return np.array(features, dtype=np.float32)


def build_training_data(conn):
    """Build full training dataset from tournament games.

    Each game produces TWO samples (one from each team's perspective).
    Returns: features (N x 29), labels_win (N,), labels_margin (N,), seasons (N,)
    """
    games = conn.execute(
        """SELECT tg.*, ps.spread, ps.over_under
           FROM tournament_games tg
           LEFT JOIN point_spreads ps ON tg.game_id = ps.game_id"""
    ).fetchall()

    all_features = []
    all_win_labels = []
    all_margin_labels = []
    all_seasons = []

    for game in games:
        if game["winner_id"] is None:
            continue

        t1 = game["team1_id"]
        t2 = game["team2_id"]
        season = game["season"]
        s1 = game["seed1"]
        s2 = game["seed2"]
        spread = game["spread"]
        ou = game["over_under"]
        vlat = game["venue_lat"]
        vlon = game["venue_lon"]

        # Team1 perspective
        feat = build_matchup_features(
            conn, t1, t2, season, s1, s2, spread, ou, vlat, vlon
        )
        if feat is not None:
            win = 1.0 if game["winner_id"] == t1 else 0.0
            score1 = game["score1"] or 0
            score2 = game["score2"] or 0
            margin = float(score1 - score2)

            all_features.append(feat)
            all_win_labels.append(win)
            all_margin_labels.append(margin)
            all_seasons.append(season)

            # Team2 perspective (swap everything)
            feat2 = build_matchup_features(
                conn, t2, t1, season, s2, s1,
                -spread if spread is not None else None,
                ou, vlat, vlon
            )
            if feat2 is not None:
                all_features.append(feat2)
                all_win_labels.append(1.0 - win)
                all_margin_labels.append(-margin)
                all_seasons.append(season)

    if not all_features:
        return None, None, None, None

    return (
        np.array(all_features, dtype=np.float32),
        np.array(all_win_labels, dtype=np.float32),
        np.array(all_margin_labels, dtype=np.float32),
        np.array(all_seasons, dtype=np.int32),
    )
