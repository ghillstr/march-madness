"""Scraper for historical NCAA tournament bracket results."""

import re
from scraping.base_scraper import BaseScraper
from db.database import get_or_create_team
from config import SR_POSTSEASON


# Map round names to a canonical order
ROUND_ORDER = {
    "First Four": 0, "Play-In": 0,
    "First Round": 1, "Round of 64": 1, "1st Round": 1,
    "Second Round": 2, "Round of 32": 2, "2nd Round": 2,
    "Sweet 16": 3, "Sweet Sixteen": 3, "Regional Semifinal": 3,
    "Elite 8": 4, "Elite Eight": 4, "Regional Final": 4,
    "Final Four": 5, "National Semifinal": 5,
    "Championship": 6, "National Championship": 6, "National Final": 6,
}

ROUND_CANONICAL = {
    0: "First Four", 1: "Round of 64", 2: "Round of 32",
    3: "Sweet 16", 4: "Elite 8", 5: "Final Four", 6: "Championship",
}


class TournamentScraper(BaseScraper):
    """Scrape NCAA tournament bracket results."""

    def scrape_bracket(self, conn, season):
        """Scrape full tournament bracket for a season."""
        url = f"{SR_POSTSEASON}/{season}-ncaa.html"
        print(f"  Scraping tournament bracket for {season}...")
        soup = self.fetch_and_parse(url)
        if not soup:
            return 0

        soup = self.uncomment_tables(soup)
        games = []

        # Strategy: parse the bracket div structure
        bracket = soup.find("div", id="brackets")
        if not bracket:
            bracket = soup  # Fallback to whole page

        # Find all game entries - Sports Reference uses a specific structure
        # Each round/region section has game matchups
        # We'll parse from the tables that contain seed/team/score info

        # Approach: find all links to team pages and their contexts
        # The bracket page typically has rounds as sections
        current_region = None
        current_round = None

        # Parse region headers and game rows
        # SR bracket pages use <div id="bracket"> with nested divs
        # Each round is a div, each game has two team rows

        # Alternative: look for the games table
        games_table = soup.find("table", id="games")
        if games_table:
            return self._parse_games_table(conn, games_table, season)

        # Prefer the per-region div format (e.g. 2026+)
        region_divs = {
            r: soup.find("div", id=r.lower())
            for r in ["East", "West", "South", "Midwest"]
        }
        if any(v for v in region_divs.values()):
            return self._parse_region_divs(conn, region_divs, season)

        # Parse bracket structure
        return self._parse_bracket_divs(conn, bracket, season)

    def _parse_games_table(self, conn, table, season):
        """Parse a structured games table."""
        tbody = table.find("tbody")
        if not tbody:
            return 0

        count = 0
        for row in tbody.find_all("tr"):
            if "thead" in row.get("class", []):
                continue

            round_cell = row.find("td", {"data-stat": "round"})
            round_name = round_cell.get_text(strip=True) if round_cell else None

            region_cell = row.find("td", {"data-stat": "region"})
            region = region_cell.get_text(strip=True) if region_cell else None

            # Team 1
            t1_cell = row.find("td", {"data-stat": "school"})
            t1_seed_cell = row.find("td", {"data-stat": "seed"})
            t1_score_cell = row.find("td", {"data-stat": "pts"})

            # Team 2
            t2_cell = row.find("td", {"data-stat": "opp_school"})
            t2_seed_cell = row.find("td", {"data-stat": "opp_seed"})
            t2_score_cell = row.find("td", {"data-stat": "opp_pts"})

            if not t1_cell or not t2_cell:
                continue

            t1_name = self.clean_school_name(t1_cell.get_text(strip=True))
            t2_name = self.clean_school_name(t2_cell.get_text(strip=True))
            if not t1_name or not t2_name:
                continue

            t1_id = get_or_create_team(conn, t1_name)
            t2_id = get_or_create_team(conn, t2_name)
            seed1 = self.parse_int(t1_seed_cell)
            seed2 = self.parse_int(t2_seed_cell)
            score1 = self.parse_int(t1_score_cell)
            score2 = self.parse_int(t2_score_cell)

            winner_id = None
            margin = None
            if score1 is not None and score2 is not None:
                winner_id = t1_id if score1 > score2 else t2_id
                margin = abs(score1 - score2)

            self._insert_game(
                conn, season, round_name, region,
                t1_id, t2_id, seed1, seed2, score1, score2,
                winner_id, margin
            )
            count += 1

        conn.commit()
        return count

    def _parse_region_divs(self, conn, region_divs, season):
        """Parse the per-region div layout used by Sports Reference (2026+).

        Structure:
          <div id="east">
            <div id="bracket" class="team16">
              <div class="round">           <!-- one per round: R64, R32, S16, E8, FF -->
                <div>                        <!-- one per game -->
                  <div>                      <!-- team 1 -->
                    <span>seed</span>
                    <a href="...">Name</a>
                    [<span class="score">pts</span>]
                  </div>
                  <div>                      <!-- team 2 -->
                    ...
                  </div>
                </div>
                ...
              </div>
            </div>
          </div>
        """
        ROUND_BY_INDEX = {
            0: "Round of 64", 1: "Round of 32", 2: "Sweet 16",
            3: "Elite 8", 4: "Final Four",
        }
        count = 0
        for region_name, region_div in region_divs.items():
            if not region_div:
                continue
            bracket_div = region_div.find("div", id="bracket")
            if not bracket_div:
                continue
            rounds = bracket_div.find_all("div", class_="round", recursive=False)
            for round_idx, rnd_div in enumerate(rounds):
                round_name = ROUND_BY_INDEX.get(round_idx, "Unknown")
                # Each direct child div that contains team sub-divs is a game
                game_divs = [
                    d for d in rnd_div.find_all("div", recursive=False)
                    if d.find("span")
                ]
                for game_div in game_divs:
                    team_divs = [
                        d for d in game_div.find_all("div", recursive=False)
                        if d.find("span") or d.find("a")
                    ]
                    if len(team_divs) < 2:
                        continue

                    def extract_team(td):
                        """Return (name, seed, score, is_winner)."""
                        spans = td.find_all("span")
                        links = td.find_all("a")
                        seed = self.parse_int(spans[0]) if spans else None
                        # TBD placeholder (First Four winner not yet determined)
                        if not links:
                            tbd = td.find("span", class_="note")
                            if tbd or not td.get_text(strip=True):
                                return "TBD", seed, None, False
                            return None, None, None, False
                        # First link = team page, second link = boxscore with score
                        name = self.clean_school_name(links[0].get_text(strip=True))
                        if not name:
                            return None, None, None, False
                        score = self.parse_int(links[1]) if len(links) > 1 else None
                        is_winner = "winner" in td.get("class", [])
                        return name, seed, score, is_winner

                    t1, s1, sc1, w1 = extract_team(team_divs[0])
                    t2, s2, sc2, w2 = extract_team(team_divs[1])
                    if not t1:
                        continue

                    t1_id = get_or_create_team(conn, t1)
                    t2_id = get_or_create_team(conn, t2)
                    winner_id = None
                    margin = None
                    if w1:
                        winner_id = t1_id
                    elif w2:
                        winner_id = t2_id
                    if sc1 is not None and sc2 is not None:
                        margin = abs(sc1 - sc2)
                        if winner_id is None:
                            winner_id = t1_id if sc1 > sc2 else t2_id

                    self._insert_game(
                        conn, season, round_name, region_name,
                        t1_id, t2_id, s1, s2, sc1, sc2, winner_id, margin,
                    )
                    count += 1

        conn.commit()
        return count

    def _parse_bracket_divs(self, conn, bracket, season):
        """Parse bracket from div-based layout."""
        count = 0
        # Look for all game-like structures
        # Each game typically has two team entries with seeds and scores

        # Find all <p> or <span> elements with seed-team-score patterns
        # Pattern in SR bracket pages: seed, team link, score
        all_rounds = bracket.find_all(["div", "section"])

        # Try to find round/region headings
        region = None
        round_name = None

        # Simpler approach: find all anchor tags linking to team pages
        # and their surrounding context for seeds/scores
        team_entries = []
        for link in bracket.find_all("a"):
            href = link.get("href", "")
            if "/schools/" not in href:
                continue

            team_name = link.get_text(strip=True)
            if not team_name:
                continue

            # Look for seed number near the link
            parent = link.parent
            text = parent.get_text() if parent else ""

            # Try to find seed (number before team name)
            seed_match = re.search(r"(\d{1,2})\s+" + re.escape(team_name[:10]), text)
            seed = int(seed_match.group(1)) if seed_match else None

            # Try to find score (number after team name)
            score = None
            next_sib = link.next_sibling
            if next_sib:
                score_match = re.search(r"(\d{2,3})", str(next_sib))
                if score_match:
                    score = int(score_match.group(1))

            team_entries.append({
                "name": team_name, "seed": seed, "score": score,
                "href": href
            })

        # Pair consecutive entries as matchups
        i = 0
        while i < len(team_entries) - 1:
            t1 = team_entries[i]
            t2 = team_entries[i + 1]

            t1_id = get_or_create_team(conn, t1["name"])
            t2_id = get_or_create_team(conn, t2["name"])

            winner_id = None
            margin = None
            if t1["score"] and t2["score"]:
                winner_id = t1_id if t1["score"] > t2["score"] else t2_id
                margin = abs(t1["score"] - t2["score"])

            # Determine round from seed matchup pattern
            round_name = self._guess_round(t1["seed"], t2["seed"], count)

            self._insert_game(
                conn, season, round_name, region,
                t1_id, t2_id, t1["seed"], t2["seed"],
                t1["score"], t2["score"], winner_id, margin
            )
            count += 1
            i += 2

        conn.commit()
        return count

    def _insert_game(self, conn, season, round_name, region,
                     t1_id, t2_id, seed1, seed2, score1, score2,
                     winner_id, margin):
        """Insert a tournament game if it doesn't exist."""
        existing = conn.execute(
            """SELECT game_id FROM tournament_games
               WHERE season = ? AND team1_id = ? AND team2_id = ? AND round = ?""",
            (season, t1_id, t2_id, round_name or "Unknown"),
        ).fetchone()
        if existing:
            return

        conn.execute(
            """INSERT INTO tournament_games
               (season, round, region, team1_id, team2_id, seed1, seed2,
                score1, score2, winner_id, margin)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (season, round_name or "Unknown", region,
             t1_id, t2_id, seed1, seed2, score1, score2, winner_id, margin),
        )

        # Also insert tournament_results for both teams (skip TBD placeholder)
        tbd_row = conn.execute("SELECT team_id FROM teams WHERE school_name='TBD'").fetchone()
        tbd_id  = tbd_row["team_id"] if tbd_row else None
        for tid, seed in [(t1_id, seed1), (t2_id, seed2)]:
            if tbd_id and tid == tbd_id:
                continue  # Don't add TBD to tournament participants
            existing = conn.execute(
                "SELECT id FROM tournament_results WHERE team_id = ? AND season = ?",
                (tid, season),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO tournament_results (team_id, season, seed, region)
                       VALUES (?, ?, ?, ?)""",
                    (tid, season, seed, region),
                )

    def _guess_round(self, seed1, seed2, game_count):
        """Rough guess at round based on seeds and game position."""
        if seed1 and seed2:
            seed_sum = seed1 + seed2
            if seed_sum == 17:  # 1v16, 2v15, etc.
                return "Round of 64"
            elif seed_sum <= 20:
                return "Round of 32"
        return "Unknown"

    def scrape_all(self, conn, start_year, end_year, skip_years=None):
        """Scrape tournament brackets for a range of years."""
        skip = skip_years or set()
        total = 0
        for year in range(start_year, end_year + 1):
            if year in skip:
                print(f"  Skipping {year} (COVID)")
                continue
            n = self.scrape_bracket(conn, year)
            total += n
            print(f"    Found {n} games for {year}")
        print(f"\n  Total tournament games loaded: {total}")
        return total
