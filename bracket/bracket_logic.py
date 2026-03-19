"""68-team NCAA tournament bracket structure and seeding."""

# Standard 64-team bracket matchups (by seed) for each region
# First round: 1v16, 8v9, 5v12, 4v13, 6v11, 3v14, 7v10, 2v15
FIRST_ROUND_MATCHUPS = [
    (1, 16), (8, 9), (5, 12), (4, 13),
    (6, 11), (3, 14), (7, 10), (2, 15),
]

REGIONS = ["East", "West", "South", "Midwest"]

ROUND_NAMES = [
    "Round of 64", "Round of 32", "Sweet 16",
    "Elite 8", "Final Four", "Championship",
]


class BracketTeam:
    """A team in the bracket."""

    def __init__(self, team_id, name, seed, region):
        self.team_id = team_id
        self.name = name
        self.seed = seed
        self.region = region

    def __repr__(self):
        return f"({self.seed}) {self.name}"


class Bracket:
    """Full 68-team tournament bracket."""

    def __init__(self):
        self.regions = {r: [] for r in REGIONS}
        self.games = []  # List of (round, team1, team2, winner, win_prob, margin)
        self.results = {}  # round_name -> list of winners

    def load_from_db(self, conn, season):
        """Load tournament field from database."""
        teams = conn.execute(
            """SELECT tr.team_id, t.school_name, tr.seed, tr.region
               FROM tournament_results tr
               JOIN teams t ON tr.team_id = t.team_id
               WHERE tr.season = ?
               ORDER BY tr.region, tr.seed""",
            (season,),
        ).fetchall()

        for row in teams:
            bt = BracketTeam(
                row["team_id"], row["school_name"],
                row["seed"], row["region"]
            )
            region = row["region"]
            if region in self.regions:
                self.regions[region].append(bt)
            elif len(self.regions) > 0:
                # Put in first region with space
                for r in REGIONS:
                    if len(self.regions[r]) < 16:
                        self.regions[r].append(bt)
                        bt.region = r
                        break

        return len(teams)

    def load_field_manual(self, teams_data):
        """Load bracket from a list of dicts with team_id, name, seed, region."""
        for td in teams_data:
            bt = BracketTeam(td["team_id"], td["name"], td["seed"], td["region"])
            if td["region"] in self.regions:
                self.regions[td["region"]].append(bt)

    def get_first_round_matchups(self, region):
        """Get first round matchups for a region based on seed pairing."""
        teams = {t.seed: t for t in self.regions.get(region, [])}
        matchups = []
        for s1, s2 in FIRST_ROUND_MATCHUPS:
            t1 = teams.get(s1)
            t2 = teams.get(s2)
            # First Four TBD: one seed not yet determined — use placeholder
            if t1 and not t2:
                t2 = BracketTeam(-1, "TBD", s2, region)
            elif t2 and not t1:
                t1 = BracketTeam(-1, "TBD", s1, region)
            if t1 and t2:
                matchups.append((t1, t2))
        return matchups

    def get_all_teams(self):
        """Get flat list of all teams in the bracket."""
        all_teams = []
        for region in REGIONS:
            all_teams.extend(self.regions[region])
        return all_teams

    def get_team_by_id(self, team_id):
        """Find a team in the bracket by team_id."""
        for region in REGIONS:
            for team in self.regions[region]:
                if team.team_id == team_id:
                    return team
        return None
