"""Generate synthetic point spreads from SRS differentials."""

from scraping.base_scraper import BaseScraper


class OddsScraper(BaseScraper):
    """Generate synthetic spreads using SRS (Simple Rating System).

    SRS correlates with Vegas lines at r > 0.90, so SRS differential
    is a strong proxy for point spreads.
    """

    def generate_spreads(self, conn):
        """Generate synthetic spreads for all tournament games."""
        print("\n[Spreads] Generating synthetic spreads from SRS...")

        games = conn.execute(
            """SELECT tg.game_id, tg.season, tg.team1_id, tg.team2_id,
                      ts1.srs AS srs1, ts2.srs AS srs2,
                      ts1.ppg AS ppg1, ts2.ppg AS ppg2,
                      ts1.opp_ppg AS opp_ppg1, ts2.opp_ppg AS opp_ppg2,
                      ts1.pace AS pace1, ts2.pace AS pace2
               FROM tournament_games tg
               LEFT JOIN team_seasons ts1 ON tg.team1_id = ts1.team_id AND tg.season = ts1.season
               LEFT JOIN team_seasons ts2 ON tg.team2_id = ts2.team_id AND tg.season = ts2.season"""
        ).fetchall()

        count = 0
        for game in games:
            srs1 = game["srs1"]
            srs2 = game["srs2"]

            if srs1 is None or srs2 is None:
                continue

            # Spread: negative means team1 is favored
            spread = srs2 - srs1  # team1 perspective

            # Over/under: estimate from pace and scoring
            over_under = None
            ppg1 = game["ppg1"]
            ppg2 = game["ppg2"]
            if ppg1 and ppg2:
                # Simple estimate: average of both teams' PPG * tournament pace factor
                over_under = (ppg1 + ppg2) * 0.97  # Tournament games slightly slower

            existing = conn.execute(
                "SELECT id FROM point_spreads WHERE game_id = ?",
                (game["game_id"],),
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE point_spreads SET spread = ?, over_under = ? WHERE id = ?",
                    (spread, over_under, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO point_spreads
                       (game_id, season, team1_id, team2_id, spread, over_under, is_synthetic)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (game["game_id"], game["season"],
                     game["team1_id"], game["team2_id"],
                     spread, over_under),
                )
            count += 1

        conn.commit()
        print(f"  Generated {count} synthetic spreads")
        return count
