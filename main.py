from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import uvicorn
import json

from impact_engine import run_impact_for_match
from database import (
    init_db, create_match, create_innings, save_ball,
    update_innings_score, save_batter_innings, save_bowler_innings,
    complete_match, abort_match,
    get_all_matches, get_career_batting_stats, get_career_bowling_stats,
    get_match_detail, get_balls_for_match, store_impact_scores, get_impact_scores,
    save_target_to_match, get_matches_grouped_by_date, get_full_scorecard
)

app = FastAPI(title="CricketLive Scorer")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── WebSocket Connection Manager ─────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.spectators: Dict[int, List[WebSocket]] = {}

    async def connect_spectator(self, match_id: int, ws: WebSocket):
        await ws.accept()
        if match_id not in self.spectators:
            self.spectators[match_id] = []
        self.spectators[match_id].append(ws)

    def disconnect_spectator(self, match_id: int, ws: WebSocket):
        if match_id in self.spectators:
            self.spectators[match_id].remove(ws)

    async def broadcast(self, match_id: int, data: dict):
        if match_id not in self.spectators:
            return
        dead = []
        for ws in self.spectators[match_id]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.spectators[match_id].remove(ws)

    def spectator_count(self, match_id: int) -> int:
        return len(self.spectators.get(match_id, []))

manager = ConnectionManager()

# ── Pydantic Models ──────────────────────────────────────────

class CreateMatchRequest(BaseModel):
    team1: str
    team2: str
    total_overs: int
    joker: Optional[str] = None
    toss_winner: str
    batting_first: str

class CreateInningsRequest(BaseModel):
    match_id: int
    innings_num: int
    batting_team: str
    bowling_team: str

class SaveBallRequest(BaseModel):
    match_id: int
    innings_id: int
    over_num: int
    ball_num: int
    batter: str
    bowler: str
    runs: int = 0
    extras: int = 0
    extra_type: Optional[str] = None
    wicket: int = 0
    wicket_type: Optional[str] = None

class UpdateInningsRequest(BaseModel):
    innings_id: int
    runs: int
    wickets: int
    balls: int
    extras: int
    wides: int
    no_balls: int

class SaveBatterRequest(BaseModel):
    match_id: int
    innings_id: int
    player_name: str
    team: str
    runs: int
    balls: int
    fours: int
    sixes: int
    out: int
    out_desc: Optional[str] = None
    did_bat: int

class SaveBowlerRequest(BaseModel):
    match_id: int
    innings_id: int
    player_name: str
    team: str
    balls_bowled: int
    wickets: int
    runs: int
    wides: int
    no_balls: int

class CompleteMatchRequest(BaseModel):
    match_id: int
    result: str

class LiveStateRequest(BaseModel):
    match_id: int
    state: dict

# ── Page Routes ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/watch/{match_id}", response_class=HTMLResponse)
async def watch(request: Request, match_id: int):
    return templates.TemplateResponse("watch.html", {"request": request, "match_id": match_id})

@app.get("/scorecard/{match_id}", response_class=HTMLResponse)
async def scorecard(request: Request, match_id: int):
    return templates.TemplateResponse("scorecard.html", {"request": request, "match_id": match_id})

@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", {"request": request})

# ── API: Match ───────────────────────────────────────────────

@app.post("/api/match/create")
async def api_create_match(req: CreateMatchRequest):
    match_id = create_match(
        req.team1, req.team2, req.total_overs,
        req.joker, req.toss_winner, req.batting_first
    )
    return {"match_id": match_id}

@app.post("/api/match/complete")
async def api_complete_match(req: CompleteMatchRequest):
    complete_match(req.match_id, req.result)
    await manager.broadcast(req.match_id, {"type": "match_complete", "result": req.result})
    return {"ok": True}

@app.post("/api/match/abort")
async def api_abort_match(req: dict):
    match_id = req.get("match_id")
    abort_match(match_id)
    await manager.broadcast(match_id, {"type": "match_aborted"})
    return {"ok": True}

@app.get("/api/matches")
async def api_get_matches():
    return get_all_matches()

@app.get("/api/match/{match_id}")
async def api_get_match(match_id: int):
    data = get_match_detail(match_id)
    if not data:
        raise HTTPException(status_code=404, detail="Match not found")
    return data

# ── API: Innings ─────────────────────────────────────────────

@app.post("/api/innings/create")
async def api_create_innings(req: CreateInningsRequest):
    innings_id = create_innings(req.match_id, req.innings_num, req.batting_team, req.bowling_team)
    return {"innings_id": innings_id}

@app.post("/api/innings/update")
async def api_update_innings(req: UpdateInningsRequest):
    update_innings_score(req.innings_id, req.runs, req.wickets, req.balls, req.extras, req.wides, req.no_balls)
    return {"ok": True}

# ── API: Ball ────────────────────────────────────────────────

@app.post("/api/ball/save")
async def api_save_ball(req: SaveBallRequest):
    save_ball(
        req.match_id, req.innings_id, req.over_num, req.ball_num,
        req.batter, req.bowler, req.runs, req.extras,
        req.extra_type, req.wicket, req.wicket_type
    )
    return {"ok": True}

# ── API: Player Stats ────────────────────────────────────────

@app.post("/api/batter/save")
async def api_save_batter(req: SaveBatterRequest):
    save_batter_innings(
        req.match_id, req.innings_id, req.player_name, req.team,
        req.runs, req.balls, req.fours, req.sixes, req.out, req.out_desc, req.did_bat
    )
    return {"ok": True}

@app.post("/api/bowler/save")
async def api_save_bowler(req: SaveBowlerRequest):
    save_bowler_innings(
        req.match_id, req.innings_id, req.player_name, req.team,
        req.balls_bowled, req.wickets, req.runs, req.wides, req.no_balls
    )
    return {"ok": True}

@app.get("/api/stats/batting")
async def api_batting_stats():
    return get_career_batting_stats()

@app.get("/api/stats/bowling")
async def api_bowling_stats():
    return get_career_bowling_stats()

# ── API: Live Broadcast ──────────────────────────────────────

@app.post("/api/live/broadcast")
async def api_broadcast(req: LiveStateRequest):
    await manager.broadcast(req.match_id, {"type": "score_update", "state": req.state})
    return {"spectators": manager.spectator_count(req.match_id)}

@app.get("/api/live/spectators/{match_id}")
async def api_spectator_count(match_id: int):
    return {"count": manager.spectator_count(match_id)}

# ── WebSocket ────────────────────────────────────────────────

@app.websocket("/ws/watch/{match_id}")
async def websocket_watch(websocket: WebSocket, match_id: int):
    await manager.connect_spectator(match_id, websocket)
    try:
        await manager.broadcast(match_id, {
            "type": "spectator_count",
            "count": manager.spectator_count(match_id)
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_spectator(match_id, websocket)

# ── History Page ────────────────────────────────────────────

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    return templates.TemplateResponse("history.html", {"request": request})

@app.get("/api/history/matches")
async def api_history_matches():
    """Returns matches grouped by date."""
    grouped = get_matches_grouped_by_date()
    # Convert OrderedDict to list for JSON
    result = []
    for date, matches in grouped.items():
        result.append({"date": date, "matches": matches})
    return result

@app.get("/api/history/scorecard/{match_id}")
async def api_history_scorecard(match_id: int):
    data = get_full_scorecard(match_id)
    if not data:
        raise HTTPException(status_code=404, detail="Match not found")
    return data

# ── API: Impact Engine ──────────────────────────────────────

@app.get("/api/impact/{match_id}")
async def api_get_impact(match_id: int):
    # Return cached scores if available
    cached = get_impact_scores(match_id)
    if cached:
        return cached
    # Compute on demand
    match_data = get_match_detail(match_id)
    if not match_data:
        raise HTTPException(status_code=404, detail="Match not found")
    balls = get_balls_for_match(match_id)
    result = run_impact_for_match(match_data, balls)
    store_impact_scores(match_id, result)
    return result

@app.post("/api/impact/{match_id}/compute")
async def api_compute_impact(match_id: int):
    match_data = get_match_detail(match_id)
    if not match_data:
        raise HTTPException(status_code=404, detail="Match not found")
    balls = get_balls_for_match(match_id)
    result = run_impact_for_match(match_data, balls)
    store_impact_scores(match_id, result)
    await manager.broadcast(match_id, {"type": "impact_update", "data": result})
    return result

class SaveTargetRequest(BaseModel):
    match_id: int
    target: int

@app.post("/api/match/target")
async def api_save_target(req: SaveTargetRequest):
    save_target_to_match(req.match_id, req.target)
    return {"ok": True}

# ── Startup ──────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)