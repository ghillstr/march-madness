"""Tournament simulation: deterministic and Monte Carlo modes."""

import random
from collections import defaultdict

from bracket.bracket_logic import Bracket, REGIONS, ROUND_NAMES, FIRST_ROUND_MATCHUPS
from model.predict import Predictor
from config import MC_SIMULATIONS


class TournamentSimulator:
    """Simulate the full NCAA tournament."""

    def __init__(self, predictor, conn):
        self.predictor = predictor
        self.conn = conn

    def predict_game(self, team1, team2):
        """Get prediction for a single game."""
        # TBD placeholder (First Four winner not yet known): real team auto-wins
        if team1.team_id == -1:
            return {"win_prob": 0.0, "margin": -10.0}
        if team2.team_id == -1:
            return {"win_prob": 1.0, "margin": 10.0}
        result = self.predictor.predict(
            self.conn, team1.team_id, team2.team_id,
            seed1=team1.seed, seed2=team2.seed,
        )
        return result

    def simulate_deterministic(self, bracket):
        """Simulate bracket picking the higher-probability winner each game.

        Returns list of (round, team1, team2, winner, win_prob, margin).
        """
        all_games = []

        # Simulate each region through Elite 8
        final_four = []
        for region in REGIONS:
            matchups = bracket.get_first_round_matchups(region)
            round_teams = matchups  # List of (team1, team2) pairs

            for round_idx, round_name in enumerate(ROUND_NAMES[:4]):
                next_round = []
                for t1, t2 in round_teams:
                    result = self.predict_game(t1, t2)
                    wp = result["win_prob"]
                    margin = result["margin"]

                    if wp >= 0.5:
                        winner = t1
                    else:
                        winner = t2
                        wp = 1 - wp
                        margin = -margin

                    all_games.append({
                        "round": round_name,
                        "region": region,
                        "team1": t1,
                        "team2": t2,
                        "winner": winner,
                        "win_prob": wp if winner == t1 else 1 - result["win_prob"],
                        "margin": abs(margin),
                    })
                    next_round.append(winner)

                # Pair winners for next round
                round_teams = []
                for i in range(0, len(next_round), 2):
                    if i + 1 < len(next_round):
                        round_teams.append((next_round[i], next_round[i + 1]))

            if round_teams:
                final_four.append(round_teams[0][0] if len(round_teams[0]) == 2
                                  else round_teams[0])
            elif next_round:
                final_four.append(next_round[0])

        # Final Four
        if len(final_four) >= 4:
            # East(0) vs South(2) on the left; West(1) vs Midwest(3) on the right
            ff_matchups = [(final_four[0], final_four[2]),
                           (final_four[1], final_four[3])]
        elif len(final_four) >= 2:
            ff_matchups = [(final_four[0], final_four[1])]
        else:
            return all_games

        championship_teams = []
        for t1, t2 in ff_matchups:
            result = self.predict_game(t1, t2)
            wp = result["win_prob"]
            winner = t1 if wp >= 0.5 else t2

            all_games.append({
                "round": "Final Four",
                "region": "Final Four",
                "team1": t1,
                "team2": t2,
                "winner": winner,
                "win_prob": wp if winner == t1 else 1 - wp,
                "margin": abs(result["margin"]),
            })
            championship_teams.append(winner)

        # Championship
        if len(championship_teams) == 2:
            t1, t2 = championship_teams
            result = self.predict_game(t1, t2)
            wp = result["win_prob"]
            winner = t1 if wp >= 0.5 else t2

            all_games.append({
                "round": "Championship",
                "region": "Championship",
                "team1": t1,
                "team2": t2,
                "winner": winner,
                "win_prob": wp if winner == t1 else 1 - wp,
                "margin": abs(result["margin"]),
            })

        return all_games

    def simulate_random(self, bracket):
        """Single random bracket using win probabilities as coin-flip weights.

        Returns same structure as simulate_deterministic but with random outcomes.
        """
        all_games = []
        final_four = []

        for region in REGIONS:
            matchups = bracket.get_first_round_matchups(region)
            round_teams = matchups

            for round_name in ROUND_NAMES[:4]:
                next_round = []
                for t1, t2 in round_teams:
                    result = self.predict_game(t1, t2)
                    wp = result["win_prob"]
                    winner = t1 if random.random() < wp else t2
                    actual_wp = wp if winner == t1 else 1 - wp

                    all_games.append({
                        "round": round_name,
                        "region": region,
                        "team1": t1,
                        "team2": t2,
                        "winner": winner,
                        "win_prob": actual_wp,
                        "margin": abs(result["margin"]),
                    })
                    next_round.append(winner)

                round_teams = [(next_round[i], next_round[i+1])
                               for i in range(0, len(next_round) - 1, 2)]

            if round_teams:
                final_four.append(round_teams[0][0])
            elif next_round:
                final_four.append(next_round[0])

        if len(final_four) >= 4:
            ff_matchups = [(final_four[0], final_four[2]),
                           (final_four[1], final_four[3])]
        elif len(final_four) >= 2:
            ff_matchups = [(final_four[0], final_four[1])]
        else:
            return all_games

        championship_teams = []
        for t1, t2 in ff_matchups:
            result = self.predict_game(t1, t2)
            wp = result["win_prob"]
            winner = t1 if random.random() < wp else t2
            all_games.append({
                "round": "Final Four",
                "region": "Final Four",
                "team1": t1, "team2": t2, "winner": winner,
                "win_prob": wp if winner == t1 else 1 - wp,
                "margin": abs(result["margin"]),
            })
            championship_teams.append(winner)

        if len(championship_teams) == 2:
            t1, t2 = championship_teams
            result = self.predict_game(t1, t2)
            wp = result["win_prob"]
            winner = t1 if random.random() < wp else t2
            all_games.append({
                "round": "Championship",
                "region": "Championship",
                "team1": t1, "team2": t2, "winner": winner,
                "win_prob": wp if winner == t1 else 1 - wp,
                "margin": abs(result["margin"]),
            })

        return all_games

    def simulate_forced_champion(self, bracket, champion_name, seed=None):
        """Simulate a bracket where the named team always wins their games.

        Other games are decided randomly using win probabilities.
        """
        import random as _random
        if seed is not None:
            _random.seed(seed)

        all_games = []
        final_four = []

        for region in REGIONS:
            matchups = bracket.get_first_round_matchups(region)
            round_teams = matchups

            for round_name in ROUND_NAMES[:4]:
                next_round = []
                for t1, t2 in round_teams:
                    result = self.predict_game(t1, t2)
                    wp = result["win_prob"]
                    # Force the named champion to always win
                    if champion_name.lower() in t1.name.lower():
                        winner, actual_wp = t1, max(wp, 0.99)
                    elif champion_name.lower() in t2.name.lower():
                        winner, actual_wp = t2, max(1 - wp, 0.99)
                    else:
                        winner = t1 if _random.random() < wp else t2
                        actual_wp = wp if winner == t1 else 1 - wp

                    all_games.append({
                        "round": round_name,
                        "region": region,
                        "team1": t1, "team2": t2, "winner": winner,
                        "win_prob": actual_wp,
                        "margin": abs(result["margin"]),
                    })
                    next_round.append(winner)

                round_teams = [(next_round[i], next_round[i+1])
                               for i in range(0, len(next_round) - 1, 2)]

            if round_teams:
                final_four.append(round_teams[0][0])
            elif next_round:
                final_four.append(next_round[0])

        if len(final_four) < 2:
            return all_games

        ff_matchups = [(final_four[0], final_four[2]), (final_four[1], final_four[3])] \
                      if len(final_four) >= 4 else [(final_four[0], final_four[1])]

        championship_teams = []
        for t1, t2 in ff_matchups:
            result = self.predict_game(t1, t2)
            wp = result["win_prob"]
            if champion_name.lower() in t1.name.lower():
                winner, actual_wp = t1, max(wp, 0.99)
            elif champion_name.lower() in t2.name.lower():
                winner, actual_wp = t2, max(1 - wp, 0.99)
            else:
                winner = t1 if _random.random() < wp else t2
                actual_wp = wp if winner == t1 else 1 - wp
            all_games.append({
                "round": "Final Four", "region": "Final Four",
                "team1": t1, "team2": t2, "winner": winner,
                "win_prob": actual_wp, "margin": abs(result["margin"]),
            })
            championship_teams.append(winner)

        if len(championship_teams) == 2:
            t1, t2 = championship_teams
            result = self.predict_game(t1, t2)
            wp = result["win_prob"]
            if champion_name.lower() in t1.name.lower():
                winner, actual_wp = t1, max(wp, 0.99)
            elif champion_name.lower() in t2.name.lower():
                winner, actual_wp = t2, max(1 - wp, 0.99)
            else:
                winner = t1 if _random.random() < wp else t2
                actual_wp = wp if winner == t1 else 1 - wp
            all_games.append({
                "round": "Championship", "region": "Championship",
                "team1": t1, "team2": t2, "winner": winner,
                "win_prob": actual_wp, "margin": abs(result["margin"]),
            })

        return all_games

    def simulate_monte_carlo(self, bracket, n_sims=None):
        """Run Monte Carlo simulations using probabilities as coin flips.

        Returns dict of team_id -> {
            'team': BracketTeam,
            'championship_pct': float,
            'final_four_pct': float,
            'elite_eight_pct': float,
            'sweet_sixteen_pct': float,
        }
        """
        n_sims = n_sims or MC_SIMULATIONS
        round_counts = defaultdict(lambda: defaultdict(int))

        # Cache predictions to avoid recomputing
        pred_cache = {}

        def get_cached_pred(t1_id, t2_id, s1, s2):
            key = (t1_id, t2_id)
            if key not in pred_cache:
                result = self.predictor.predict(
                    self.conn, t1_id, t2_id, seed1=s1, seed2=s2
                )
                pred_cache[key] = result["win_prob"]
            return pred_cache[key]

        for sim in range(n_sims):
            # Simulate each region
            final_four = []
            for region in REGIONS:
                matchups = bracket.get_first_round_matchups(region)
                round_teams = matchups

                for round_idx, round_name in enumerate(ROUND_NAMES[:4]):
                    next_round = []
                    for t1, t2 in round_teams:
                        wp = get_cached_pred(t1.team_id, t2.team_id,
                                             t1.seed, t2.seed)
                        winner = t1 if random.random() < wp else t2
                        round_counts[round_name][winner.team_id] += 1
                        next_round.append(winner)

                    round_teams = []
                    for i in range(0, len(next_round), 2):
                        if i + 1 < len(next_round):
                            round_teams.append((next_round[i], next_round[i + 1]))

                if next_round:
                    final_four.append(next_round[-1] if not round_teams else
                                      round_teams[0][0])

            # Final Four + Championship
            if len(final_four) >= 4:
                for team in final_four:
                    round_counts["Final Four"][team.team_id] += 1

                # Semis: East(0) vs South(2), West(1) vs Midwest(3)
                wp1 = get_cached_pred(final_four[0].team_id, final_four[2].team_id,
                                      final_four[0].seed, final_four[2].seed)
                f1 = final_four[0] if random.random() < wp1 else final_four[2]

                wp2 = get_cached_pred(final_four[1].team_id, final_four[3].team_id,
                                      final_four[1].seed, final_four[3].seed)
                f2 = final_four[1] if random.random() < wp2 else final_four[3]

                # Championship
                wp_final = get_cached_pred(f1.team_id, f2.team_id, f1.seed, f2.seed)
                champ = f1 if random.random() < wp_final else f2
                round_counts["Championship"][champ.team_id] += 1

        # Convert to percentages
        results = {}
        all_teams = bracket.get_all_teams()
        for team in all_teams:
            tid = team.team_id
            results[tid] = {
                "team": team,
                "championship_pct": round_counts["Championship"].get(tid, 0) / n_sims * 100,
                "final_four_pct": round_counts["Final Four"].get(tid, 0) / n_sims * 100,
                "elite_eight_pct": round_counts["Elite 8"].get(tid, 0) / n_sims * 100,
                "sweet_sixteen_pct": round_counts["Sweet 16"].get(tid, 0) / n_sims * 100,
            }

        return results
