import sqlite3
import json
from datetime import datetime

DB_PATH = "cricket.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Matches table
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team1 TEXT NOT NULL,
            team2 TEXT NOT NULL,
            total_overs INTEGER NOT NULL,
            joker TEXT,
            toss_winner TEXT,
            batting_first TEXT,
            status TEXT DEFAULT 'live',  -- live, completed, aborted
            result TEXT,
            target INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Innings table
    c.execute("""
        CREATE TABLE IF NOT EXISTS innings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            innings_num INTEGER NOT NULL,  -- 1 or 2
            batting_team TEXT NOT NULL,
            bowling_team TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            wickets INTEGER DEFAULT 0,
            balls INTEGER DEFAULT 0,
            extras INTEGER DEFAULT 0,
            wides INTEGER DEFAULT 0,
            no_balls INTEGER DEFAULT 0,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)

    # Ball by ball table
    c.execute("""
        CREATE TABLE IF NOT EXISTS balls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            innings_id INTEGER NOT NULL,
            over_num INTEGER NOT NULL,
            ball_num INTEGER NOT NULL,
            batter TEXT NOT NULL,
            bowler TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            extras INTEGER DEFAULT 0,
            extra_type TEXT,        -- wide, nb_leg, nb_height, null
            wicket INTEGER DEFAULT 0,
            wicket_type TEXT,       -- bowled, runout, caught, null
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (match_id) REFERENCES matches(id),
            FOREIGN KEY (innings_id) REFERENCES innings(id)
        )
    """)

    # Batter stats per innings
    c.execute("""
        CREATE TABLE IF NOT EXISTS batter_innings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            innings_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            team TEXT NOT NULL,
            runs INTEGER DEFAULT 0,
            balls INTEGER DEFAULT 0,
            fours INTEGER DEFAULT 0,
            sixes INTEGER DEFAULT 0,
            out INTEGER DEFAULT 0,
            out_desc TEXT,
            did_bat INTEGER DEFAULT 0,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)

    # Bowler stats per innings
    c.execute("""
        CREATE TABLE IF NOT EXISTS bowler_innings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            innings_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            team TEXT NOT NULL,
            balls_bowled INTEGER DEFAULT 0,
            wickets INTEGER DEFAULT 0,
            runs INTEGER DEFAULT 0,
            wides INTEGER DEFAULT 0,
            no_balls INTEGER DEFAULT 0,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialized")

# ── Match CRUD ──────────────────────────────────────────────

def create_match(team1, team2, total_overs, joker, toss_winner, batting_first):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO matches (team1, team2, total_overs, joker, toss_winner, batting_first)
        VALUES (?,?,?,?,?,?)
    """, (team1, team2, total_overs, joker, toss_winner, batting_first))
    match_id = c.lastrowid
    conn.commit()
    conn.close()
    return match_id

def create_innings(match_id, innings_num, batting_team, bowling_team):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO innings (match_id, innings_num, batting_team, bowling_team)
        VALUES (?,?,?,?)
    """, (match_id, innings_num, batting_team, bowling_team))
    innings_id = c.lastrowid
    conn.commit()
    conn.close()
    return innings_id

def save_ball(match_id, innings_id, over_num, ball_num, batter, bowler,
              runs, extras, extra_type, wicket, wicket_type):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO balls (match_id, innings_id, over_num, ball_num, batter, bowler,
                           runs, extras, extra_type, wicket, wicket_type)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (match_id, innings_id, over_num, ball_num, batter, bowler,
          runs, extras, extra_type, wicket, wicket_type))
    conn.commit()
    conn.close()

def update_innings_score(innings_id, runs, wickets, balls, extras, wides, no_balls):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE innings SET runs=?, wickets=?, balls=?, extras=?, wides=?, no_balls=?
        WHERE id=?
    """, (runs, wickets, balls, extras, wides, no_balls, innings_id))
    conn.commit()
    conn.close()

def save_batter_innings(match_id, innings_id, player_name, team,
                        runs, balls, fours, sixes, out, out_desc, did_bat):
    conn = get_db()
    c = conn.cursor()
    # Upsert - update if exists, insert if not
    existing = c.execute("""
        SELECT id FROM batter_innings WHERE innings_id=? AND player_name=?
    """, (innings_id, player_name)).fetchone()
    if existing:
        c.execute("""
            UPDATE batter_innings SET runs=?,balls=?,fours=?,sixes=?,out=?,out_desc=?,did_bat=?
            WHERE id=?
        """, (runs, balls, fours, sixes, out, out_desc, did_bat, existing['id']))
    else:
        c.execute("""
            INSERT INTO batter_innings (match_id,innings_id,player_name,team,runs,balls,fours,sixes,out,out_desc,did_bat)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (match_id, innings_id, player_name, team, runs, balls, fours, sixes, out, out_desc, did_bat))
    conn.commit()
    conn.close()

def save_bowler_innings(match_id, innings_id, player_name, team,
                        balls_bowled, wickets, runs, wides, no_balls):
    conn = get_db()
    c = conn.cursor()
    existing = c.execute("""
        SELECT id FROM bowler_innings WHERE innings_id=? AND player_name=?
    """, (innings_id, player_name)).fetchone()
    if existing:
        c.execute("""
            UPDATE bowler_innings SET balls_bowled=?,wickets=?,runs=?,wides=?,no_balls=?
            WHERE id=?
        """, (balls_bowled, wickets, runs, wides, no_balls, existing['id']))
    else:
        c.execute("""
            INSERT INTO bowler_innings (match_id,innings_id,player_name,team,balls_bowled,wickets,runs,wides,no_balls)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (match_id, innings_id, player_name, team, balls_bowled, wickets, runs, wides, no_balls))
    conn.commit()
    conn.close()

def complete_match(match_id, result):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE matches SET status='completed', result=?, updated_at=datetime('now')
        WHERE id=?
    """, (result, match_id))
    conn.commit()
    conn.close()

def abort_match(match_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE matches SET status='aborted', updated_at=datetime('now') WHERE id=?
    """, (match_id,))
    conn.commit()
    conn.close()

# ── Stats queries ────────────────────────────────────────────

def get_all_matches():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT m.*, 
               i1.runs as inn1_runs, i1.wickets as inn1_wkts, i1.balls as inn1_balls,
               i2.runs as inn2_runs, i2.wickets as inn2_wkts, i2.balls as inn2_balls
        FROM matches m
        LEFT JOIN innings i1 ON i1.match_id=m.id AND i1.innings_num=1
        LEFT JOIN innings i2 ON i2.match_id=m.id AND i2.innings_num=2
        ORDER BY m.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_career_batting_stats():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT 
            player_name,
            team,
            COUNT(*) as innings,
            SUM(runs) as total_runs,
            MAX(runs) as high_score,
            ROUND(AVG(runs), 1) as avg_runs,
            SUM(balls) as total_balls,
            SUM(fours) as total_fours,
            SUM(sixes) as total_sixes,
            SUM(CASE WHEN runs >= 50 AND runs < 100 THEN 1 ELSE 0 END) as fifties,
            SUM(CASE WHEN runs >= 100 THEN 1 ELSE 0 END) as hundreds,
            ROUND(CAST(SUM(runs) AS FLOAT) / NULLIF(SUM(balls), 0) * 100, 1) as strike_rate
        FROM batter_innings
        WHERE did_bat = 1
        GROUP BY player_name
        ORDER BY total_runs DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_career_bowling_stats():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT
            player_name,
            team,
            COUNT(*) as innings,
            SUM(balls_bowled) as total_balls,
            SUM(wickets) as total_wickets,
            SUM(runs) as total_runs,
            MAX(wickets) as best_bowling,
            ROUND(CAST(SUM(runs) AS FLOAT) / NULLIF(SUM(balls_bowled), 0) * 6, 2) as economy,
            ROUND(CAST(SUM(balls_bowled) AS FLOAT) / NULLIF(SUM(wickets), 0), 1) as bowling_avg
        FROM bowler_innings
        WHERE balls_bowled > 0
        GROUP BY player_name
        ORDER BY total_wickets DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_match_detail(match_id):
    conn = get_db()
    c = conn.cursor()
    match = c.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return None
    innings = c.execute("SELECT * FROM innings WHERE match_id=? ORDER BY innings_num", (match_id,)).fetchall()
    result = {"match": dict(match), "innings": []}
    for inn in innings:
        inn_dict = dict(inn)
        batters = c.execute("SELECT * FROM batter_innings WHERE innings_id=?", (inn['id'],)).fetchall()
        bowlers = c.execute("SELECT * FROM bowler_innings WHERE innings_id=?", (inn['id'],)).fetchall()
        inn_dict['batters'] = [dict(b) for b in batters]
        inn_dict['bowlers'] = [dict(b) for b in bowlers]
        result['innings'].append(inn_dict)
    conn.close()
    return result


def get_balls_for_match(match_id):
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT b.*, i.innings_num FROM balls b
        JOIN innings i ON b.innings_id = i.id
        WHERE b.match_id = ?
        ORDER BY b.innings_id, b.over_num, b.ball_num
    """, (match_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def store_impact_scores(match_id, impact_data):
    """Store computed impact scores for a match."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS impact_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            team TEXT NOT NULL,
            batting_impact REAL DEFAULT 0,
            bowling_impact REAL DEFAULT 0,
            fielding_impact REAL DEFAULT 0,
            final_score REAL DEFAULT 0,
            is_mom INTEGER DEFAULT 0,
            reasoning TEXT,
            components TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)
    # Delete existing for this match
    c.execute("DELETE FROM impact_scores WHERE match_id=?", (match_id,))
    
    import json
    mom_name = impact_data.get("man_of_the_match", {})
    mom_player = mom_name.get("player") if mom_name else None
    
    for entry in impact_data.get("leaderboard", []):
        c.execute("""
            INSERT INTO impact_scores 
            (match_id, player_name, team, batting_impact, bowling_impact, fielding_impact,
             final_score, is_mom, reasoning, components)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            match_id, entry["player"], entry["team"],
            entry["batting_impact"], entry["bowling_impact"], entry["fielding_impact"],
            entry["final_score"], 1 if entry["player"] == mom_player else 0,
            entry["reasoning"], json.dumps(entry["components"])
        ))
    conn.commit()
    conn.close()


def get_impact_scores(match_id):
    conn = get_db()
    c = conn.cursor()
    # Ensure table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS impact_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            team TEXT NOT NULL,
            batting_impact REAL DEFAULT 0,
            bowling_impact REAL DEFAULT 0,
            fielding_impact REAL DEFAULT 0,
            final_score REAL DEFAULT 0,
            is_mom INTEGER DEFAULT 0,
            reasoning TEXT,
            components TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(id)
        )
    """)
    rows = c.execute("""
        SELECT * FROM impact_scores WHERE match_id=? ORDER BY final_score DESC
    """, (match_id,)).fetchall()
    conn.close()
    import json
    result = []
    for r in rows:
        d = dict(r)
        try: d["components"] = json.loads(d["components"] or "{}")
        except: d["components"] = {}
        result.append(d)
    return result


def save_target_to_match(match_id, target):
    conn = get_db()
    c = conn.cursor()
    # Add column if missing (backward compat)
    try:
        c.execute("ALTER TABLE matches ADD COLUMN target INTEGER")
    except Exception:
        pass
    c.execute("UPDATE matches SET target=? WHERE id=?", (target, match_id))
    conn.commit()
    conn.close()