"""Scraper for team basic stats, advanced stats, and ratings from Sports Reference."""

import re
from scraping.base_scraper import BaseScraper
from db.database import get_or_create_team, upsert_team_season
from config import SR_SEASONS


class TeamStatsScraper(BaseScraper):
    """Scrape team-level stats for all D1 teams."""

    def scrape_basic_stats(self, conn, season):
        """Scrape basic school stats for a season."""
        url = f"{SR_SEASONS}/{season}-school-stats.html"
        print(f"  Scraping basic stats for {season}...")
        soup = self.fetch_and_parse(url)
        if not soup:
            return 0

        soup = self.uncomment_tables(soup)
        table = soup.find("table", id="basic_school_stats")
        if not table:
            # Try finding any table with school stats
            table = soup.find("table")
        if not table:
            print(f"    No basic stats table found for {season}")
            return 0

        tbody = table.find("tbody")
        if not tbody:
            return 0

        count = 0
        for row in tbody.find_all("tr"):
            if row.find("th", {"scope": "row"}) is None:
                continue
            if "thead" in row.get("class", []):
                continue

            school_cell = row.find("td", {"data-stat": "school_name"})
            if not school_cell:
                continue
            link = school_cell.find("a")
            school_name = self.clean_school_name(school_cell.get_text(strip=True))
            slug = None
            if link and link.get("href"):
                # Extract slug from /schools/slug/men/2026.html
                match = re.search(r"/schools/([^/]+)/", link["href"])
                if match:
                    slug = match.group(1)

            team_id = get_or_create_team(conn, school_name, slug)

            stats = {}
            # Win-loss
            wins = self.parse_int(row.find("td", {"data-stat": "wins"}))
            losses = self.parse_int(row.find("td", {"data-stat": "losses"}))
            stats["wins"] = wins
            stats["losses"] = losses
            if wins is not None and losses is not None and (wins + losses) > 0:
                stats["win_pct"] = wins / (wins + losses)

            # Per-game stats
            g = self.parse_int(row.find("td", {"data-stat": "g"}))
            for stat_name, col in [
                ("ppg", "pts_per_g"), ("opp_ppg", "opp_pts_per_g"),
                ("fg_pct", "fg_pct"), ("fg3_pct", "fg3_pct"), ("ft_pct", "ft_pct"),
                ("orb_per_game", "orb_per_g"), ("drb_per_game", "drb_per_g"),
                ("trb_per_game", "trb_per_g"), ("ast_per_game", "ast_per_g"),
                ("stl_per_game", "stl_per_g"), ("blk_per_game", "blk_per_g"),
                ("tov_per_game", "tov_per_g"),
            ]:
                val = self.parse_float(row.find("td", {"data-stat": col}))
                if val is not None:
                    stats[stat_name] = val

            # MOV
            if stats.get("ppg") and stats.get("opp_ppg"):
                stats["mov"] = stats["ppg"] - stats["opp_ppg"]

            upsert_team_season(conn, team_id, season, stats)
            count += 1

        conn.commit()
        print(f"    Loaded basic stats for {count} teams")
        return count

    def scrape_advanced_stats(self, conn, season):
        """Scrape advanced school stats (four factors, etc.)."""
        url = f"{SR_SEASONS}/{season}-advanced-school-stats.html"
        print(f"  Scraping advanced stats for {season}...")
        soup = self.fetch_and_parse(url)
        if not soup:
            return 0

        soup = self.uncomment_tables(soup)
        table = soup.find("table", id="adv_school_stats")
        if not table:
            table = soup.find("table")
        if not table:
            print(f"    No advanced stats table found for {season}")
            return 0

        tbody = table.find("tbody")
        if not tbody:
            return 0

        count = 0
        for row in tbody.find_all("tr"):
            if row.find("th", {"scope": "row"}) is None:
                continue
            if "thead" in row.get("class", []):
                continue

            school_cell = row.find("td", {"data-stat": "school_name"})
            if not school_cell:
                continue
            school_name = self.clean_school_name(school_cell.get_text(strip=True))
            team_id = get_or_create_team(conn, school_name)

            stats = {}
            for stat_name, col in [
                ("pace", "pace"), ("ortg", "off_rtg"), ("drtg", "def_rtg"),
                ("efg_pct", "efg_pct"), ("tov_pct", "tov_pct"),
                ("orb_pct", "orb_pct"), ("ft_rate", "ft_rate"),
                ("opp_efg_pct", "opp_efg_pct"), ("opp_tov_pct", "opp_tov_pct"),
                ("opp_orb_pct", "opp_orb_pct"), ("opp_ft_rate", "opp_ft_rate"),
            ]:
                val = self.parse_float(row.find("td", {"data-stat": col}))
                if val is not None:
                    stats[stat_name] = val

            if stats.get("ortg") and stats.get("drtg"):
                stats["net_rtg"] = stats["ortg"] - stats["drtg"]

            if stats:
                upsert_team_season(conn, team_id, season, stats)
                count += 1

        conn.commit()
        print(f"    Loaded advanced stats for {count} teams")
        return count

    def scrape_ratings(self, conn, season):
        """Scrape team ratings (SRS, SOS, etc.)."""
        url = f"{SR_SEASONS}/{season}-ratings.html"
        print(f"  Scraping ratings for {season}...")
        soup = self.fetch_and_parse(url)
        if not soup:
            return 0

        soup = self.uncomment_tables(soup)
        table = soup.find("table", id="ratings")
        if not table:
            # Try alternate table IDs
            for tid in ["net_ratings", "adv_ratings"]:
                table = soup.find("table", id=tid)
                if table:
                    break
        if not table:
            table = soup.find("table")
        if not table:
            print(f"    No ratings table found for {season}")
            return 0

        tbody = table.find("tbody")
        if not tbody:
            return 0

        count = 0
        for row in tbody.find_all("tr"):
            if row.find("th", {"scope": "row"}) is None:
                continue
            if "thead" in row.get("class", []):
                continue

            school_cell = row.find("td", {"data-stat": "school_name"})
            if not school_cell:
                continue
            school_name = self.clean_school_name(school_cell.get_text(strip=True))
            conf_cell = row.find("td", {"data-stat": "conf_abbr"})
            conf = conf_cell.get_text(strip=True) if conf_cell else None

            team_id = get_or_create_team(conn, school_name, conference=conf)

            stats = {}
            for stat_name, col in [
                ("srs", "srs"), ("sos", "sos"),
                ("osrs", "off_srs"), ("dsrs", "def_srs"),
                ("ppg", "pts_per_g"), ("opp_ppg", "opp_pts_per_g"),
                ("mov", "mov"), ("drtg", "def_rtg"),
            ]:
                val = self.parse_float(row.find("td", {"data-stat": col}))
                if val is not None:
                    stats[stat_name] = val

            # Also grab AP/coaches poll ranking if available
            # Try to get TS% and 3PAr from ratings page
            for stat_name, col in [
                ("ts_pct", "ts_pct"), ("three_par", "fg3a_per_fga_pct"),
            ]:
                val = self.parse_float(row.find("td", {"data-stat": col}))
                if val is not None:
                    stats[stat_name] = val

            if stats:
                upsert_team_season(conn, team_id, season, stats)
                count += 1

        conn.commit()
        print(f"    Loaded ratings for {count} teams")
        return count

    def scrape_season(self, conn, season):
        """Scrape all team stats for a season."""
        print(f"\n[Team Stats] Season {season}")
        self.scrape_basic_stats(conn, season)
        self.scrape_advanced_stats(conn, season)
        self.scrape_ratings(conn, season)
