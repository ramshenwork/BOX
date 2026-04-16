"""
CricketLive Impact Points Calculator Engine
============================================
Evaluates each player's performance using:
  - Batting Impact (runs, SR, contribution %, pressure)
  - Bowling Impact (wickets by position, economy, phase)
  - Fielding Impact (catches, run-outs, stumpings)
  - Match Difficulty Index (MDI)
  - Entry Pressure + Dynamic Pressure
  - Man of the Match selection with reasoning
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import math


# ─────────────────────────────────────────────
#  DATA STRUCTURES
# ─────────────────────────────────────────────

@dataclass
class BallEvent:
    over: int
    ball: int
    batter: str
    bowler: str
    runs: int
    extras: int
    extra_type: Optional[str]   # 'wide', 'nb_leg', 'nb_height', None
    wicket: bool
    wicket_type: Optional[str]  # 'bowled', 'caught', 'runout', None
    innings: int                # 1 or 2


@dataclass
class PlayerInnings:
    name: str
    team: str
    # Batting
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    out: bool = False
    out_desc: str = ""
    did_bat: bool = False
    batting_position: int = 0   # 1 = opener
    # Bowling
    balls_bowled: int = 0
    wickets: int = 0
    runs_conceded: int = 0
    wides: int = 0
    no_balls: int = 0
    # Fielding
    catches: int = 0
    run_outs: int = 0
    stumpings: int = 0
    # Computed
    entry_score: int = 0        # team score when this batter arrived
    entry_wickets: int = 0      # wickets fallen when batter arrived
    phase_runs: Dict[str, int] = field(default_factory=dict)   # powerplay/middle/death runs scored
    phase_balls: Dict[str, int] = field(default_factory=dict)


@dataclass
class InningsData:
    innings_num: int            # 1 or 2
    batting_team: str
    bowling_team: str
    total_runs: int = 0
    total_wickets: int = 0
    total_balls: int = 0        # legal deliveries
    extras: int = 0
    target: Optional[int] = None  # only for innings 2
    balls: List[BallEvent] = field(default_factory=list)
    batters: List[PlayerInnings] = field(default_factory=list)
    bowlers: List[PlayerInnings] = field(default_factory=list)
    fall_of_wickets: List[Dict] = field(default_factory=list)  # [{score, over, batter}]


@dataclass
class FieldingEvent:
    player: str
    team: str
    event_type: str     # 'catch', 'runout', 'stumping'
    innings: int


@dataclass
class ImpactScore:
    player: str
    team: str
    batting_impact: float = 0.0
    bowling_impact: float = 0.0
    fielding_impact: float = 0.0
    pressure_multiplier: float = 1.0
    mdi_adjustment: float = 1.0
    raw_total: float = 0.0
    final_score: float = 0.0
    # Sub-components for reasoning
    runs_component: float = 0.0
    sr_component: float = 0.0
    contribution_component: float = 0.0
    entry_pressure: float = 0.0
    dynamic_pressure: float = 0.0
    wickets_component: float = 0.0
    economy_component: float = 0.0
    phase_component: float = 0.0
    reasoning: str = ""


# ─────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────

EXPECTED_RUN_RATE = 6.5        # baseline RR for normalisation
MAX_BATTING_IMPACT = 60.0
MAX_BOWLING_IMPACT = 40.0
MAX_FIELDING_IMPACT = 15.0

# Phase boundaries (overs, 0-indexed)
POWERPLAY_END = 6
MIDDLE_END = 15

# Wicket weights by batting position (top-order dismissal = more impact)
WICKET_POSITION_WEIGHTS = {
    1: 2.0, 2: 1.8, 3: 2.0, 4: 1.7, 5: 1.5,
    6: 1.3, 7: 1.1, 8: 1.0, 9: 0.9, 10: 0.8, 11: 0.7
}

# Phase bowling weights
PHASE_BOWL_WEIGHTS = {
    'powerplay': 1.3,
    'middle': 1.0,
    'death': 1.4
}

# Phase batting weights
PHASE_BAT_WEIGHTS = {
    'powerplay': 1.1,
    'middle': 1.0,
    'death': 1.3
}


# ─────────────────────────────────────────────
#  HELPER FUNCTIONS
# ─────────────────────────────────────────────

def overs_to_balls(overs_str: str) -> int:
    parts = str(overs_str).split('.')
    return int(parts[0]) * 6 + int(parts[1]) if len(parts) == 2 else int(parts[0]) * 6


def balls_to_overs(balls: int) -> float:
    return balls // 6 + (balls % 6) / 10


def get_phase(over: int) -> str:
    if over < POWERPLAY_END:
        return 'powerplay'
    elif over < MIDDLE_END:
        return 'middle'
    else:
        return 'death'


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def safe_divide(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default


# ─────────────────────────────────────────────
#  MATCH DIFFICULTY INDEX
# ─────────────────────────────────────────────

def compute_mdi(innings1: InningsData, innings2: Optional[InningsData]) -> float:
    """
    MDI: compares actual match run rate to expected baseline.
    High-scoring match → higher MDI for batters, slightly lower for bowlers.
    Low-scoring match → higher MDI for bowlers, slightly lower for batters.
    Returns a normalised multiplier between 0.7 and 1.4.
    """
    rr1 = safe_divide(innings1.total_runs * 6, innings1.total_balls, EXPECTED_RUN_RATE)

    if innings2 and innings2.total_balls > 0:
        rr2 = safe_divide(innings2.total_runs * 6, innings2.total_balls, EXPECTED_RUN_RATE)
        avg_rr = (rr1 + rr2) / 2
    else:
        avg_rr = rr1

    # Ratio vs expected baseline
    ratio = safe_divide(avg_rr, EXPECTED_RUN_RATE, 1.0)

    # Normalise to 0.7–1.4 range using log-ish curve
    mdi = 0.7 + 0.7 * clamp(ratio, 0.5, 1.5) / 1.5
    return round(mdi, 3)


# ─────────────────────────────────────────────
#  PRESSURE CALCULATIONS
# ─────────────────────────────────────────────

def compute_entry_pressure(innings: InningsData, batter: PlayerInnings) -> float:
    """
    Entry pressure: how difficult was the situation when this batter came in?
    Factors: wickets lost, run rate deficit, collapse index.
    """
    max_balls = innings.total_balls if innings.total_balls > 0 else 120
    wickets_at_entry = batter.entry_wickets
    score_at_entry = batter.entry_score

    # Wicket pressure: more wickets lost = higher pressure
    wicket_pressure = (wickets_at_entry / 10.0) * 3.0

    # Collapse pressure: wickets lost quickly
    collapse_bonus = 0.0
    if wickets_at_entry >= 2:
        # Check if last 2 wickets fell within 10 runs
        fow = innings.fall_of_wickets
        if len(fow) >= 2:
            last2_runs = fow[-1]['score'] - fow[-2]['score'] if len(fow) >= 2 else 20
            if last2_runs <= 10:
                collapse_bonus = 1.5
            elif last2_runs <= 20:
                collapse_bonus = 0.8

    # Run-rate pressure (innings 2 only)
    rrr_pressure = 0.0
    if innings.innings_num == 2 and innings.target and score_at_entry is not None:
        balls_remaining = max_balls - batter.entry_score  # proxy
        runs_needed = innings.target - score_at_entry
        if balls_remaining > 0:
            required_rr = safe_divide(runs_needed * 6, balls_remaining, 6.0)
            rrr_pressure = clamp((required_rr - EXPECTED_RUN_RATE) / EXPECTED_RUN_RATE, 0, 2.0)

    total = wicket_pressure + collapse_bonus + rrr_pressure
    return clamp(total, 0.0, 5.0)


def compute_dynamic_pressure_batting(
    innings: InningsData,
    batter: PlayerInnings,
    ball_sequence: List[BallEvent]
) -> float:
    """
    Dynamic pressure: what was the run-rate situation DURING the batter's innings?
    Phase-by-phase comparison of required vs actual run rate.
    """
    if not ball_sequence or innings.total_balls == 0:
        return 1.0

    phase_pressures = []
    total_balls = innings.total_balls if innings.total_balls > 0 else 1

    # Build over-by-over cumulative state
    cum_runs = 0
    cum_balls = 0

    for event in ball_sequence:
        if event.batter != batter.name:
            continue
        if event.extra_type in ('wide', 'nb_leg', 'nb_height'):
            continue

        phase = get_phase(event.over)
        cum_balls += 1
        cum_runs += event.runs

        if innings.innings_num == 2 and innings.target:
            # Required vs current
            remaining_balls = total_balls - cum_balls
            remaining_runs = innings.target - (innings.total_runs - (batter.runs - cum_runs))
            if remaining_balls > 0:
                rrr = safe_divide(remaining_runs * 6, remaining_balls, 6.0)
                crr = safe_divide(innings.total_runs * 6, cum_balls, 0)
                pressure = clamp((rrr - crr) / max(crr, 1), 0, 3.0)
                phase_pressures.append(pressure * PHASE_BAT_WEIGHTS[phase])
        else:
            # First innings: compare vs expected run rate per phase
            expected = {'powerplay': 7.5, 'middle': 6.0, 'death': 8.5}[phase]
            current_rr = safe_divide(cum_runs * 6, cum_balls, 0)
            # Lower RR than expected = scoring under pressure
            pressure = clamp((expected - current_rr) / expected, 0, 2.0)
            phase_pressures.append(pressure * PHASE_BAT_WEIGHTS[phase])

    if not phase_pressures:
        return 1.0

    return clamp(sum(phase_pressures) / len(phase_pressures), 0.5, 3.5)


def compute_bowling_pressure(
    innings: InningsData,
    bowler: PlayerInnings,
    ball_sequence: List[BallEvent]
) -> float:
    """
    Bowling pressure: economy relative to match context.
    Bowling tight when RRR is high = high pressure performance.
    """
    if bowler.balls_bowled == 0:
        return 1.0

    bowler_runs = bowler.runs_conceded
    bowler_balls = bowler.balls_bowled
    bowler_economy = safe_divide(bowler_runs * 6, bowler_balls, 6.0)

    if innings.innings_num == 2 and innings.target and innings.total_balls > 0:
        # Compare economy to required run rate at time of bowling
        avg_rrr = safe_divide((innings.target - innings.total_runs) * 6,
                               max(innings.total_balls * 6 - innings.total_balls, 1), 6.0)
        pressure = clamp((avg_rrr - bowler_economy) / max(avg_rrr, 1), 0, 2.5)
    else:
        # First innings: compare to expected RR
        match_rr = safe_divide(innings.total_runs * 6, innings.total_balls, EXPECTED_RUN_RATE)
        pressure = clamp((match_rr - bowler_economy) / max(match_rr, 1), 0, 2.5)

    # Phase weight: which phases did this bowler bowl in?
    phase_weight = 1.0
    bowler_overs_phases = {'powerplay': 0, 'middle': 0, 'death': 0}
    for event in ball_sequence:
        if event.bowler == bowler.name and not event.extra_type:
            bowler_overs_phases[get_phase(event.over)] += 1
    dominant_phase = max(bowler_overs_phases, key=bowler_overs_phases.get)
    phase_weight = PHASE_BOWL_WEIGHTS[dominant_phase]

    return clamp(pressure * phase_weight, 0.5, 3.5)


# ─────────────────────────────────────────────
#  BATTING IMPACT
# ─────────────────────────────────────────────

def compute_batting_impact(
    innings: InningsData,
    batter: PlayerInnings,
    ball_sequence: List[BallEvent],
    mdi: float
) -> Tuple[float, Dict]:
    """
    Returns (batting_impact_score, components_dict)
    """
    if not batter.did_bat or batter.balls == 0:
        return 0.0, {}

    team_runs = innings.total_runs if innings.total_runs > 0 else 1
    team_balls = innings.total_balls if innings.total_balls > 0 else 1
    team_sr = safe_divide(team_runs * 100, team_balls, 100)

    # 1. Runs component (log-scaled, diminishing returns)
    runs_score = math.log1p(batter.runs) * 6.0

    # 2. Strike rate component vs team SR
    batter_sr = safe_divide(batter.runs * 100, batter.balls, 0)
    sr_ratio = safe_divide(batter_sr, team_sr, 1.0)
    sr_score = clamp((sr_ratio - 0.8) * 8.0, -4.0, 12.0)

    # 3. Contribution % to team total
    contribution_pct = safe_divide(batter.runs, team_runs, 0)
    contribution_score = contribution_pct * 15.0

    # 4. Milestone bonuses
    milestone_bonus = 0.0
    if batter.runs >= 100:
        milestone_bonus = 10.0
    elif batter.runs >= 75:
        milestone_bonus = 6.0
    elif batter.runs >= 50:
        milestone_bonus = 4.0
    elif batter.runs >= 30:
        milestone_bonus = 2.0

    # 4b. Boundary bonus
    boundary_bonus = (batter.fours * 0.3) + (batter.sixes * 0.6)

    # 5. Not out bonus (especially in successful chase)
    not_out_bonus = 0.0
    if not batter.out:
        not_out_bonus = 2.0
        if innings.innings_num == 2 and innings.target and innings.total_runs >= innings.target:
            not_out_bonus = 5.0  # finished the chase

    # 6. Entry pressure (30% weight)
    entry_p = compute_entry_pressure(innings, batter)

    # 7. Dynamic pressure (70% weight)
    dynamic_p = compute_dynamic_pressure_batting(innings, batter, ball_sequence)

    # Combined pressure multiplier
    pressure_combined = 0.3 * entry_p + 0.7 * dynamic_p
    pressure_multiplier = 1.0 + clamp(pressure_combined / 5.0, 0, 0.8)

    # Raw batting impact
    raw = (runs_score + sr_score + contribution_score +
           milestone_bonus + boundary_bonus + not_out_bonus)

    # Apply pressure and MDI
    adjusted = raw * pressure_multiplier * (0.6 + 0.4 * mdi)
    final = clamp(adjusted, 0.0, MAX_BATTING_IMPACT)

    components = {
        'runs_component': round(runs_score, 2),
        'sr_component': round(sr_score, 2),
        'contribution_component': round(contribution_score, 2),
        'milestone_bonus': round(milestone_bonus, 2),
        'boundary_bonus': round(boundary_bonus, 2),
        'not_out_bonus': round(not_out_bonus, 2),
        'entry_pressure': round(entry_p, 2),
        'dynamic_pressure': round(dynamic_p, 2),
        'pressure_multiplier': round(pressure_multiplier, 3),
    }
    return round(final, 2), components


# ─────────────────────────────────────────────
#  BOWLING IMPACT
# ─────────────────────────────────────────────

def compute_bowling_impact(
    innings: InningsData,
    bowler: PlayerInnings,
    ball_sequence: List[BallEvent],
    mdi: float
) -> Tuple[float, Dict]:
    """
    Returns (bowling_impact_score, components_dict)
    """
    if bowler.balls_bowled == 0:
        return 0.0, {}

    team_runs = innings.total_runs if innings.total_runs > 0 else 1

    # 1. Wickets component (weighted by batting position)
    wicket_score = 0.0
    # Figure out which batters this bowler dismissed and their positions
    dismissed = []
    for event in ball_sequence:
        if event.bowler == bowler.name and event.wicket and event.wicket_type != 'runout':
            dismissed.append(event.batter)

    for batter_name in dismissed:
        # Find batting position
        bat_pos = next(
            (b.batting_position for b in innings.batters if b.name == batter_name),
            6
        )
        weight = WICKET_POSITION_WEIGHTS.get(bat_pos, 1.0)
        wicket_score += 8.0 * weight

    # Wicket haul bonuses
    if bowler.wickets >= 5:
        wicket_score += 10.0
    elif bowler.wickets >= 4:
        wicket_score += 6.0
    elif bowler.wickets >= 3:
        wicket_score += 3.0

    # 2. Economy component
    economy = safe_divide(bowler.runs_conceded * 6, bowler.balls_bowled, 6.0)
    match_rr = safe_divide(team_runs * 6, innings.total_balls, EXPECTED_RUN_RATE)
    eco_diff = match_rr - economy  # positive = bowling below run rate = good
    eco_score = clamp(eco_diff * 1.5, -6.0, 10.0)

    # 3. Maidens proxy (overs with 0 runs)
    maiden_score = 0.0
    over_runs: Dict[int, int] = {}
    for event in ball_sequence:
        if event.bowler == bowler.name:
            over_runs[event.over] = over_runs.get(event.over, 0) + event.runs + event.extras
    maidens = sum(1 for r in over_runs.values() if r == 0)
    maiden_score = maidens * 1.5

    # 4. Phase importance
    pressure_mult = compute_bowling_pressure(innings, bowler, ball_sequence)

    # Raw bowling impact
    raw = wicket_score + eco_score + maiden_score

    # Apply pressure and MDI (inverted for bowlers — harder to bowl in high-scoring games)
    mdi_bowl = 0.6 + 0.4 * (2.0 - mdi)   # inverted MDI
    adjusted = raw * (1.0 + clamp((pressure_mult - 1.0) * 0.5, 0, 0.6)) * clamp(mdi_bowl, 0.7, 1.3)
    final = clamp(adjusted, 0.0, MAX_BOWLING_IMPACT)

    components = {
        'wickets_component': round(wicket_score, 2),
        'economy_component': round(eco_score, 2),
        'maiden_component': round(maiden_score, 2),
        'pressure_multiplier': round(pressure_mult, 3),
        'economy': round(economy, 2),
        'match_rr': round(match_rr, 2),
    }
    return round(final, 2), components


# ─────────────────────────────────────────────
#  FIELDING IMPACT
# ─────────────────────────────────────────────

def compute_fielding_impact(player: PlayerInnings) -> float:
    score = (
        player.catches * 3.0 +
        player.run_outs * 4.0 +
        player.stumpings * 4.5
    )
    return clamp(score, 0.0, MAX_FIELDING_IMPACT)


# ─────────────────────────────────────────────
#  GENERATE REASONING
# ─────────────────────────────────────────────

def generate_reasoning(
    player: str,
    imp: ImpactScore,
    batter_data: Optional[PlayerInnings],
    bowler_data: Optional[PlayerInnings],
    is_mom: bool,
    mdi: float
) -> str:
    parts = []

    if is_mom:
        parts.append(f"🏆 MAN OF THE MATCH")

    if batter_data and batter_data.did_bat and batter_data.runs > 0:
        sr = round(safe_divide(batter_data.runs * 100, batter_data.balls, 0))
        parts.append(f"Scored {batter_data.runs} off {batter_data.balls} balls (SR: {sr})")
        if batter_data.fours or batter_data.sixes:
            parts.append(f"{batter_data.fours}×4, {batter_data.sixes}×6")
        if imp.entry_pressure > 2.0:
            parts.append("Came in under high pressure")
        if imp.dynamic_pressure > 1.5:
            parts.append("Performed under difficult match conditions")
        if not batter_data.out:
            parts.append("Remained not out")

    if bowler_data and bowler_data.balls_bowled > 0:
        overs = f"{bowler_data.balls_bowled // 6}.{bowler_data.balls_bowled % 6}"
        eco = round(safe_divide(bowler_data.runs_conceded * 6, bowler_data.balls_bowled, 0), 2)
        parts.append(f"Bowled {overs} overs: {bowler_data.wickets}/{bowler_data.runs_conceded} (Eco: {eco})")

    if batter_data and (batter_data.catches + batter_data.run_outs + batter_data.stumpings) > 0:
        f_str = []
        if batter_data.catches: f_str.append(f"{batter_data.catches} catch{'es' if batter_data.catches > 1 else ''}")
        if batter_data.run_outs: f_str.append(f"{batter_data.run_outs} run-out")
        if batter_data.stumpings: f_str.append(f"{batter_data.stumpings} stumping")
        parts.append("Fielding: " + ", ".join(f_str))

    if mdi < 0.85:
        parts.append("Match played on a difficult pitch (low MDI)")
    elif mdi > 1.15:
        parts.append("High-scoring match (high MDI)")

    return " · ".join(parts)


# ─────────────────────────────────────────────
#  MAIN ENGINE ENTRY POINT
# ─────────────────────────────────────────────

def calculate_impact(
    innings1: InningsData,
    innings2: Optional[InningsData],
    fielding_events: List[FieldingEvent]
) -> Dict:
    """
    Full engine: compute impact scores for all players across both innings.
    Returns a ranked list of ImpactScore objects and the MOM.
    """

    # 1. Match Difficulty Index
    mdi = compute_mdi(innings1, innings2)

    # 2. Apply fielding events to player objects
    all_innings = [inn for inn in [innings1, innings2] if inn is not None]
    player_map: Dict[str, PlayerInnings] = {}

    for inn in all_innings:
        for b in inn.batters:
            key = b.name
            if key not in player_map:
                player_map[key] = b
        for bw in inn.bowlers:
            key = bw.name
            if key not in player_map:
                player_map[key] = bw

    for fe in fielding_events:
        p = player_map.get(fe.player)
        if p:
            if fe.event_type == 'catch':
                p.catches += 1
            elif fe.event_type == 'runout':
                p.run_outs += 1
            elif fe.event_type == 'stumping':
                p.stumpings += 1

    # 3. Build all-balls list per innings
    impact_scores: Dict[str, ImpactScore] = {}

    for inn in all_innings:
        ball_seq = inn.balls

        for batter in inn.batters:
            name = batter.name
            bat_imp, bat_comp = compute_batting_impact(inn, batter, ball_seq, mdi)
            if name not in impact_scores:
                impact_scores[name] = ImpactScore(player=name, team=batter.team)
            impact_scores[name].batting_impact += bat_imp
            # Store sub-components
            impact_scores[name].runs_component += bat_comp.get('runs_component', 0)
            impact_scores[name].sr_component += bat_comp.get('sr_component', 0)
            impact_scores[name].contribution_component += bat_comp.get('contribution_component', 0)
            impact_scores[name].entry_pressure = max(
                impact_scores[name].entry_pressure, bat_comp.get('entry_pressure', 0))
            impact_scores[name].dynamic_pressure = max(
                impact_scores[name].dynamic_pressure, bat_comp.get('dynamic_pressure', 0))

        for bowler in inn.bowlers:
            name = bowler.name
            bowl_imp, bowl_comp = compute_bowling_impact(inn, bowler, ball_seq, mdi)
            if name not in impact_scores:
                impact_scores[name] = ImpactScore(player=name, team=bowler.team)
            impact_scores[name].bowling_impact += bowl_imp
            impact_scores[name].wickets_component += bowl_comp.get('wickets_component', 0)
            impact_scores[name].economy_component += bowl_comp.get('economy_component', 0)
            impact_scores[name].phase_component += bowl_comp.get('maiden_component', 0)

    # 4. Fielding impact
    for name, imp in impact_scores.items():
        p = player_map.get(name)
        if p:
            imp.fielding_impact = compute_fielding_impact(p)

    # 5. Final scores
    for name, imp in impact_scores.items():
        imp.mdi_adjustment = mdi
        imp.raw_total = imp.batting_impact + imp.bowling_impact + imp.fielding_impact
        imp.final_score = round(imp.raw_total, 2)

    # 6. Rank
    ranked = sorted(impact_scores.values(), key=lambda x: x.final_score, reverse=True)

    # 7. Generate reasoning
    for i, imp in enumerate(ranked):
        batter_data = player_map.get(imp.player)
        bowler_data = player_map.get(imp.player)
        imp.reasoning = generate_reasoning(
            imp.player, imp, batter_data, bowler_data,
            is_mom=(i == 0), mdi=mdi
        )

    # 8. Build result
    mom = ranked[0] if ranked else None

    return {
        'mdi': round(mdi, 3),
        'mdi_label': 'High-scoring' if mdi > 1.1 else ('Low-scoring' if mdi < 0.9 else 'Normal'),
        'man_of_the_match': {
            'player': mom.player if mom else None,
            'team': mom.team if mom else None,
            'score': mom.final_score if mom else 0,
            'reasoning': mom.reasoning if mom else ''
        } if mom else None,
        'leaderboard': [
            {
                'rank': i + 1,
                'player': imp.player,
                'team': imp.team,
                'batting_impact': round(imp.batting_impact, 2),
                'bowling_impact': round(imp.bowling_impact, 2),
                'fielding_impact': round(imp.fielding_impact, 2),
                'final_score': imp.final_score,
                'reasoning': imp.reasoning,
                'components': {
                    'runs': round(imp.runs_component, 2),
                    'strike_rate': round(imp.sr_component, 2),
                    'contribution': round(imp.contribution_component, 2),
                    'entry_pressure': round(imp.entry_pressure, 2),
                    'dynamic_pressure': round(imp.dynamic_pressure, 2),
                    'wickets': round(imp.wickets_component, 2),
                    'economy': round(imp.economy_component, 2),
                    'phase': round(imp.phase_component, 2),
                }
            }
            for i, imp in enumerate(ranked)
        ]
    }


# ─────────────────────────────────────────────
#  BUILD FROM DB DATA
# ─────────────────────────────────────────────

def build_innings_from_db(match_data: dict, innings_num: int) -> Optional[InningsData]:
    """Convert DB match_detail dict into InningsData for the engine."""
    innings_list = match_data.get('innings', [])
    inn_db = next((i for i in innings_list if i['innings_num'] == innings_num), None)
    if not inn_db:
        return None

    inn = InningsData(
        innings_num=innings_num,
        batting_team=inn_db['batting_team'],
        bowling_team=inn_db['bowling_team'],
        total_runs=inn_db['runs'],
        total_wickets=inn_db['wickets'],
        total_balls=inn_db['balls'],
        extras=inn_db['extras'],
        target=match_data['match'].get('target')
    )

    # Batters
    for i, b in enumerate(inn_db.get('batters', [])):
        pi = PlayerInnings(
            name=b['player_name'],
            team=b['team'],
            runs=b['runs'],
            balls=b['balls'],
            fours=b['fours'],
            sixes=b['sixes'],
            out=bool(b['out']),
            out_desc=b.get('out_desc', ''),
            did_bat=bool(b['did_bat']),
            batting_position=i + 1,
            balls_bowled=0,
            wickets=0,
            runs_conceded=0
        )
        inn.batters.append(pi)

    # Bowlers
    for bw in inn_db.get('bowlers', []):
        pi = PlayerInnings(
            name=bw['player_name'],
            team=bw['team'],
            runs=0, balls=0, fours=0, sixes=0,
            did_bat=False,
            balls_bowled=bw['balls_bowled'],
            wickets=bw['wickets'],
            runs_conceded=bw['runs'],
            wides=bw['wides'],
            no_balls=bw['no_balls']
        )
        inn.bowlers.append(pi)

    return inn


def run_impact_for_match(match_data: dict, balls_data: list) -> dict:
    """
    High-level function to run the engine from DB data.
    match_data: result of get_match_detail()
    balls_data: list of ball dicts from the balls table
    """
    # Build ball events
    def make_ball_event(b: dict, innings_num: int) -> BallEvent:
        return BallEvent(
            over=b.get('over_num', 0),
            ball=b.get('ball_num', 0),
            batter=b.get('batter', ''),
            bowler=b.get('bowler', ''),
            runs=b.get('runs', 0),
            extras=b.get('extras', 0),
            extra_type=b.get('extra_type'),
            wicket=bool(b.get('wicket', 0)),
            wicket_type=b.get('wicket_type'),
            innings=innings_num
        )

    inn1 = build_innings_from_db(match_data, 1)
    inn2 = build_innings_from_db(match_data, 2)

    # Attach balls to innings
    if inn1:
        inn1_id = next((i['id'] for i in match_data['innings'] if i['innings_num'] == 1), None)
        inn1.balls = [make_ball_event(b, 1) for b in balls_data if b.get('innings_id') == inn1_id]

    if inn2:
        inn2_id = next((i['id'] for i in match_data['innings'] if i['innings_num'] == 2), None)
        inn2.balls = [make_ball_event(b, 2) for b in balls_data if b.get('innings_id') == inn2_id]
        target_val = match_data['match'].get('target')
        if target_val:
            inn2.target = int(target_val)
        elif inn1:
            # Derive target from innings 1 if not saved
            inn2.target = inn1.total_runs + 1

    return calculate_impact(inn1, inn2, fielding_events=[])