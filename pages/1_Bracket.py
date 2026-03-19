"""Predicted tournament bracket — visual bracket with model predictions."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go

from db.database import get_db
from config import CURRENT_SEASON, MODEL_DIR

st.set_page_config(page_title="Bracket", page_icon="🏀", layout="wide")
st.title("🏀 2026 Tournament Bracket — Model Predictions")

# ---------------------------------------------------------------------------
# Layout constants (same as Live Bracket)
# ---------------------------------------------------------------------------
SLOT_H    = 56
GAME_H    = 48
GAME_W    = 150
ROUND_W   = 190
REG_H     = 8 * SLOT_H    # 448
HALF_H    = 2 * REG_H     # 896
LABEL_H   = 22

_PAD      = 30
_GAP      = 40
CENTER_W  = _PAD + GAME_W + _GAP + GAME_W + _GAP + GAME_W + _PAD  # 560

CENTER_X   = 4 * ROUND_W   # 760
LEFT_FF_X  = CENTER_X + _PAD
CHAMP_X    = CENTER_X + _PAD + GAME_W + _GAP
RIGHT_FF_X = CENTER_X + _PAD + GAME_W + _GAP + GAME_W + _GAP

TOTAL_W   = CENTER_X * 2 + CENTER_W   # 2080

SEED_PAIRS = [(1,16),(8,9),(5,12),(4,13),(6,11),(3,14),(7,10),(2,15)]
REGIONS    = ["East","West","South","Midwest"]
LEFT_REG   = ["East","South"]
RIGHT_REG  = ["West","Midwest"]

# ---------------------------------------------------------------------------
# Check model exists
# ---------------------------------------------------------------------------
model_path = os.path.join(MODEL_DIR, "best_model.pt")
if not os.path.exists(model_path):
    st.warning("No trained model found. Train the model first: `python model/train.py`")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.header("Controls")
n_scenarios = st.sidebar.slider("Random Scenarios", 1, 10, 10)
n_sims      = st.sidebar.slider("Monte Carlo Sims (Odds tab)", 1000, 20000, 5000, step=1000)

st.sidebar.markdown("---")
st.sidebar.subheader("Force Champion")

@st.cache_data(ttl=3600)
def get_team_names():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT DISTINCT t.school_name FROM tournament_results tr
               JOIN teams t ON tr.team_id = t.team_id
               WHERE tr.season = ? ORDER BY t.school_name""",
            (CURRENT_SEASON,),
        ).fetchall()
    return ["(None)"] + [r["school_name"] for r in rows]

team_names     = get_team_names()
forced_champ   = st.sidebar.selectbox("Pick a champion", team_names, index=0)
n_forced       = st.sidebar.slider("Forced scenarios", 1, 5, 2) if forced_champ != "(None)" else 0

# ---------------------------------------------------------------------------
# Run simulation (cached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def run_simulation(n_scenarios, n_sims, forced_champ, n_forced):
    import random
    from bracket.bracket_logic import Bracket
    from bracket.simulator import TournamentSimulator
    from model.predict import Predictor

    predictor = Predictor()
    with get_db() as conn:
        bracket = Bracket()
        loaded = bracket.load_from_db(conn, CURRENT_SEASON)
        if loaded == 0:
            bracket.load_from_db(conn, CURRENT_SEASON - 1)
        sim = TournamentSimulator(predictor, conn)

        det_games = sim.simulate_deterministic(bracket)

        rand_scenarios = []
        for seed in range(n_scenarios):
            random.seed(seed * 42 + 7)
            rand_scenarios.append(sim.simulate_random(bracket))

        forced_scenarios = []
        if forced_champ and forced_champ != "(None)":
            for seed in range(n_forced):
                forced_scenarios.append(
                    sim.simulate_forced_champion(bracket, forced_champ, seed=seed * 13 + 3)
                )

        mc = sim.simulate_monte_carlo(bracket, n_sims)

    return det_games, rand_scenarios, forced_scenarios, mc, bracket

try:
    with st.spinner("Running simulations..."):
        det_games, rand_scenarios, forced_scenarios, mc_results, bracket = run_simulation(
            n_scenarios, n_sims, forced_champ, n_forced
        )
except Exception as e:
    st.error(f"Simulation error: {e}")
    import traceback; st.code(traceback.format_exc())
    st.stop()

if not det_games:
    st.warning("No bracket data. Make sure 2026 tournament teams are scraped.")
    st.stop()

# ---------------------------------------------------------------------------
# Slot class + builders from simulator output
# ---------------------------------------------------------------------------
class Slot:
    def __init__(self):
        self.team1 = self.team2 = None
        self.seed1 = self.seed2 = None
        self.win_prob = 0.5
        self.margin   = 0.0
        self.winner   = None

    @classmethod
    def from_game(cls, g):
        s = cls()
        s.team1    = g["team1"].name;   s.seed1 = g["team1"].seed
        s.team2    = g["team2"].name;   s.seed2 = g["team2"].seed
        s.winner   = g["winner"].name
        s.win_prob = g["win_prob"]
        s.margin   = g["margin"]
        return s


def build_region_slots(games, region):
    """Organize simulator games into (r64[8], r32[4], s16[2], e8[1]) Slot lists."""
    by_round = {"Round of 64":[],"Round of 32":[],"Sweet 16":[],"Elite 8":[]}
    for g in games:
        if g.get("region") == region and g["round"] in by_round:
            by_round[g["round"]].append(g)

    # R64 — order by SEED_PAIRS to match bracket position
    seed_map = {}
    for g in by_round["Round of 64"]:
        key = (min(g["team1"].seed, g["team2"].seed),
               max(g["team1"].seed, g["team2"].seed))
        seed_map[key] = g

    r64 = []
    for s1, s2 in SEED_PAIRS:
        g = seed_map.get((s1, s2))
        r64.append(Slot.from_game(g) if g else Slot())

    # Build R32/S16/E8 ordered by matching winners from previous round
    def ordered_later_slots(glist, prev_winners):
        """Return Slots in bracket order by matching known winners from prev round."""
        used = set()
        slots = []
        for i in range(0, len(prev_winners), 2):
            wa = prev_winners[i]
            wb = prev_winners[i+1] if i+1 < len(prev_winners) else None
            found = None
            for idx, g in enumerate(glist):
                if idx in used:
                    continue
                names = {g["team1"].name, g["team2"].name}
                if (wa and wa in names) or (wb and wb in names):
                    found = g
                    used.add(idx)
                    break
            slots.append(Slot.from_game(found) if found else Slot())
        return slots

    r64_winners = [sl.winner for sl in r64]
    r32 = ordered_later_slots(by_round["Round of 32"], r64_winners)
    r32_winners = [sl.winner for sl in r32]
    s16 = ordered_later_slots(by_round["Sweet 16"], r32_winners)
    s16_winners = [sl.winner for sl in s16]
    e8  = ordered_later_slots(by_round["Elite 8"], s16_winners)
    return r64, r32, s16, e8


def build_center_slots(games):
    ff_games = [g for g in games if g["round"] == "Final Four"]
    ch_games = [g for g in games if g["round"] == "Championship"]

    ff_left  = Slot.from_game(ff_games[0]) if len(ff_games) >= 1 else Slot()
    ff_right = Slot.from_game(ff_games[1]) if len(ff_games) >= 2 else Slot()
    champ    = Slot.from_game(ch_games[0]) if ch_games else Slot()
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

def conf_color(prob):
    """Border/accent color based on win probability confidence."""
    if prob >= 0.75: return "#2ecc71"
    if prob >= 0.60: return "#f1c40f"
    if prob >= 0.50: return "#e67e22"
    return "#e74c3c"

def game_card(slot):
    if slot.winner is None:
        # Empty slot
        t1 = clip(slot.team1); s1 = esc(slot.seed1 or "")
        t2 = clip(slot.team2); s2 = esc(slot.seed2 or "")
        row = ('<div style="display:flex;justify-content:space-between;align-items:center;'
               'padding:0 5px;height:50%;color:#666;">'
               '<span><span style="color:#444;font-size:9px;margin-right:3px;">{s}</span>{t}</span>'
               '</div>')
        return (f'<div style="background:#162032;border:1px solid #2d4a6e;border-radius:4px;'
                f'width:{GAME_W}px;height:{GAME_H}px;font-size:10.5px;overflow:hidden;box-sizing:border-box;">'
                f'{row.format(s=s1,t=t1)}'
                f'<hr style="margin:0;border:none;border-top:1px solid #1e3350;">'
                f'{row.format(s=s2,t=t2)}</div>')

    wp   = slot.win_prob
    color = conf_color(wp)
    t1w  = slot.winner == slot.team1
    t2w  = slot.winner == slot.team2

    pct_str = f"{wp:.0%}"
    margin_str = f"{slot.margin:.1f}pts"

    def team_row(name, seed, is_winner):
        c  = "#2ecc71" if is_winner else "#888"
        fw = "600"     if is_winner else "400"
        badge = f'<span style="color:#0d1117;background:{color};font-size:8px;padding:0 3px;border-radius:2px;margin-left:4px;">{pct_str}</span>' if is_winner else f'<span style="font-size:9px;color:#555;margin-left:4px;">{margin_str}</span>'
        return (f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:0 5px;height:50%;color:{c};font-weight:{fw};">'
                f'<span style="min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'
                f'<span style="color:#6a8aaa;font-size:9px;margin-right:3px;">{esc(seed or "")}</span>'
                f'{clip(name)}{badge}</span></div>')

    r1 = team_row(slot.team1, slot.seed1, t1w)
    r2 = team_row(slot.team2, slot.seed2, t2w)
    divider = '<hr style="margin:0;border:none;border-top:1px solid #1e3350;">'

    return (f'<div style="background:#162032;border:1px solid {color};border-radius:4px;'
            f'width:{GAME_W}px;height:{GAME_H}px;font-size:10.5px;overflow:hidden;box-sizing:border-box;">'
            f'{r1}{divider}{r2}</div>')


def slot_cy(si, n, y_off=0):
    step = REG_H / n
    return y_off + step * (si + 0.5)

def elbow(x1, y1, x2, y2, color="#2d4a6e"):
    mx = (x1 + x2) / 2
    return (f'<polyline points="{x1},{y1} {mx},{y1} {mx},{y2} {x2},{y2}" '
            f'fill="none" stroke="{color}" stroke-width="1.5"/>')

def right_card_x(ri):
    return TOTAL_W - (ri + 1) * ROUND_W

# ---------------------------------------------------------------------------
# Full bracket HTML builder
# ---------------------------------------------------------------------------
def build_bracket_html(games):
    region_rounds = {r: build_region_slots(games, r) for r in REGIONS}
    ff_left, ff_right, champ = build_center_slots(games)

    cards = []
    lines = []

    def winner_color(slot):
        return conf_color(slot.win_prob) if slot.winner else "#2d4a6e"

    def place_left(y_off, rounds):
        r64, r32, s16, e8 = rounds
        all_rounds = [(r64,8),(r32,4),(s16,2),(e8,1)]
        for ri, (slots, n) in enumerate(all_rounds):
            cx = ri * ROUND_W
            for si, sl in enumerate(slots):
                cy = slot_cy(si, n, y_off)
                cards.append((cx, cy - GAME_H/2, game_card(sl)))
                if ri < 3:
                    next_n  = all_rounds[ri+1][1]
                    next_si = si // 2
                    lines.append(elbow(cx + GAME_W, cy,
                                       (ri+1)*ROUND_W,
                                       slot_cy(next_si, next_n, y_off),
                                       winner_color(sl)))
        if e8:
            lines.append(elbow(3*ROUND_W + GAME_W, slot_cy(0,1,y_off),
                               LEFT_FF_X, HALF_H/2,
                               winner_color(e8[0])))

    def place_right(y_off, rounds):
        r64, r32, s16, e8 = rounds
        all_rounds = [(r64,8),(r32,4),(s16,2),(e8,1)]
        for ri, (slots, n) in enumerate(all_rounds):
            cx = right_card_x(ri)
            for si, sl in enumerate(slots):
                cy = slot_cy(si, n, y_off)
                cards.append((cx, cy - GAME_H/2, game_card(sl)))
                if ri < 3:
                    next_n  = all_rounds[ri+1][1]
                    next_si = si // 2
                    x2 = right_card_x(ri+1) + GAME_W
                    y2 = slot_cy(next_si, next_n, y_off)
                    mx = (cx + x2) / 2
                    c  = winner_color(sl)
                    lines.append(
                        f'<polyline points="{cx},{cy} {mx},{cy} {mx},{y2} {x2},{y2}" '
                        f'fill="none" stroke="{c}" stroke-width="1.5"/>')
        if e8:
            x1 = right_card_x(3)
            x2 = RIGHT_FF_X + GAME_W
            lines.append(elbow(x1, slot_cy(0,1,y_off), x2, HALF_H/2,
                               winner_color(e8[0])))

    place_left(0,      region_rounds["East"])
    place_left(REG_H,  region_rounds["South"])
    place_right(0,      region_rounds["West"])
    place_right(REG_H,  region_rounds["Midwest"])

    # Center cards
    ff_y  = HALF_H/2 - GAME_H/2
    cards.append((LEFT_FF_X,  ff_y, game_card(ff_left)))
    cards.append((RIGHT_FF_X, ff_y, game_card(ff_right)))
    cards.append((CHAMP_X,    ff_y, game_card(champ)))

    # FF → Champ connectors
    ff_cy  = HALF_H/2
    c_left  = conf_color(ff_left.win_prob)  if ff_left.winner  else "#2d4a6e"
    c_right = conf_color(ff_right.win_prob) if ff_right.winner else "#2d4a6e"
    lines.append(f'<line x1="{LEFT_FF_X+GAME_W}" y1="{ff_cy}" x2="{CHAMP_X}" y2="{ff_cy}" '
                 f'stroke="{c_left}" stroke-width="1.5"/>')
    lines.append(f'<line x1="{CHAMP_X+GAME_W}" y1="{ff_cy}" x2="{RIGHT_FF_X}" y2="{ff_cy}" '
                 f'stroke="{c_right}" stroke-width="1.5"/>')

    # Labels
    lbl = ("position:absolute;font-size:9px;color:#4a7aaa;font-weight:700;"
           "letter-spacing:.8px;text-align:center;white-space:nowrap;")
    label_html = ""
    for ri, txt in enumerate(["R64","R32","S16","E8"]):
        lx = ri * ROUND_W + GAME_W/2 - 20
        label_html += f'<div style="{lbl}left:{lx}px;top:4px;width:40px;">{txt}</div>'
    for ri, txt in enumerate(["E8","S16","R32","R64"]):
        lx = right_card_x(3-ri) + GAME_W/2 - 20
        label_html += f'<div style="{lbl}left:{lx}px;top:4px;width:40px;">{txt}</div>'
    cx = CHAMP_X + GAME_W/2
    label_html += f'<div style="{lbl}left:{cx-30}px;top:4px;width:60px;color:#e8c84a;">CHAMP</div>'

    reg = ("position:absolute;font-size:11px;color:#4a8aff;font-weight:700;"
           "letter-spacing:1px;text-align:center;z-index:20;"
           "background:rgba(13,17,23,0.85);padding:1px 6px;border-radius:3px;")
    left_cx  = (4 * ROUND_W) / 2 - 25
    right_cx = TOTAL_W - (4 * ROUND_W) / 2 - 25
    label_html += f'<div style="{reg}left:{left_cx}px;top:{LABEL_H+6}px;">EAST</div>'
    label_html += f'<div style="{reg}left:{left_cx}px;top:{LABEL_H+REG_H+6}px;">SOUTH</div>'
    label_html += f'<div style="{reg}left:{right_cx}px;top:{LABEL_H+6}px;">WEST</div>'
    label_html += f'<div style="{reg}left:{right_cx}px;top:{LABEL_H+REG_H+6}px;">MIDWEST</div>'

    CONTAINER_H = HALF_H + LABEL_H + 4
    CONTAINER_W = TOTAL_W + 20

    svg = (f'<svg style="position:absolute;top:0;left:0;pointer-events:none;overflow:visible;" '
           f'width="{CONTAINER_W}" height="{CONTAINER_H}">'
           f'<g transform="translate(0,{LABEL_H})">'
           + "".join(lines) + "</g></svg>")

    card_html = "".join(
        f'<div style="position:absolute;left:{cx}px;top:{LABEL_H+cy}px;">{html}</div>'
        for (cx, cy, html) in cards
    )

    # Legend
    legend = (
        '<div style="position:absolute;bottom:6px;left:50%;transform:translateX(-50%);'
        'display:flex;gap:12px;font-size:10px;color:#888;">'
        '<span style="color:#2ecc71;">■</span> ≥75% '
        '<span style="color:#f1c40f;">■</span> 60–75% '
        '<span style="color:#e67e22;">■</span> 50–60% '
        '<span style="color:#e74c3c;">■</span> Upset'
        '</div>'
    )

    return (f'<div style="position:relative;width:{CONTAINER_W}px;height:{CONTAINER_H+24}px;'
            f'background:#0d1117;font-family:\'Segoe UI\',system-ui,sans-serif;">'
            f'{svg}{card_html}{label_html}{legend}</div>')

# ---------------------------------------------------------------------------
# Session state: extra added scenarios + removed set
# ---------------------------------------------------------------------------
if "added_scenarios" not in st.session_state:
    st.session_state.added_scenarios = []   # list of (label, games, fmt)
if "removed_scenarios" not in st.session_state:
    st.session_state.removed_scenarios = set()
if "next_seed" not in st.session_state:
    st.session_state.next_seed = 1000

# Reset when base config changes
state_key = f"cfg_{n_scenarios}_{forced_champ}_{n_forced}"
if st.session_state.get("last_cfg") != state_key:
    st.session_state.removed_scenarios = set()
    st.session_state.added_scenarios   = []
    st.session_state.next_seed         = 1000
    st.session_state.last_cfg          = state_key

# ---------------------------------------------------------------------------
# Sidebar: Add Scenario
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Add Scenario")

add_type = st.sidebar.radio("Type", ["🎲 Random", "👑 Force Champion"], label_visibility="collapsed")

add_champ_pick = "(None)"
if add_type == "👑 Force Champion":
    add_champ_pick = st.sidebar.selectbox("Champion to force", team_names[1:], key="add_champ")

if st.sidebar.button("➕ Add Scenario", type="primary"):
    import random as _rnd
    from bracket.bracket_logic import Bracket
    from bracket.simulator import TournamentSimulator
    from model.predict import Predictor

    seed = st.session_state.next_seed
    st.session_state.next_seed += 1

    predictor = Predictor()
    with get_db() as conn:
        b = Bracket()
        b.load_from_db(conn, CURRENT_SEASON)
        sim = TournamentSimulator(predictor, conn)
        if add_type == "🎲 Random":
            _rnd.seed(seed)
            new_games = sim.simulate_random(b)
            label = f"🎲 Added #{len(st.session_state.added_scenarios)+1}"
            fmt   = f"Added scenario champion: **{{winner}}** ({{prob:.1%}})"
        else:
            new_games = sim.simulate_forced_champion(b, add_champ_pick, seed=seed)
            label = f"👑 {add_champ_pick} #{len(st.session_state.added_scenarios)+1}"
            fmt   = f"{add_champ_pick} wins ({{prob:.1%}})"

    st.session_state.added_scenarios.append((label, new_games, fmt))
    st.rerun()

# Build full scenario list
all_scenarios = []
all_scenarios.append(("🏆 Best Prediction", det_games,
                      "Model's top pick: **{winner}** wins ({prob:.1%})"))
for i, games in enumerate(rand_scenarios):
    all_scenarios.append((f"🎲 Scenario {i+1}", games,
                          f"Scenario {i+1} champion: **{{winner}}** ({{prob:.1%}})"))
for i, games in enumerate(forced_scenarios):
    all_scenarios.append((f"👑 {forced_champ} #{i+1}", games,
                          f"{forced_champ} wins ({{prob:.1%}})"))
for label, games, fmt in st.session_state.added_scenarios:
    all_scenarios.append((label, games, fmt))

active = [(i, label, games, fmt)
          for i, (label, games, fmt) in enumerate(all_scenarios)
          if i not in st.session_state.removed_scenarios]

# ---------------------------------------------------------------------------
# Sidebar: Remove Scenarios
# ---------------------------------------------------------------------------
if len(active) > 1:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Remove Scenarios")
    for i, label, _, _ in active[1:]:   # Best Prediction always stays
        if st.sidebar.button(f"🗑 {label}", key=f"rm_{i}"):
            st.session_state.removed_scenarios.add(i)
            st.rerun()

# ---------------------------------------------------------------------------
# Tabs: one per active scenario + Championship Odds
# ---------------------------------------------------------------------------
tab_labels = [label for _, label, _, _ in active] + ["📊 Championship Odds"]
all_tabs   = st.tabs(tab_labels)

for tab_idx, (scen_idx, label, games, fmt) in enumerate(active):
    with all_tabs[tab_idx]:
        champ = next((g for g in games if g["round"] == "Championship"), None)
        if champ:
            st.caption(fmt.format(winner=champ["winner"].name, prob=champ["win_prob"]))
        html = build_bracket_html(games)
        components.html(
            f'<html><body style="margin:0;padding:8px;background:#0d1117;'
            f'overflow-x:auto;overflow-y:hidden;">{html}</body></html>',
            height=HALF_H + LABEL_H + 60,
            scrolling=True,
        )

with all_tabs[-1]:
    if mc_results:
        st.subheader("Championship Odds (Monte Carlo)")
        odds_data = []
        for tid, data in mc_results.items():
            team = data["team"]
            odds_data.append({
                "Seed": team.seed,
                "Team": team.name,
                "Region": team.region,
                "Championship %": data["championship_pct"],
                "Final Four %": data["final_four_pct"],
                "Elite 8 %": data["elite_eight_pct"],
                "Sweet 16 %": data["sweet_sixteen_pct"],
            })
        df = pd.DataFrame(odds_data).sort_values("Championship %", ascending=False).head(30).reset_index(drop=True)
        df.index += 1
        st.dataframe(
            df.style.format({
                "Championship %": "{:.1f}%", "Final Four %": "{:.1f}%",
                "Elite 8 %": "{:.1f}%",      "Sweet 16 %": "{:.1f}%",
            }),
            use_container_width=True,
        )
        top = df.head(16)
        fig = go.Figure(go.Bar(
            x=top["Team"], y=top["Championship %"],
            marker_color=[conf_color(p/100) for p in top["Championship %"]],
            text=[f"{v:.1f}%" for v in top["Championship %"]],
            textposition="outside",
        ))
        fig.update_layout(title="Top 16 Championship Contenders",
                          xaxis_title="Team", yaxis_title="Win Probability (%)",
                          height=450, plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
                          font_color="#ccc")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Switch to **Monte Carlo** mode in the sidebar to see championship odds.")
