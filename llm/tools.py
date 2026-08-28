"""Tools the chat analyst can call.

Each tool reads the same database the app reads and, where relevant, runs the
same trained network the pages run — so a chat answer and a page answer can
never disagree. Tools return JSON strings; a failed lookup returns an
explanatory JSON object rather than raising, so the model can recover.

The `@beta_tool` decorator builds each schema from the signature and docstring,
so argument descriptions below are part of the API contract.
"""

import functools
import json
import os

from anthropic import beta_tool

from config import CURRENT_SEASON, MODEL_DIR
from db.database import get_db, get_team_id_by_name
from llm import context

# Monte Carlo runs are slow; memoize per (season, n_sims) for the session.
_ODDS_CACHE = {}


def _json(payload):
    return json.dumps(payload, sort_keys=True, default=str)


def _error(message, **extra):
    return _json(dict({"error": message}, **extra))


@functools.lru_cache(maxsize=1)
def _get_predictor():
    """Load the trained network once per process."""
    from model.predict import Predictor

    return Predictor()


def _model_ready():
    return os.path.exists(os.path.join(MODEL_DIR, "best_model.pt"))


def _resolve(conn, name):
    """Map a school name to (team_id, canonical name), or (None, None)."""
    team_id = get_team_id_by_name(conn, name)
    if team_id is None:
        return None, None
    row = conn.execute(
        "SELECT school_name FROM teams WHERE team_id = ?", (team_id,)
    ).fetchone()
    return team_id, (row["school_name"] if row else name)


@beta_tool
def search_teams(query: str, season: int = CURRENT_SEASON) -> str:
    """Find teams whose school name matches a search string.

    Use this first when you are unsure how a school is spelled in the database
    (for example "UConn" is stored as "Connecticut"). Returns matching school
    names with conference, and the seed and region if the team is in that
    season's tournament field.

    Args:
        query: Part of a school name, e.g. "Duke" or "State".
        season: Season to report seeding for. Defaults to the current season.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT team_id, school_name, conference FROM teams
               WHERE school_name LIKE ? ORDER BY school_name LIMIT 25""",
            (f"%{query}%",),
        ).fetchall()
        if not rows:
            return _error(f"No team matches '{query}'.")
        results = []
        for r in rows:
            entry = {
                "team_id": r["team_id"],
                "name": r["school_name"],
                "conference": r["conference"],
            }
            field = conn.execute(
                """SELECT seed, region FROM tournament_results
                   WHERE team_id = ? AND season = ?""",
                (r["team_id"], season),
            ).fetchone()
            if field:
                entry["seed"] = field["seed"]
                entry["region"] = field["region"]
            results.append(entry)
    return _json({"season": season, "matches": results})


@beta_tool
def get_team_stats(team_name: str, season: int = CURRENT_SEASON) -> str:
    """Get a team's full season profile.

    Returns record, scoring, efficiency (ORtg/DRtg/pace/SRS/SOS), shooting,
    possession and defensive stats, the leading scorers with their per-game
    lines, the injury report, and recent tournament appearances.

    Args:
        team_name: School name, e.g. "Duke".
        season: Season to look up. Defaults to the current season.
    """
    with get_db() as conn:
        team_id, name = _resolve(conn, team_name)
        if team_id is None:
            return _error(f"No team named '{team_name}'. Try search_teams.")
        pack = context.team_pack(conn, team_id, season)
    if pack is None:
        return _error(f"No data for {name} in {season}.")
    return _json(pack)


@beta_tool
def compare_teams(team1: str, team2: str, season: int = CURRENT_SEASON) -> str:
    """Compare two teams' season stats side by side, without predicting.

    Use predict_matchup instead when the question is who would win.

    Args:
        team1: First school name.
        team2: Second school name.
        season: Season to compare. Defaults to the current season.
    """
    with get_db() as conn:
        id1, name1 = _resolve(conn, team1)
        id2, name2 = _resolve(conn, team2)
        if id1 is None:
            return _error(f"No team named '{team1}'. Try search_teams.")
        if id2 is None:
            return _error(f"No team named '{team2}'. Try search_teams.")
        pack1 = context.team_pack(conn, id1, season, include_history=False)
        pack2 = context.team_pack(conn, id2, season, include_history=False)
    if pack1 is None or pack2 is None:
        return _error(f"Missing {season} data for one of these teams.")
    return _json({"season": season, name1: pack1, name2: pack2})


@beta_tool
def predict_matchup(team1: str, team2: str,
                    seed1: int = 0, seed2: int = 0,
                    season: int = CURRENT_SEASON) -> str:
    """Run the trained neural network on a head-to-head matchup.

    This is the app's actual model, not an estimate. Returns the win probability
    for each side, the predicted margin, the model's confidence label, and the
    ranked model inputs driving the result (with standardized values showing how
    unusual each edge is).

    Args:
        team1: First school name.
        team2: Second school name.
        seed1: Tournament seed for team1, 1-16. Pass 0 to use the team's real
            seed if it is in the field, or the model's neutral default.
        seed2: Tournament seed for team2, 1-16. Pass 0 as above.
        season: Season to predict for. Defaults to the current season.
    """
    if not _model_ready():
        return _error("No trained model is available. Run model/train.py first.")

    with get_db() as conn:
        id1, name1 = _resolve(conn, team1)
        id2, name2 = _resolve(conn, team2)
        if id1 is None:
            return _error(f"No team named '{team1}'. Try search_teams.")
        if id2 is None:
            return _error(f"No team named '{team2}'. Try search_teams.")

        s1 = seed1 or None
        s2 = seed2 or None
        if s1 is None or s2 is None:
            for team_id, current in ((id1, "s1"), (id2, "s2")):
                row = conn.execute(
                    """SELECT seed FROM tournament_results
                       WHERE team_id = ? AND season = ?""",
                    (team_id, season),
                ).fetchone()
                if row and row["seed"]:
                    if current == "s1" and s1 is None:
                        s1 = row["seed"]
                    elif current == "s2" and s2 is None:
                        s2 = row["seed"]

        try:
            predictor = _get_predictor()
        except FileNotFoundError as exc:
            return _error(str(exc))

        pack = context.matchup_pack(
            conn, predictor, id1, id2, seed1=s1, seed2=s2, season=season
        )

    if pack is None:
        return _error(f"Not enough {season} data to predict {name1} vs {name2}.")

    # Trim the full team profiles: the caller can pull those with
    # get_team_stats if it needs them, and this keeps the tool result small.
    return _json({
        "matchup": pack["matchup"],
        "model_prediction": pack["model_prediction"],
        "key_factors": pack["key_factors"],
    })


@beta_tool
def team_tournament_history(team_name: str, limit: int = 10) -> str:
    """Get a team's NCAA tournament appearances, newest first.

    Returns the season, seed, region and round reached for each appearance in
    the database (2014 onward).

    Args:
        team_name: School name, e.g. "Gonzaga".
        limit: Maximum number of appearances to return.
    """
    with get_db() as conn:
        team_id, name = _resolve(conn, team_name)
        if team_id is None:
            return _error(f"No team named '{team_name}'. Try search_teams.")
        history = context.tournament_history(conn, team_id, limit=limit)
    if not history:
        return _json({"team": name, "appearances": [],
                      "note": "No tournament appearances on record."})
    return _json({"team": name, "appearances": history})


@beta_tool
def list_injuries(team_name: str, season: int = CURRENT_SEASON) -> str:
    """Get the current injury report for a team.

    Also returns the share of the team's scoring that is compromised, which is
    the value the model actually consumes as a feature.

    Args:
        team_name: School name.
        season: Season to look up. Defaults to the current season.
    """
    with get_db() as conn:
        team_id, name = _resolve(conn, team_name)
        if team_id is None:
            return _error(f"No team named '{team_name}'. Try search_teams.")
        report = context.injuries(conn, team_id, season)
        impact = context.get_injury_impact(conn, team_id, season)
    return _json({
        "team": name,
        "season": season,
        "injuries": report,
        "impact_share_of_scoring": round(impact, 3),
        "note": "An empty list means no injuries have been scraped for this team.",
    })


@beta_tool
def championship_odds(top_n: int = 10, n_sims: int = 2000,
                      season: int = CURRENT_SEASON) -> str:
    """Run Monte Carlo bracket simulations and return championship odds.

    Simulates the full tournament repeatedly using the network's win
    probabilities as weighted coin flips, and returns the teams with the best
    title odds along with their Final Four, Elite Eight and Sweet 16 rates.
    Results are approximate and vary slightly between runs.

    Args:
        top_n: How many teams to return, ranked by title odds.
        n_sims: Number of simulations. More is more stable but slower.
        season: Season to simulate. Defaults to the current season.
    """
    if not _model_ready():
        return _error("No trained model is available. Run model/train.py first.")

    key = (season, n_sims)
    if key not in _ODDS_CACHE:
        from bracket.bracket_logic import Bracket
        from bracket.simulator import TournamentSimulator

        with get_db() as conn:
            bracket = Bracket()
            bracket.load_from_db(conn, season)
            if not bracket.get_all_teams():
                return _error(f"No {season} tournament field in the database.")
            simulator = TournamentSimulator(_get_predictor(), conn)
            odds = simulator.simulate_monte_carlo(bracket, n_sims=n_sims)

        _ODDS_CACHE[key] = [
            {
                "team": o["team"].name,
                "seed": o["team"].seed,
                "region": o["team"].region,
                "championship_pct": round(o["championship_pct"], 2),
                "final_four_pct": round(o["final_four_pct"], 2),
                "elite_eight_pct": round(o["elite_eight_pct"], 2),
                "sweet_sixteen_pct": round(o["sweet_sixteen_pct"], 2),
            }
            for o in sorted(odds.values(),
                            key=lambda o: o["championship_pct"], reverse=True)
        ]

    return _json({
        "season": season,
        "simulations": n_sims,
        "odds": _ODDS_CACHE[key][:top_n],
    })


ALL_TOOLS = [
    search_teams,
    get_team_stats,
    compare_teams,
    predict_matchup,
    team_tournament_history,
    list_injuries,
    championship_odds,
]
