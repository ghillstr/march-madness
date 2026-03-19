"""Orchestrator to run all scrapers in the correct order."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db, get_db
from scraping.tournament_scraper import TournamentScraper
from scraping.team_stats_scraper import TeamStatsScraper
from scraping.player_stats_scraper import PlayerStatsScraper
from scraping.odds_scraper import OddsScraper
from scraping.injury_scraper import InjuryScraper
from config import (
    HISTORICAL_START, HISTORICAL_END, CURRENT_SEASON, SKIP_SEASONS
)


def run_all():
    """Run all scrapers in order."""
    print("=" * 60)
    print("NCAA March Madness Data Collection")
    print("=" * 60)

    # Initialize database
    init_db()

    with get_db() as conn:
        # 1. Tournament brackets (historical) - need these first to know which teams to scrape
        print("\n" + "=" * 60)
        print("PHASE 1: Tournament Brackets")
        print("=" * 60)
        tourn_scraper = TournamentScraper()
        tourn_scraper.scrape_all(conn, HISTORICAL_START, HISTORICAL_END, SKIP_SEASONS)

        # 2. Team stats (all seasons including current)
        print("\n" + "=" * 60)
        print("PHASE 2: Team Stats")
        print("=" * 60)
        team_scraper = TeamStatsScraper()
        for season in range(HISTORICAL_START, CURRENT_SEASON + 1):
            if season in SKIP_SEASONS:
                continue
            team_scraper.scrape_season(conn, season)

        # 3. Player stats (tournament teams for history, all for current)
        print("\n" + "=" * 60)
        print("PHASE 3: Player Stats")
        print("=" * 60)
        player_scraper = PlayerStatsScraper()

        # Historical: only tournament teams
        for season in range(HISTORICAL_START, HISTORICAL_END + 1):
            if season in SKIP_SEASONS:
                continue
            player_scraper.scrape_season(conn, season, tournament_only=True)

        # Current season: all D1 teams (or just top teams if too slow)
        player_scraper.scrape_season(conn, CURRENT_SEASON, tournament_only=False)

        # 4. Synthetic spreads
        print("\n" + "=" * 60)
        print("PHASE 4: Point Spreads")
        print("=" * 60)
        odds_scraper = OddsScraper()
        odds_scraper.generate_spreads(conn)

        # 5. Injury reports (current season only — always fresh)
        print("\n" + "=" * 60)
        print("PHASE 5: Injury Reports")
        print("=" * 60)
        injury_scraper = InjuryScraper()
        injury_scraper.scrape_injuries(conn, CURRENT_SEASON)

        # Summary
        print("\n" + "=" * 60)
        print("DATA COLLECTION SUMMARY")
        print("=" * 60)
        for table in ["teams", "team_seasons", "players", "player_stats",
                       "tournament_games", "tournament_results", "point_spreads",
                       "player_injuries"]:
            count = conn.execute(f"SELECT COUNT(*) as n FROM {table}").fetchone()["n"]
            print(f"  {table}: {count} rows")


if __name__ == "__main__":
    run_all()
