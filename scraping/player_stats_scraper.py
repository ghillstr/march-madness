"""Scraper for per-school player stats from Sports Reference."""

import re
from scraping.base_scraper import BaseScraper
from db.database import get_or_create_team
from config import SR_SCHOOLS


class PlayerStatsScraper(BaseScraper):
    """Scrape player-level stats for tournament teams."""

    def scrape_team_players(self, conn, team_id, slug, season):
        """Scrape all player stats for one team in one season."""
        url = f"{SR_SCHOOLS}/{slug}/men/{season}.html"
        soup = self.fetch_and_parse(url)
        if not soup:
            return 0

        soup = self.uncomment_tables(soup)

        # Find the per-game stats table
        table = soup.find("table", id="players_per_game")
        if not table:
            table = soup.find("table", id="per_game")
        if not table:
            # Try roster table
            table = soup.find("table", id="roster")
        if not table:
            return 0

        tbody = table.find("tbody")
        if not tbody:
            return 0

        count = 0
        for row in tbody.find_all("tr"):
            if "thead" in row.get("class", []):
                continue

            name_cell = row.find("td", {"data-stat": "name_display"})
            if not name_cell:
                name_cell = row.find("th", {"data-stat": "player"})
            if not name_cell:
                name_cell = row.find("td", {"data-stat": "player"})
            if not name_cell:
                continue

            player_name = name_cell.get_text(strip=True)
            if not player_name or player_name.lower() in ("team", "opponent", "school"):
                continue

            player_slug = None
            link = name_cell.find("a")
            if link and link.get("href"):
                match = re.search(r"/players/([^.]+)", link["href"])
                if match:
                    player_slug = match.group(1)
                # Also try /cbb/players/ pattern
                if not player_slug:
                    match = re.search(r"/cbb/players/([^/]+)", link["href"])
                    if match:
                        player_slug = match.group(1)

            # Get player metadata
            class_year = None
            class_cell = row.find("td", {"data-stat": "class"})
            if class_cell:
                class_year = class_cell.get_text(strip=True)

            pos = None
            pos_cell = row.find("td", {"data-stat": "pos"})
            if pos_cell:
                pos = pos_cell.get_text(strip=True)

            height = None
            ht_cell = row.find("td", {"data-stat": "height"})
            if ht_cell:
                ht_text = ht_cell.get_text(strip=True)
                match = re.match(r"(\d+)-(\d+)", ht_text)
                if match:
                    height = int(match.group(1)) * 12 + int(match.group(2))

            weight = self.parse_int(row.find("td", {"data-stat": "weight"}))

            # Upsert player
            existing = conn.execute(
                "SELECT player_id FROM players WHERE name = ? AND team_id = ?",
                (player_name, team_id),
            ).fetchone()

            if existing:
                player_id = existing["player_id"]
                if class_year:
                    conn.execute(
                        "UPDATE players SET class_year = ? WHERE player_id = ?",
                        (class_year, player_id),
                    )
            else:
                cur = conn.execute(
                    """INSERT INTO players (name, team_id, sports_ref_slug, position,
                       height_inches, weight, class_year)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (player_name, team_id, player_slug, pos, height, weight, class_year),
                )
                player_id = cur.lastrowid

            # Per-game stats
            stats = {}
            for stat_name, col in [
                ("games", "games"), ("games_started", "games_started"),
                ("mpg", "mp_per_g"), ("ppg", "pts_per_g"),
                ("rpg", "trb_per_g"), ("apg", "ast_per_g"),
                ("spg", "stl_per_g"), ("bpg", "blk_per_g"),
                ("tov", "tov_per_g"),
                ("fg_pct", "fg_pct"), ("fg3_pct", "fg3_pct"), ("ft_pct", "ft_pct"),
                ("efg_pct", "efg_pct"), ("ts_pct", "ts_pct"),
            ]:
                val = self.parse_float(row.find("td", {"data-stat": col}))
                if val is not None:
                    stats[stat_name] = val

            if stats:
                # Upsert player_stats
                existing_stat = conn.execute(
                    "SELECT id FROM player_stats WHERE player_id = ? AND team_id = ? AND season = ?",
                    (player_id, team_id, season),
                ).fetchone()

                cols = list(stats.keys())
                vals = list(stats.values())

                if existing_stat:
                    set_clause = ", ".join(f"{c} = ?" for c in cols)
                    conn.execute(
                        f"UPDATE player_stats SET {set_clause} WHERE id = ?",
                        vals + [existing_stat["id"]],
                    )
                else:
                    cols_str = ", ".join(["player_id", "team_id", "season"] + cols)
                    placeholders = ", ".join(["?"] * (len(cols) + 3))
                    conn.execute(
                        f"INSERT INTO player_stats ({cols_str}) VALUES ({placeholders})",
                        [player_id, team_id, season] + vals,
                    )
                count += 1

        conn.commit()
        return count

    def scrape_season(self, conn, season, tournament_only=True):
        """Scrape player stats for a season.

        For current season, scrape all teams.
        For historical, only scrape tournament teams.
        """
        print(f"\n[Player Stats] Season {season}")
        if tournament_only:
            # Only scrape teams that appear in tournament_games
            teams = conn.execute(
                """SELECT DISTINCT t.team_id, t.school_name, t.sports_ref_slug
                   FROM teams t
                   JOIN tournament_games tg ON (t.team_id = tg.team1_id OR t.team_id = tg.team2_id)
                   WHERE tg.season = ? AND t.sports_ref_slug IS NOT NULL""",
                (season,),
            ).fetchall()
        else:
            teams = conn.execute(
                """SELECT team_id, school_name, sports_ref_slug
                   FROM teams WHERE sports_ref_slug IS NOT NULL"""
            ).fetchall()

        total = 0
        for i, team in enumerate(teams):
            slug = team["sports_ref_slug"]
            print(f"  [{i+1}/{len(teams)}] {team['school_name']}...")
            n = self.scrape_team_players(conn, team["team_id"], slug, season)
            total += n

        print(f"  Loaded stats for {total} players across {len(teams)} teams")
        return total
