"""Live 2026 NCAA Tournament Bracket — visual bracket with connecting lines."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import streamlit.components.v1 as components

from db.database import get_db
from config import CURRENT_SEASON, MODEL_DIR

st.set_page_config(page_title="Live Bracket 2026", page_icon="🏀", layout="wide")
st.title("🏀 2026 NCAA Tournament — Live Bracket")

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
SLOT_H   = 56    # px per bracket slot (game card + gap)
GAME_H   = 48    # px game card height
GAME_W   = 150   # px game card width
ROUND_W  = 190   # px per round column  (gap = ROUND_W - GAME_W = 40px per side)
REG_H    = 8 * SLOT_H    # 448 px — one region (8 first-round games)
HALF_H   = 2 * REG_H     # 896 px — two stacked regions

# Center section: [pad][Left FF][gap][Champ][gap][Right FF][pad]
_PAD     = 30
_GAP     = 40
CENTER_W = _PAD + GAME_W + _GAP + GAME_W + _GAP + GAME_W + _PAD  # = 560

CENTER_X  = 4 * ROUND_W  # x where center section starts = 760
LEFT_FF_X  = CENTER_X + _PAD                              # 790
CHAMP_X    = CENTER_X + _PAD + GAME_W + _GAP              # 1020
RIGHT_FF_X = CENTER_X + _PAD + GAME_W + _GAP + GAME_W + _GAP  # 1250

TOTAL_W  = CENTER_X * 2 + CENTER_W   # 760*2 + 560 = 2080
LABEL_H  = 22   # height reserved at top for round labels

SEED_PAIRS = [(1,16),(8,9),(5,12),(4,13),(6,11),(3,14),(7,10),(2,15)]
REGIONS    = ["East","West","South","Midwest"]
LEFT_REG   = ["East","South"]
RIGHT_REG  = ["West","Midwest"]

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.header("Controls")
if st.sidebar.button("🔄 Refresh from Sports Reference", type="primary"):
    with st.spinner("Scraping 2026 bracket..."):
        try:
            from scraping.tournament_scraper import TournamentScraper
            scraper = TournamentScraper()
            with get_db() as conn:
                conn.execute("DELETE FROM point_spreads     WHERE season=?", (CURRENT_SEASON,))
                conn.execute("DELETE FROM tournament_games   WHERE season=?", (CURRENT_SEASON,))
                conn.execute("DELETE FROM tournament_results WHERE season=?", (CURRENT_SEASON,))
            with get_db() as conn:
                n = scraper.scrape_bracket(conn, CURRENT_SEASON)
            st.sidebar.success(f"Loaded {n} games")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Scrape failed: {e}")

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_games():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT tg.round, tg.region,
                      t1.school_name AS team1, tg.seed1,
                      t2.school_name AS team2, tg.seed2,
                      tg.score1, tg.score2,
                      tw.school_name AS winner
               FROM tournament_games tg
               JOIN teams t1 ON tg.team1_id = t1.team_id
               JOIN teams t2 ON tg.team2_id = t2.team_id
               LEFT JOIN teams tw ON tg.winner_id = tw.team_id
               WHERE tg.season = ?
               ORDER BY tg.game_id""",
            (CURRENT_SEASON,),
        ).fetchall()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# Bracket slot tree
# ---------------------------------------------------------------------------
class Slot:
    def __init__(self):
        self.team1 = self.team2 = None
        self.seed1 = self.seed2 = None
        self.score1 = self.score2 = None
        self.winner = None
        self.played = False

    def fill(self, t1, s1, sc1, t2, s2, sc2, w):
        self.team1=t1; self.seed1=s1; self.score1=sc1
        self.team2=t2; self.seed2=s2; self.score2=sc2
        self.winner=w; self.played=(sc1 is not None)


def build_region_slots(games, region):
    """Return (r64[8], r32[4], s16[2], e8[1]) Slot lists for a region."""
    by_round = {"Round of 64":[],"Round of 32":[],"Sweet 16":[],"Elite 8":[]}
    for g in games:
        if g["region"] and g["region"].strip().lower() == region.lower():
            r = g["round"] or ""
            if r in by_round:
                by_round[r].append(g)

    # R64 — order by SEED_PAIRS
    seed_map = {}
    for g in by_round["Round of 64"]:
        key = (min(g["seed1"] or 99, g["seed2"] or 99),
               max(g["seed1"] or 99, g["seed2"] or 99))
        seed_map[key] = g

    # Also index by the known seed for TBD games (seed2=None → 99)
    seed_by_known = {}
    for g in by_round["Round of 64"]:
        if g["seed1"] is not None and g["seed2"] is None:
            seed_by_known[g["seed1"]] = g
        elif g["seed2"] is not None and g["seed1"] is None:
            seed_by_known[g["seed2"]] = g

    r64 = []
    for s1, s2 in SEED_PAIRS:
        g = seed_map.get((s1, s2)) or seed_by_known.get(s1) or seed_by_known.get(s2)
        sl = Slot()
        if g:
            if (g["seed1"] or 99) <= (g["seed2"] or 99):
                sl.fill(g["team1"],g["seed1"],g["score1"],g["team2"],g["seed2"],g["score2"],g["winner"])
            else:
                sl.fill(g["team2"],g["seed2"],g["score2"],g["team1"],g["seed1"],g["score1"],g["winner"])
        r64.append(sl)

    def find_game(glist, wa, wb):
        for g in glist:
            names = {g["team1"], g["team2"]}
            if (wa and wa in names) or (wb and wb in names):
                return g
        return None

    def later_slot(glist, wa, wb):
        sl = Slot()
        g = find_game(glist, wa, wb)
        if g:
            if (g["seed1"] or 99) <= (g["seed2"] or 99):
                sl.fill(g["team1"],g["seed1"],g["score1"],g["team2"],g["seed2"],g["score2"],g["winner"])
            else:
                sl.fill(g["team2"],g["seed2"],g["score2"],g["team1"],g["seed1"],g["score1"],g["winner"])
        else:
            sl.team1 = wa; sl.team2 = wb
        return sl

    r32 = [later_slot(by_round["Round of 32"],
                       r64[i].winner, r64[i+1].winner) for i in range(0,8,2)]
    s16 = [later_slot(by_round["Sweet 16"],
                       r32[i].winner, r32[i+1].winner) for i in range(0,4,2)]
    e8  = [later_slot(by_round["Elite 8"],
                       s16[0].winner, s16[1].winner)]
    return r64, r32, s16, e8


def build_center_slots(games):
    """Return (ff_left, ff_right, champ) Slots."""
    e8w = {}
    for r in REGIONS:
        _, _, _, e8 = build_region_slots(games, r)
        e8w[r] = e8[0].winner if e8 else None

    ff_games = [g for g in games if g["round"] == "Final Four"]
    ch_games = [g for g in games if g["round"] == "Championship"]

    def ff_slot(wa, wb):
        sl = Slot()
        g = next((g for g in ff_games
                  if g["team1"] in (wa, wb, None) or g["team2"] in (wa, wb, None)), None)
        if g:
            sl.fill(g["team1"],g["seed1"],g["score1"],g["team2"],g["seed2"],g["score2"],g["winner"])
        else:
            sl.team1 = wa; sl.team2 = wb
        return sl

    ff_left  = ff_slot(e8w.get("East"),  e8w.get("South"))
    ff_right = ff_slot(e8w.get("West"),  e8w.get("Midwest"))

    champ = Slot()
    if ch_games:
        g = ch_games[0]
        champ.fill(g["team1"],g["seed1"],g["score1"],g["team2"],g["seed2"],g["score2"],g["winner"])
    else:
        champ.team1 = ff_left.winner
        champ.team2 = ff_right.winner
    return ff_left, ff_right, champ

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def esc(v):
    if v is None: return ""
    return str(v).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def clip(name, n=17):
    if not name: return "TBD"
    return esc(name[:n] + ("." if len(name) > n else ""))

def game_card(slot):
    t1 = clip(slot.team1); s1 = esc(slot.seed1 or "")
    t2 = clip(slot.team2); s2 = esc(slot.seed2 or "")
    sc1 = esc(slot.score1 if slot.score1 is not None else "")
    sc2 = esc(slot.score2 if slot.score2 is not None else "")

    if slot.played:
        c1  = "#2ecc71" if slot.winner == slot.team1 else "#666"
        c2  = "#2ecc71" if slot.winner == slot.team2 else "#666"
        fw1 = "600"     if slot.winner == slot.team1 else "400"
        fw2 = "600"     if slot.winner == slot.team2 else "400"
        bdr = "#2ecc71"
    else:
        c1 = c2 = "#ccc"; fw1 = fw2 = "400"; bdr = "#2d4a6e"

    row = (
        '<div style="display:flex;justify-content:space-between;align-items:center;'
        'padding:0 5px;height:50%;color:{c};font-weight:{fw};">'
        '<span style="min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'
        '<span style="color:#6a8aaa;font-size:9px;margin-right:3px;">{s}</span>{t}</span>'
        '<span style="font-size:10px;margin-left:4px;flex-shrink:0;">{sc}</span></div>'
    )
    r1 = row.format(c=c1, fw=fw1, s=s1, t=t1, sc=sc1)
    r2 = row.format(c=c2, fw=fw2, s=s2, t=t2, sc=sc2)
    divider = '<hr style="margin:0;border:none;border-top:1px solid #1e3350;">'

    return (
        f'<div style="background:#162032;border:1px solid {bdr};border-radius:4px;'
        f'width:{GAME_W}px;height:{GAME_H}px;font-size:10.5px;overflow:hidden;'
        f'box-sizing:border-box;">'
        f'{r1}{divider}{r2}</div>'
    )

def slot_cy(si, n, y_off=0):
    """Center-y of slot si in a round with n slots, within region at y_off."""
    step = REG_H / n
    return y_off + step * (si + 0.5)

def elbow(x1, y1, x2, y2, color):
    """SVG L-shaped elbow: horizontal from (x1,y1) to mid, vertical to mid, horizontal to (x2,y2)."""
    mx = (x1 + x2) / 2
    return (
        f'<polyline points="{x1},{y1} {mx},{y1} {mx},{y2} {x2},{y2}" '
        f'fill="none" stroke="{color}" stroke-width="1.5"/>'
    )

# ---------------------------------------------------------------------------
# Bracket builder
# ---------------------------------------------------------------------------
def build_bracket_html(games):
    region_rounds = {r: build_region_slots(games, r) for r in REGIONS}
    ff_left, ff_right, champ = build_center_slots(games)

    cards = []   # (abs_x, abs_y_in_bracket_coords, html)
    lines = []   # SVG line/polyline strings

    # ------------------------------------------------------------------
    # Left side: East (y_off=0) and West (y_off=REG_H)
    # Columns: R64=0, R32=1, S16=2, E8=3  (x = col * ROUND_W)
    # ------------------------------------------------------------------
    def place_left(y_off, rounds):
        r64, r32, s16, e8 = rounds
        all_rounds = [(r64,8),(r32,4),(s16,2),(e8,1)]
        for ri, (slots, n) in enumerate(all_rounds):
            cx = ri * ROUND_W
            for si, sl in enumerate(slots):
                cy = slot_cy(si, n, y_off)
                cards.append((cx, cy - GAME_H/2, game_card(sl)))

                if ri < 3:
                    x1    = cx + GAME_W          # right edge of this card
                    next_n = all_rounds[ri+1][1]
                    next_si= si // 2
                    x2    = (ri+1) * ROUND_W      # left edge of next-round card
                    y2    = slot_cy(next_si, next_n, y_off)
                    color = "#2ecc71" if sl.played else "#2d4a6e"
                    lines.append(elbow(x1, cy, x2, y2, color))

        # E8 → Left FF connector
        if e8:
            e8_cy = slot_cy(0, 1, y_off)
            x1    = 3 * ROUND_W + GAME_W          # right edge of E8 card
            x2    = LEFT_FF_X                      # left edge of Left FF card
            ff_cy = slot_cy(0, 1, y_off=HALF_H/2 - REG_H/2)  # center of the pair
            # Both East E8 and West E8 connect at Left FF y-center = HALF_H/2
            color = "#2ecc71" if e8[0].winner else "#2d4a6e"
            lines.append(elbow(x1, e8_cy, x2, HALF_H/2, color))

    place_left(0,      region_rounds["East"])
    place_left(REG_H,  region_rounds["South"])

    # ------------------------------------------------------------------
    # Right side: West (y_off=0) and Midwest (y_off=REG_H)
    # Columns: R64=7, R32=6, S16=5, E8=4  (x = col*ROUND_W + CENTER_W + CENTER_X*? )
    # x of col c on right = (7-ri)*ROUND_W + CENTER_X + CENTER_W - 7*ROUND_W + CENTER_X
    # Simpler: right_x(ri) = TOTAL_W - (ri+1)*ROUND_W
    # ------------------------------------------------------------------
    def right_card_x(ri):
        # ri=0 → R64 outermost right, ri=3 → E8 closest to center
        return TOTAL_W - (ri + 1) * ROUND_W

    def place_right(y_off, rounds):
        r64, r32, s16, e8 = rounds
        all_rounds = [(r64,8),(r32,4),(s16,2),(e8,1)]
        for ri, (slots, n) in enumerate(all_rounds):
            cx = right_card_x(ri)
            for si, sl in enumerate(slots):
                cy = slot_cy(si, n, y_off)
                cards.append((cx, cy - GAME_H/2, game_card(sl)))

                if ri < 3:
                    x1 = cx                        # left edge of this card (goes inward)
                    next_n  = all_rounds[ri+1][1]
                    next_si = si // 2
                    x2 = right_card_x(ri+1) + GAME_W  # right edge of next-round card
                    y2 = slot_cy(next_si, next_n, y_off)
                    color = "#2ecc71" if sl.played else "#2d4a6e"
                    lines.append(elbow(x1, cy, x2, y2, color))

        # E8 → Right FF connector
        if e8:
            e8_cy = slot_cy(0, 1, y_off)
            x1    = right_card_x(3)               # left edge of E8 card
            x2    = RIGHT_FF_X + GAME_W            # right edge of Right FF card
            color = "#2ecc71" if e8[0].winner else "#2d4a6e"
            lines.append(elbow(x1, e8_cy, x2, HALF_H/2, color))

    place_right(0,      region_rounds["West"])
    place_right(REG_H,  region_rounds["Midwest"])

    # ------------------------------------------------------------------
    # Center: Left FF, Champ, Right FF  — all at y = HALF_H/2
    # ------------------------------------------------------------------
    ff_y   = HALF_H/2 - GAME_H/2
    ch_y   = HALF_H/2 - GAME_H/2
    ff_cy  = HALF_H/2

    cards.append((LEFT_FF_X,  ff_y, game_card(ff_left)))
    cards.append((RIGHT_FF_X, ff_y, game_card(ff_right)))
    cards.append((CHAMP_X,    ch_y, game_card(champ)))

    # Left FF → Champ
    x1 = LEFT_FF_X + GAME_W;  x2 = CHAMP_X
    color = "#2ecc71" if ff_left.played else "#2d4a6e"
    lines.append(f'<line x1="{x1}" y1="{ff_cy}" x2="{x2}" y2="{ff_cy}" '
                 f'stroke="{color}" stroke-width="1.5"/>')

    # Right FF → Champ
    x1 = CHAMP_X + GAME_W;  x2 = RIGHT_FF_X
    color = "#2ecc71" if ff_right.played else "#2d4a6e"
    lines.append(f'<line x1="{x1}" y1="{ff_cy}" x2="{x2}" y2="{ff_cy}" '
                 f'stroke="{color}" stroke-width="1.5"/>')

    # ------------------------------------------------------------------
    # Round labels (rendered as divs above the bracket)
    # ------------------------------------------------------------------
    lbl_css = "position:absolute;font-size:9px;color:#4a7aaa;font-weight:700;" \
              "letter-spacing:.8px;text-align:center;white-space:nowrap;"

    label_html = ""
    left_labels  = ["R64","R32","S16","E8"]
    right_labels = ["E8","S16","R32","R64"]

    for ri, txt in enumerate(left_labels):
        lx = ri * ROUND_W + GAME_W/2 - 20
        label_html += f'<div style="{lbl_css}left:{lx}px;top:4px;width:40px;">{txt}</div>'
    for ri, txt in enumerate(right_labels):
        lx = right_card_x(3-ri) + GAME_W/2 - 20
        label_html += f'<div style="{lbl_css}left:{lx}px;top:4px;width:40px;">{txt}</div>'

    center_cx = CHAMP_X + GAME_W/2
    label_html += f'<div style="{lbl_css}left:{center_cx-30}px;top:4px;width:60px;color:#e8c84a;">CHAMP</div>'

    # Region labels — horizontal banners at the top of each region's area
    reg_css = ("position:absolute;font-size:11px;color:#4a8aff;font-weight:700;"
               "letter-spacing:1px;text-align:center;z-index:20;"
               "background:rgba(13,17,23,0.85);padding:1px 6px;border-radius:3px;")
    left_cx  = (4 * ROUND_W) / 2 - 25          # center of left half
    right_cx = TOTAL_W - (4 * ROUND_W) / 2 - 25  # center of right half
    label_html += f'<div style="{reg_css}left:{left_cx}px;top:{LABEL_H+6}px;">EAST</div>'
    label_html += f'<div style="{reg_css}left:{left_cx}px;top:{LABEL_H+REG_H+6}px;">SOUTH</div>'
    label_html += f'<div style="{reg_css}left:{right_cx}px;top:{LABEL_H+6}px;">WEST</div>'
    label_html += f'<div style="{reg_css}left:{right_cx}px;top:{LABEL_H+REG_H+6}px;">MIDWEST</div>'

    # ------------------------------------------------------------------
    # Assemble SVG + cards into one container
    # SVG coordinate origin = top-left of the bracket (below labels)
    # Game cards: left=x, top=LABEL_H + y
    # SVG: translate(0, LABEL_H)
    # ------------------------------------------------------------------
    CONTAINER_H = HALF_H + LABEL_H + 4
    CONTAINER_W = TOTAL_W + 20

    svg = (
        f'<svg style="position:absolute;top:0;left:0;pointer-events:none;overflow:visible;" '
        f'width="{CONTAINER_W}" height="{CONTAINER_H}">'
        f'<g transform="translate(0,{LABEL_H})">'
        + "".join(lines)
        + "</g></svg>"
    )

    card_html = ""
    for (cx, cy, html) in cards:
        card_html += f'<div style="position:absolute;left:{cx}px;top:{LABEL_H+cy}px;">{html}</div>'

    return (
        f'<div style="position:relative;width:{CONTAINER_W}px;height:{CONTAINER_H}px;'
        f'background:#0d1117;font-family:\'Segoe UI\',system-ui,sans-serif;">'
        f'{svg}{card_html}{label_html}</div>'
    )

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_bracket, tab_schedule = st.tabs(["🏆 Bracket", "📅 Schedule & TV"])

with tab_bracket:
    games = load_games()
    if not games:
        st.info(
            "No 2026 bracket data found. Click **Refresh from Sports Reference** "
            "in the sidebar to load the bracket."
        )
    else:
        completed = sum(1 for g in games if g["score1"] is not None)
        st.caption(f"{completed}/{len(games)} games completed · {CURRENT_SEASON} NCAA Tournament")

        html = build_bracket_html(games)
        components.html(
            f'<html><body style="margin:0;padding:8px;background:#0d1117;'
            f'overflow-x:auto;overflow-y:hidden;">'
            f'{html}</body></html>',
            height=HALF_H + LABEL_H + 40,
            scrolling=True,
        )

with tab_schedule:
    st.subheader("📅 Game Schedule & TV Listings")
    st.caption("Times Eastern · All games on CBS, TruTV, TNT, or TBS · Stream on Paramount+")

    import pandas as pd
    from datetime import datetime, timezone, timedelta

    # ------------------------------------------------------------------
    # Fetch game times from ESPN public API and cache in DB
    # ------------------------------------------------------------------
    @st.cache_data(ttl=300)  # refresh every 5 minutes
    def fetch_espn_times(season):
        """Fetch game times from ESPN scoreboard API for tournament dates.
        Returns dict keyed by frozenset({team1_lower, team2_lower}) -> time string.
        """
        import urllib.request, json
        times = {}
        # NCAA tournament runs ~March 18–April 7 for 2026
        start = datetime(season - 1, 3, 18)  # Mar 18 prior year? No — same year
        start = datetime(season, 3, 18)
        for day_offset in range(22):  # 22 days covers First Four through Championship
            date_str = (start + timedelta(days=day_offset)).strftime("%Y%m%d")
            url = (
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/"
                f"mens-college-basketball/scoreboard?groups=50&dates={date_str}"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                for event in data.get("events", []):
                    # Parse UTC time -> Eastern
                    raw_date = event.get("date", "")
                    try:
                        dt_utc = datetime.strptime(raw_date, "%Y-%m-%dT%H:%MZ")
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        dt_et  = dt_utc.astimezone(timezone(timedelta(hours=-4)))  # EDT
                        time_str = dt_et.strftime("%-m/%-d %-I:%M %p ET")
                    except Exception:
                        time_str = raw_date[:10]

                    # Build lookup key from competitor names
                    comps = event.get("competitions", [{}])[0].get("competitors", [])
                    names = frozenset(
                        c["team"]["displayName"].lower()
                        for c in comps if "team" in c
                    )
                    if names:
                        times[names] = time_str
                    # Also store TV network
                    broadcasts = event.get("competitions", [{}])[0].get("broadcasts", [])
                    tv = ", ".join(
                        b.get("names", [""])[0]
                        for b in broadcasts if b.get("names")
                    ) or "CBS/TruTV/TNT/TBS"
                    times[names + ("_tv",)] = tv  # type: ignore[operator]
            except Exception:
                pass
        return times

    def match_espn_time(espn_times, team1, team2):
        """Look up game time from ESPN dict using fuzzy team name matching."""
        t1l = team1.lower(); t2l = team2.lower()
        key = frozenset([t1l, t2l])
        if key in espn_times:
            return espn_times[key], espn_times.get(key | {"_tv"}, "CBS/TruTV/TNT/TBS")  # type: ignore[operator]
        # Try partial match
        for k, v in espn_times.items():
            if isinstance(k, frozenset) and "_tv" not in k:
                if any(t1l in n or n in t1l for n in k) and \
                   any(t2l in n or n in t2l for n in k):
                    return v, espn_times.get(k | {"_tv"}, "CBS/TruTV/TNT/TBS")  # type: ignore[operator]
        return None, "CBS/TruTV/TNT/TBS"

    with st.spinner("Fetching game times from ESPN..."):
        espn_times = fetch_espn_times(CURRENT_SEASON)

    with get_db() as conn:
        db_games = conn.execute(
            """SELECT tg.game_id, tg.round, tg.region,
                      t1.school_name AS team1, tg.seed1,
                      t2.school_name AS team2, tg.seed2,
                      tg.score1, tg.score2, tg.game_time
               FROM tournament_games tg
               JOIN teams t1 ON tg.team1_id = t1.team_id
               JOIN teams t2 ON tg.team2_id = t2.team_id
               WHERE tg.season = ?
               ORDER BY tg.game_id""",
            (CURRENT_SEASON,),
        ).fetchall()
        db_games = [dict(g) for g in db_games]

        # Back-fill game_time from ESPN into DB where missing
        for g in db_games:
            if not g["game_time"]:
                t, _ = match_espn_time(espn_times, g["team1"], g["team2"])
                if t:
                    conn.execute(
                        "UPDATE tournament_games SET game_time = ? WHERE game_id = ?",
                        (t, g["game_id"]),
                    )
                    g["game_time"] = t

    if not db_games:
        st.info("No game data yet — refresh the bracket first.")
    else:
        round_order = ["First Four","Round of 64","Round of 32",
                       "Sweet 16","Elite 8","Final Four","Championship"]
        rows = []
        for g in db_games:
            status = "✅ Final" if g["score1"] is not None else "🕐 Upcoming"
            score  = f"{g['score1']}–{g['score2']}" if g["score1"] is not None else "–"
            _, tv  = match_espn_time(espn_times, g["team1"], g["team2"])
            rows.append({
                "Round":    g["round"],
                "Region":   g["region"] or "–",
                "Matchup":  f"({g['seed1']}) {g['team1']}  vs  ({g['seed2']}) {g['team2']}",
                "Time (ET)": g["game_time"] or "TBD",
                "Score":    score,
                "Status":   status,
                "TV":       tv,
            })

        df = pd.DataFrame(rows)
        df["_ord"] = df["Round"].map({r:i for i,r in enumerate(round_order)}).fillna(99)
        df = df.sort_values(["_ord","Region"]).drop(columns="_ord").reset_index(drop=True)

        for rnd in round_order:
            sub = df[df["Round"] == rnd].drop(columns="Round").reset_index(drop=True)
            if sub.empty:
                continue
            st.markdown(f"**{rnd}**")
            st.dataframe(sub, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.info("📺 Stream every game free on **NCAA March Madness Live** or **Paramount+**.")
