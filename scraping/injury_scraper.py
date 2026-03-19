"""Scraper for NCAA basketball injury reports from ESPN."""

import re
from difflib import get_close_matches

from scraping.base_scraper import BaseScraper

ESPN_INJURIES_URL = "https://www.espn.com/mens-college-basketball/injuries"

# Fraction of a player's contribution treated as lost per status
STATUS_WEIGHTS = {
    "out": 1.0,
    "doubtful": 0.75,
    "questionable": 0.50,
    "day-to-day": 0.25,
    "probable": 0.10,
}

# Common mascot words to strip when matching team names
_MASCOT_RE = re.compile(
    r"\s+(Blue\s+Devils?|Tar\s+Heels?|Wildcats?|Bulldogs?|Tigers?|Bears?|"
    r"Bruins?|Trojans?|Longhorns?|Volunteers?|Gators?|Razorbacks?|Hokies?|"
    r"Demon\s+Deacons?|Cardinals?|Crimson\s+Tide|Orange|Mountaineers?|"
    r"Cavaliers?|Nittany\s+Lions?|Fighting\s+Irish|Hoosiers?|Fighting\s+Illini|"
    r"Illini|Badgers?|Hawkeyes?|Buckeyes?|Spartans?|Wolverines?|"
    r"Golden\s+Eagles?|Eagles?|Hawks?|Owls?|Ravens?|Panthers?|Saints?|"
    r"Warriors?|Aggies?|Cowboys?|Mustangs?|Horned\s+Frogs?|Mean\s+Green|"
    r"Miners?|Roadrunners?|Lobos?|Aztecs?|Ducks?|Beavers?|Cougars?|"
    r"Utes?|Sun\s+Devils?|Buffaloes?|Rams?|Falcons?|Green\s+Wave|"
    r"Hurricanes?|Seminoles?|Yellow\s+Jackets?|Cornhuskers?|Sooners?|"
    r"Boilermakers?|Golden\s+Gophers?|Hawkeyes?|Terrapins?|"
    r"Retrievers?|Retrievers?|Retrievers?|Penguins?|Flyers?|Pilots?)$",
    re.IGNORECASE,
)


class InjuryScraper(BaseScraper):
    """Scrape player injury reports from ESPN for college basketball."""

    def _normalize_team_name(self, name):
        """Strip school nickname/mascot to get the bare school name."""
        name = _MASCOT_RE.sub("", name).strip()
        # Strip trailing state abbreviations like "(Va.)" or "(N.C.)"
        name = re.sub(r"\s*\([A-Z][a-z.]+\)\s*$", "", name).strip()
        return name

    def _match_team(self, conn, espn_name):
        """Return team_id for an ESPN team name, or None if no match."""
        normalized = self._normalize_team_name(espn_name)

        for candidate in (normalized, espn_name):
            row = conn.execute(
                "SELECT team_id FROM teams WHERE school_name = ?", (candidate,)
            ).fetchone()
            if row:
                return row["team_id"]

            row = conn.execute(
                "SELECT team_id FROM teams WHERE school_name LIKE ?",
                (f"%{candidate}%",),
            ).fetchone()
            if row:
                return row["team_id"]

        # Fuzzy fallback
        all_teams = conn.execute("SELECT team_id, school_name FROM teams").fetchall()
        names = [t["school_name"] for t in all_teams]
        matches = get_close_matches(normalized, names, n=1, cutoff=0.6)
        if matches:
            row = conn.execute(
                "SELECT team_id FROM teams WHERE school_name = ?", (matches[0],)
            ).fetchone()
            if row:
                return row["team_id"]

        return None

    def _parse_status(self, cells):
        """Extract a normalised status string from a row's cells."""
        for cell in cells:
            text = cell.get_text(strip=True).lower()
            for key in STATUS_WEIGHTS:
                if key in text:
                    return key
        return None

    def scrape_injuries(self, conn, season):
        """Fetch ESPN injury page and store results in player_injuries table."""
        print(f"\n[Injury Scraper] Fetching ESPN injury reports for {season}...")

        # Always fetch fresh (no cache) so we have current data
        soup = self.fetch_and_parse(ESPN_INJURIES_URL, use_cache=False)
        if not soup:
            print("  [ERROR] Could not fetch ESPN injury page")
            return 0

        count = 0

        # ESPN renders injuries as multiple <div> sections, each with a
        # .Table__Title header followed by a <table>.
        team_headers = soup.find_all(
            lambda tag: tag.name in ("div", "span", "h2", "h3")
            and "Table__Title" in tag.get("class", [])
        )

        if not team_headers:
            # Fallback: look for any element whose class contains 'Table__Title'
            team_headers = soup.find_all(class_=re.compile(r"Table__Title"))

        if not team_headers:
            print("  [WARN] No injury sections found — ESPN page structure may have changed.")
            return 0

        for header in team_headers:
            team_name = header.get_text(strip=True)
            if not team_name:
                continue

            team_id = self._match_team(conn, team_name)
            if not team_id:
                continue

            table = header.find_next("table")
            if not table:
                continue
            tbody = table.find("tbody")
            if not tbody:
                continue

            for row in tbody.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue

                player_name = cells[0].get_text(strip=True)
                if not player_name:
                    continue

                status = self._parse_status(cells[1:])
                if not status:
                    # If no recognised status keyword, default to questionable
                    status = "questionable"

                injury_type = cells[-1].get_text(strip=True) if len(cells) >= 4 else None

                # Try to link to existing player record
                player_row = conn.execute(
                    "SELECT player_id FROM players WHERE name = ? AND team_id = ?",
                    (player_name, team_id),
                ).fetchone()
                player_id = player_row["player_id"] if player_row else None

                conn.execute(
                    """INSERT INTO player_injuries
                           (player_id, team_id, season, player_name, status, injury_type)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(team_id, season, player_name) DO UPDATE SET
                           status = excluded.status,
                           injury_type = excluded.injury_type,
                           player_id = excluded.player_id,
                           updated_at = CURRENT_TIMESTAMP""",
                    (player_id, team_id, season, player_name, status, injury_type),
                )
                count += 1

        conn.commit()
        print(f"  Stored {count} injury records for {season}")
        return count
