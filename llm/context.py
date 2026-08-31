"""Grounding layer: turn the database and the model into context packs.

Nothing here calls an LLM. These functions assemble compact, deterministic
dicts of *facts* — team stats, roster aggregates, injuries, tournament history,
the network's own prediction, and which model inputs drove it. Every number the
analyst is allowed to state comes from one of these packs, which is what keeps
the writeups honest.

Keys are emitted in a stable order so identical inputs hash to the same cache
key and the prompt prefix stays cacheable.
"""

import math

from config import CURRENT_SEASON, FEATURE_NAMES
from features.feature_engineering import (
    get_injury_impact,
    get_player_features,
    get_team_features,
)
from features.matchup_features import predict_matchup_features

# How a positive feature difference should be read.
#   1  -> a higher value favors team 1
#  -1  -> a lower value favors team 1
#   0  -> context only, favors neither side
FEATURE_POLARITY = {
    "ORtg_diff": 1, "DRtg_diff": -1, "NetRtg_diff": 1, "Pace_diff": 0,
    "SRS_diff": 1, "SOS_diff": 1, "eFG%_diff": 1, "TOV%_diff": -1,
    "ORB%_diff": 1, "FTr_diff": 1, "3PAr_diff": 0, "TS%_diff": 1,
    "OSRS_diff": 1, "DSRS_diff": 1,
    "seed_diff": -1, "seed_sum": 0, "seed_product": 0, "hist_seed_win_rate": 1,
    # Spread is quoted from team 1's perspective, so a negative number means
    # team 1 is favored.
    "spread": -1, "over_under": 0,
    "top_scorer_diff": 1, "experience_diff": 1, "roster_depth_diff": 1,
    "star_power_diff": 1,
    # Built as (team2 injury impact - team1 injury impact): positive means the
    # opponent is the more banged-up side.
    "injury_impact_diff": 1,
    "win_pct_diff": 1, "MOV_diff": 1, "away_win_pct_diff": 1,
    "distance_adv_diff": 1, "home_region_flag": 1,
}

# Plain-English labels so the analyst does not have to decode column names.
FEATURE_LABELS = {
    "ORtg_diff": "offensive efficiency",
    "DRtg_diff": "defensive efficiency (lower is better)",
    "NetRtg_diff": "net rating",
    "Pace_diff": "tempo",
    "SRS_diff": "simple rating system",
    "SOS_diff": "strength of schedule",
    "eFG%_diff": "effective field goal %",
    "TOV%_diff": "turnover rate (lower is better)",
    "ORB%_diff": "offensive rebound rate",
    "FTr_diff": "free throw rate",
    "3PAr_diff": "three-point attempt rate",
    "TS%_diff": "true shooting %",
    "OSRS_diff": "offensive SRS",
    "DSRS_diff": "defensive SRS",
    "seed_diff": "seed line (lower is better)",
    "seed_sum": "combined seed",
    "seed_product": "seed product",
    "hist_seed_win_rate": "historical win rate for this seed line",
    "spread": "synthetic point spread (negative favors team 1)",
    "over_under": "projected total points",
    "top_scorer_diff": "leading scorer PPG",
    "experience_diff": "roster experience",
    "roster_depth_diff": "roster depth (players above 5 PPG)",
    "star_power_diff": "combined PPG of the top three scorers",
    "injury_impact_diff": "injury damage (positive means the opponent is more hurt)",
    "win_pct_diff": "win percentage",
    "MOV_diff": "margin of victory",
    "away_win_pct_diff": "road win percentage",
    "distance_adv_diff": "travel distance advantage",
    "home_region_flag": "near-home venue advantage",
}

TEAM_STAT_GROUPS = {
    "record": ["wins", "losses", "win_pct", "mov"],
    "scoring": ["ppg", "opp_ppg"],
    "efficiency": ["ortg", "drtg", "net_rtg", "pace", "srs", "sos", "osrs", "dsrs"],
    "shooting": ["efg_pct", "ts_pct", "fg_pct", "fg3_pct", "ft_pct",
                 "three_par", "ft_rate"],
    "possession": ["tov_pct", "orb_pct", "trb_per_game", "ast_per_game",
                   "stl_per_game", "blk_per_game", "tov_per_game"],
    "defense_allowed": ["opp_efg_pct", "opp_tov_pct", "opp_orb_pct", "opp_ft_rate"],
}


def _round(value, places=2):
    """Round floats for the prompt; pass through anything else."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, places)
    return value


def _drop_nulls(mapping):
    """Strip keys with no value — a missing stat should be absent, not null."""
    return {k: v for k, v in mapping.items() if v is not None}


def team_summary(conn, team_id, season=None):
    """One-line identity for a team: id, name, conference, seed and region."""
    season = season or CURRENT_SEASON
    row = conn.execute(
        "SELECT team_id, school_name, conference FROM teams WHERE team_id = ?",
        (team_id,),
    ).fetchone()
    if not row:
        return None

    summary = _drop_nulls({
        "team_id": row["team_id"],
        "name": row["school_name"],
        "conference": row["conference"],
        "season": season,
    })

    entry = conn.execute(
        "SELECT seed, region FROM tournament_results WHERE team_id = ? AND season = ?",
        (team_id, season),
    ).fetchone()
    if entry:
        summary["seed"] = entry["seed"]
        summary["region"] = entry["region"]
    return summary


def top_players(conn, team_id, season, limit=6):
    """Leading scorers with their per-game line."""
    rows = conn.execute(
        """SELECT p.name, p.class_year, p.position,
                  ps.games, ps.mpg, ps.ppg, ps.rpg, ps.apg, ps.ts_pct
           FROM player_stats ps
           JOIN players p ON ps.player_id = p.player_id
           WHERE ps.team_id = ? AND ps.season = ?
           ORDER BY ps.ppg DESC
           LIMIT ?""",
        (team_id, season, limit),
    ).fetchall()
    return [
        _drop_nulls({
            "name": r["name"],
            "class": r["class_year"],
            "position": r["position"],
            "games": r["games"],
            "mpg": _round(r["mpg"], 1),
            "ppg": _round(r["ppg"], 1),
            "rpg": _round(r["rpg"], 1),
            "apg": _round(r["apg"], 1),
            "ts_pct": _round(r["ts_pct"], 3),
        })
        for r in rows
    ]


def injuries(conn, team_id, season):
    """Current injury report rows for a team."""
    rows = conn.execute(
        """SELECT player_name, status, injury_type
           FROM player_injuries
           WHERE team_id = ? AND season = ?
           ORDER BY player_name""",
        (team_id, season),
    ).fetchall()
    return [
        {
            "player": r["player_name"],
            "status": r["status"],
            "injury": r["injury_type"],
        }
        for r in rows
    ]


def tournament_history(conn, team_id, limit=8):
    """Recent NCAA tournament appearances, newest first."""
    rows = conn.execute(
        """SELECT season, seed, region, round_reached
           FROM tournament_results
           WHERE team_id = ?
           ORDER BY season DESC
           LIMIT ?""",
        (team_id, limit),
    ).fetchall()
    return [
        _drop_nulls({
            "season": r["season"],
            "seed": r["seed"],
            "region": r["region"],
            "round_reached": r["round_reached"],
        })
        for r in rows
    ]


def team_pack(conn, team_id, season=None, include_history=True):
    """Everything the analyst may say about one team, and nothing else."""
    season = season or CURRENT_SEASON
    summary = team_summary(conn, team_id, season)
    if summary is None:
        return None

    stats = get_team_features(conn, team_id, season)
    pack = {"team": summary}

    if stats:
        for group, keys in TEAM_STAT_GROUPS.items():
            values = _drop_nulls({k: _round(stats.get(k), 3) for k in keys})
            if values:
                pack[group] = values
    else:
        pack["stats_available"] = False

    roster = get_player_features(conn, team_id, season)
    pack["roster"] = _drop_nulls({
        "top_scorer_ppg": _round(roster["top_scorer"], 1),
        "star_power_ppg": _round(roster["star_power"], 1),
        "roster_depth": roster["roster_depth"],
        "experience_score": _round(roster["experience"], 2),
        "leaders": top_players(conn, team_id, season),
    })

    pack["injuries"] = {
        "impact_share_of_scoring": _round(get_injury_impact(conn, team_id, season), 3),
        "report": injuries(conn, team_id, season),
    }

    if include_history:
        pack["tournament_history"] = tournament_history(conn, team_id)

    return pack


def key_factors(predictor, features, team1_name, team2_name, limit=8):
    """Rank the model inputs that most separate these two teams.

    Standardizing the raw differences with the checkpoint's own mean/std is what
    makes them comparable: a 6-point ORtg edge and a 3-seed gap land on the same
    scale, so "biggest factor" means biggest relative to how this feature varies
    across the training set.
    """
    if features is None:
        return []

    mean = predictor.mean
    std = predictor.std
    factors = []

    for idx, name in enumerate(FEATURE_NAMES):
        if idx >= len(features):
            break
        polarity = FEATURE_POLARITY.get(name, 0)
        if polarity == 0:
            # Tempo, shot profile and seed sums are context, not an edge for
            # either side; the team profiles carry them for style commentary.
            continue

        raw = float(features[idx])
        z = (raw - float(mean[idx])) / float(std[idx])

        if raw == 0:
            favors = "neither"
        elif (raw > 0) == (polarity > 0):
            favors = team1_name
        else:
            favors = team2_name

        factors.append({
            "feature": name,
            "means": FEATURE_LABELS.get(name, name),
            "difference": _round(raw, 3),
            "standardized": _round(z, 2),
            "favors": favors,
        })

    factors.sort(key=lambda f: abs(f["standardized"] or 0), reverse=True)
    return factors[:limit]


def matchup_pack(conn, predictor, team1_id, team2_id,
                 seed1=None, seed2=None, season=None, round_name=None):
    """Model prediction plus both team packs and the drivers behind it."""
    season = season or CURRENT_SEASON
    pack1 = team_pack(conn, team1_id, season)
    pack2 = team_pack(conn, team2_id, season)
    if pack1 is None or pack2 is None:
        return None

    name1 = pack1["team"]["name"]
    name2 = pack2["team"]["name"]

    result = predictor.predict(
        conn, team1_id, team2_id, seed1=seed1, seed2=seed2, season=season
    )
    win_prob = result["win_prob"]
    favorite = name1 if win_prob >= 0.5 else name2

    features = predict_matchup_features(
        conn, team1_id, team2_id, seed1=seed1, seed2=seed2, season=season
    )

    return {
        "matchup": {
            "team1": name1,
            "team2": name2,
            "seed1": seed1 if seed1 is not None else pack1["team"].get("seed"),
            "seed2": seed2 if seed2 is not None else pack2["team"].get("seed"),
            "round": round_name,
            "season": season,
        },
        "model_prediction": {
            "win_prob_team1": _round(win_prob, 4),
            "win_prob_team2": _round(1 - win_prob, 4),
            "favorite": favorite,
            "predicted_margin_for_favorite": _round(abs(result["margin"]), 1),
            "confidence": result["confidence"],
        },
        "key_factors": key_factors(predictor, features, name1, name2),
        "team1_profile": pack1,
        "team2_profile": pack2,
    }


def bracket_pack(games, odds=None, season=None, top_n=12):
    """Summarize a simulated bracket: the chalk, the upsets, and the odds.

    `games` is the list returned by TournamentSimulator.simulate_deterministic;
    `odds` is the dict returned by simulate_monte_carlo.
    """
    season = season or CURRENT_SEASON
    picks = []
    upsets = []
    close_calls = []

    for game in games:
        t1, t2 = game["team1"], game["team2"]
        winner = game["winner"]
        loser = t2 if winner is t1 else t1
        entry = {
            "round": game["round"],
            "region": game["region"],
            "winner": f"({winner.seed}) {winner.name}",
            "loser": f"({loser.seed}) {loser.name}",
            "win_prob": _round(game["win_prob"], 3),
            "margin": _round(game["margin"], 1),
        }
        picks.append(entry)

        if (winner.seed or 0) > (loser.seed or 0):
            upsets.append(dict(entry, seed_gap=winner.seed - loser.seed))
        if abs((game["win_prob"] or 0.5) - 0.5) < 0.06:
            close_calls.append(entry)

    upsets.sort(key=lambda u: u["seed_gap"], reverse=True)

    pack = {
        "season": season,
        "champion": picks[-1]["winner"] if picks else None,
        "picks": picks,
        "biggest_upsets": upsets[:top_n],
        "coin_flip_games": close_calls[:top_n],
    }

    if odds:
        ranked = sorted(
            odds.values(), key=lambda o: o["championship_pct"], reverse=True
        )[:top_n]
        pack["championship_odds"] = [
            {
                "team": f"({o['team'].seed}) {o['team'].name}",
                "championship_pct": _round(o["championship_pct"], 2),
                "final_four_pct": _round(o["final_four_pct"], 2),
                "elite_eight_pct": _round(o["elite_eight_pct"], 2),
                "sweet_sixteen_pct": _round(o["sweet_sixteen_pct"], 2),
            }
            for o in ranked
        ]

    return pack
