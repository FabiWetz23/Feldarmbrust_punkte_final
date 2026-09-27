from fastapi import FastAPI, HTTPException, Response, Depends, Header, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles

import uvicorn
import json
import os
import secrets
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

# Security Configuration
API_KEY = os.environ.get("FELDARMBRUST_API_KEY", "1234")
ALLOW_INSECURE_HTTP = os.environ.get("FELDARMBRUST_ALLOW_INSECURE_HTTP", "").lower() in {"1", "true", "yes"}

def app_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

SPONSOR_DIR = app_data_dir() / "Sponsoren"
SPONSOR_DIR.mkdir(parents=True, exist_ok=True)
SPONSOR_EXTENSIONS = {".png", ".jpg", ".jpeg"}
STATE_FILE = app_data_dir() / "server_state.json"
CERT_DIR = app_data_dir() / "certs"

def sponsor_files() -> list[Path]:
    files = [
        path for path in SPONSOR_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SPONSOR_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())

def clean_sponsor_filename(filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix.lower()
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-") or "sponsor"
    return f"{safe_stem}{suffix}"

def is_local_request(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"}

async def verify_api_key(
    request: Request,
    x_api_key: str = Header(alias="X-API-KEY", default=None),
    key: str = None,
):
    if request.url.scheme != "https" and not ALLOW_INSECURE_HTTP and not is_local_request(request):
        raise HTTPException(
            status_code=426,
            detail="HTTPS required. Start the server with TLS certificates.",
        )

    # Check header first, then query param 'key'
    token = x_api_key or key
    if not token or not secrets.compare_digest(str(token), str(API_KEY)):
        print("Auth Failure: invalid API key")
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid API Key")
    return token

from .models import (
    Competition,
    Shooter,
    Series,
    Shot,
    ShooterCreate,
    SeriesCreate,
    ShotCreate,
)
from .excel_export import export_competition_to_excel


app = FastAPI(
    title="Field Crossbow Scoring System",
    description="Central server for wireless scoring in field crossbow competitions",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/sponsors", StaticFiles(directory=str(SPONSOR_DIR)), name="sponsors")

# Global competition state (In-Memory)
competition = Competition()
KO_SHOTS_PER_END = 3
KO_MAX_ENDS = 5
KO_TARGET_POINTS = 5
ko_state = {
    "active": False,
    "shots_per_end": KO_SHOTS_PER_END,
    "max_ends": KO_MAX_ENDS,
    "target_points": KO_TARGET_POINTS,
    "rounds": [],
}


def default_ko_state() -> dict:
    return {
        "active": False,
        "shots_per_end": KO_SHOTS_PER_END,
        "max_ends": KO_MAX_ENDS,
        "target_points": KO_TARGET_POINTS,
        "rounds": [],
    }


def save_runtime_state() -> None:
    data = {
        "competition": competition.model_dump(mode="json"),
        "ko": ko_state,
        "saved_at": datetime.now().isoformat(),
    }
    tmp_file = STATE_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(STATE_FILE)


def load_runtime_state() -> None:
    global competition
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        competition = Competition.model_validate(data.get("competition", {}))
        ko_state.clear()
        ko_state.update(default_ko_state())
        if isinstance(data.get("ko"), dict):
            ko_state.update(data["ko"])
        recalculate_ko_advancement()
        print(f"Loaded saved data from {STATE_FILE}")
    except Exception as exc:
        print(f"Could not load saved data from {STATE_FILE}: {exc}")


# ----------------------------
# Mock data (only once on startup)
# ----------------------------
def add_mock_data() -> None:
    """Add mock shooters and series for testing the new format"""

    competition.shooters.clear()
    competition.series.clear()

    # Shooters
    competition.shooters["S001"] = Shooter(id="S001", name="John Smith", country="USA", start_number="101")
    competition.shooters["S002"] = Shooter(id="S002", name="Maria Garcia", country="Spain", start_number="102")
    competition.shooters["S003"] = Shooter(id="S003", name="Hans Mueller", country="Germany", start_number="103")
    competition.shooters["S004"] = Shooter(id="S004", name="Yuki Tanaka", country="Japan", start_number="104")

    # Series helper
    def mk_series(sid: str, shooter_id: str, round_number: int, scores: list[float], inner_hits: list[int] = None):
        shots = []
        for i, score in enumerate(scores):
            is_inner = i in (inner_hits or [])
            shots.append(Shot(shot_number=i + 1, score=score, is_inner_circle=is_inner))
        return Series(
            id=sid,
            shooter_id=shooter_id,
            round_number=round_number,
            shots_per_series=6,
            shots=shots
        )


@app.on_event("startup")
def on_startup():
    # comment this out if you don't want mock data
    # add_mock_data()
    load_runtime_state()


# ----------------------------
# Helpers
# ----------------------------
def series_sum(s: Series) -> float:
    return float(sum((10.0 if shot.score == 11.0 else shot.score for shot in s.shots), 0.0))


def inner_tens_for_shooter(shooter_id: str) -> int:
    return sum(
        1
        for s in competition.series.values()
        if s.shooter_id == shooter_id
        for shot in s.shots
        if float(shot.score) == 11.0  # Score 11 = Inner Ten
    )


def total_for_shooter(shooter_id: str) -> float:
    return float(
        sum(
            (10.0 if shot.score == 11.0 else float(shot.score))
            for s in competition.series.values()
            if s.shooter_id == shooter_id
            for shot in s.shots
        )
    )


def shooter_sort_key(shooter: Shooter):
    start_number = str(getattr(shooter, "start_number", "") or "")
    try:
        return (0, int(start_number), start_number, shooter.name.lower())
    except ValueError:
        return (1, 0, start_number, shooter.name.lower())


def shooter_brief(shooter: Shooter) -> dict:
    return {
        "id": shooter.id,
        "name": shooter.name,
        "country": getattr(shooter, "country", None),
        "start_number": getattr(shooter, "start_number", None),
    }


def next_power_of_two(value: int) -> int:
    size = 1
    while size < value:
        size *= 2
    return max(2, size)


def ko_round_name(round_index: int, total_rounds: int) -> str:
    remaining = total_rounds - round_index
    if remaining == 1:
        return "Final"
    if remaining == 2:
        return "Semi Final"
    if remaining == 3:
        return "Quarter Final"
    return f"1/{2 ** (remaining - 1)} Final"


def ko_points(value) -> int:
    if value is None:
        return 0
    score = int(value)
    return 10 if score == 11 else score


def ko_shoot_off_rank(value) -> int:
    if value is None:
        return -1
    score = int(value)
    return 11 if score == 11 else score


def empty_ko_ends() -> list:
    return [[None] * KO_SHOTS_PER_END for _ in range(KO_MAX_ENDS)]


def reset_ko_slot(match: dict, slot: int) -> None:
    match["ends"][slot] = empty_ko_ends()
    match["shoot_off"][slot] = None


def ko_end_total(match: dict, slot: int, end_index: int) -> int:
    return sum(ko_points(score) for score in match["ends"][slot][end_index])


def ko_end_inner_tens(match: dict, slot: int, end_index: int) -> int:
    return sum(1 for score in match["ends"][slot][end_index] if score == 11)


def ko_end_complete(match: dict, slot: int, end_index: int) -> bool:
    return match["competitors"][slot] is not None and all(
        score is not None for score in match["ends"][slot][end_index]
    )


def update_ko_match_result(match: dict):
    left, right = match["competitors"]
    match["match_points"] = [0, 0]
    match["end_results"] = []
    match["needs_shoot_off"] = False
    match["winner_slot"] = None

    if left and not right:
        match["winner_slot"] = 0
        return 0
    if right and not left:
        match["winner_slot"] = 1
        return 1
    if not left or not right:
        return None

    for end_index in range(KO_MAX_ENDS):
        if not ko_end_complete(match, 0, end_index) or not ko_end_complete(match, 1, end_index):
            break

        totals = [ko_end_total(match, 0, end_index), ko_end_total(match, 1, end_index)]
        inner_tens = [ko_end_inner_tens(match, 0, end_index), ko_end_inner_tens(match, 1, end_index)]
        result = {
            "end_number": end_index + 1,
            "totals": totals,
            "inner_tens": inner_tens,
            "points": [0, 0],
            "winner_slot": None,
        }

        if totals[0] > totals[1] or (totals[0] == totals[1] and inner_tens[0] > inner_tens[1]):
            result["points"] = [1, 0]
            result["winner_slot"] = 0
        elif totals[1] > totals[0] or (totals[0] == totals[1] and inner_tens[1] > inner_tens[0]):
            result["points"] = [0, 1]
            result["winner_slot"] = 1
        else:
            result["points"] = [1, 1]

        match["match_points"][0] += result["points"][0]
        match["match_points"][1] += result["points"][1]
        match["end_results"].append(result)

    if len(match["end_results"]) == KO_MAX_ENDS and match["match_points"][0] != match["match_points"][1]:
        match["winner_slot"] = 0 if match["match_points"][0] > match["match_points"][1] else 1
        return match["winner_slot"]

    if len(match["end_results"]) == KO_MAX_ENDS and match["match_points"][0] == match["match_points"][1]:
        match["needs_shoot_off"] = True
        shoot_off = match.get("shoot_off", [None, None])
        if shoot_off[0] is not None and shoot_off[1] is not None:
            left_rank = ko_shoot_off_rank(shoot_off[0])
            right_rank = ko_shoot_off_rank(shoot_off[1])
            if left_rank > right_rank:
                match["winner_slot"] = 0
                return 0
            if right_rank > left_rank:
                match["winner_slot"] = 1
                return 1
            manual_winner = match.get("manual_winner_slot")
            if manual_winner in (0, 1):
                match["winner_slot"] = manual_winner
                return manual_winner

    return None


def ko_winner_slot(match: dict):
    return update_ko_match_result(match)


def find_ko_match(match_id: str):
    for round_data in ko_state.get("rounds", []):
        for match in round_data.get("matches", []):
            if match["id"] == match_id:
                return match
    return None


def recalculate_ko_advancement() -> None:
    rounds = ko_state.get("rounds", [])
    for round_index, round_data in enumerate(rounds):
        for match in round_data.get("matches", []):
            winner_slot = ko_winner_slot(match)
            match["winner_slot"] = winner_slot
            if not match.get("next_match_id"):
                continue

            next_match = find_ko_match(match["next_match_id"])
            next_slot = match.get("next_slot")
            if next_match is None or next_slot is None:
                continue

            winner = match["competitors"][winner_slot] if winner_slot is not None else None
            current = next_match["competitors"][next_slot]
            current_id = current.get("id") if current else None
            winner_id = winner.get("id") if winner else None
            if current_id != winner_id:
                next_match["competitors"][next_slot] = winner
                reset_ko_slot(next_match, next_slot)


def ko_slots_from_pairs(pairs) -> list:
    shooters = sorted(competition.shooters.values(), key=shooter_sort_key)
    if len(shooters) < 2:
        raise HTTPException(status_code=400, detail="At least 2 competitors are needed for KO")

    shooter_by_id = {shooter.id: shooter for shooter in shooters}
    used = set()
    slots = []

    if isinstance(pairs, list):
        for pair in pairs:
            if not isinstance(pair, list):
                continue
            for raw_id in (pair + [None, None])[:2]:
                shooter_id = str(raw_id) if raw_id else None
                if shooter_id and shooter_id in shooter_by_id and shooter_id not in used:
                    slots.append(shooter_brief(shooter_by_id[shooter_id]))
                    used.add(shooter_id)
                else:
                    slots.append(None)

    for shooter in shooters:
        if shooter.id not in used:
            slots.append(shooter_brief(shooter))
            used.add(shooter.id)

    return slots


def generate_ko_bracket_from_competitors(pairs=None) -> dict:
    slots = ko_slots_from_pairs(pairs)
    competitor_count = len([slot for slot in slots if slot])
    if competitor_count < 2:
        raise HTTPException(status_code=400, detail="At least 2 competitors are needed for KO")

    bracket_size = next_power_of_two(max(competitor_count, len(slots)))
    slots = slots[:bracket_size]
    slots.extend([None] * (bracket_size - len(slots)))

    total_rounds = 0
    size = bracket_size
    while size > 1:
        total_rounds += 1
        size //= 2

    rounds = []
    for round_index in range(total_rounds):
        match_count = bracket_size // (2 ** (round_index + 1))
        matches = []
        for match_index in range(match_count):
            is_final = round_index == total_rounds - 1
            competitors = [None, None]
            if round_index == 0:
                competitors = [slots[match_index * 2], slots[match_index * 2 + 1]]

            matches.append(
                {
                    "id": f"r{round_index + 1}m{match_index + 1}",
                    "round_index": round_index,
                    "match_number": match_index + 1,
                    "competitors": competitors,
                    "ends": [empty_ko_ends(), empty_ko_ends()],
                    "shoot_off": [None, None],
                    "manual_winner_slot": None,
                    "match_points": [0, 0],
                    "end_results": [],
                    "needs_shoot_off": False,
                    "winner_slot": None,
                    "next_match_id": None if is_final else f"r{round_index + 2}m{(match_index // 2) + 1}",
                    "next_slot": None if is_final else match_index % 2,
                }
            )
        rounds.append(
            {
                "index": round_index,
                "name": ko_round_name(round_index, total_rounds),
                "matches": matches,
            }
        )

    ko_state.clear()
    ko_state.update(
        {
            "active": True,
            "shots_per_end": KO_SHOTS_PER_END,
            "max_ends": KO_MAX_ENDS,
            "target_points": KO_TARGET_POINTS,
            "started_at": datetime.now().isoformat(),
            "rounds": rounds,
        }
    )
    recalculate_ko_advancement()
    return ko_state


# ----------------------------
# API
# ----------------------------
@app.get("/state")
async def get_state(api_key: str = Depends(verify_api_key)):
    # totals
    total_shots = sum(len(s.shots) for s in competition.series.values())
    total_scores = [float(shot.score) for s in competition.series.values() for shot in s.shots]
    average_score = (sum(total_scores) / len(total_scores)) if total_scores else 0.0

    # leaderboard rows + tiebreak by inner tens
    rows = []
    for sh in competition.shooters.values():
        total = total_for_shooter(sh.id)
        series_count = sum(1 for s in competition.series.values() if s.shooter_id == sh.id)
        inner_tens = inner_tens_for_shooter(sh.id)
        average_score = (total / series_count) if series_count else 0.0

        rows.append(
            {
                "shooter": {
                    "id": sh.id, 
                    "name": sh.name, 
                    "country": getattr(sh, "country", None),
                    "start_number": getattr(sh, "start_number", None)
                },
                "total_score": total,
                "series_count": series_count,
                "average_score": average_score,
                "inner_tens": inner_tens,
            }
        )

    # Sort: total desc, then inner tens desc, then name asc
    rows.sort(key=lambda x: (-x["total_score"], -x["inner_tens"], x["shooter"]["name"]))

    statistics = {
        "total_shooters": len(competition.shooters),
        "total_series": len(competition.series),
        "total_shots": total_shots,
        "average_score": average_score,
        "last_update": datetime.now().isoformat(),
    }

    return jsonable_encoder(
        {
            "competition": competition,  # includes shooters + series dict
            "leaderboard": rows,
            "statistics": statistics,
            "ko": ko_state,
        }
    )


@app.post("/clear")
async def clear_data(api_key: str = Depends(verify_api_key)):
    competition.shooters.clear()
    competition.series.clear()
    ko_state.clear()
    ko_state.update(default_ko_state())
    save_runtime_state()
    return {"message": "All data cleared"}


@app.post("/shooters")
async def upsert_shooter(data: ShooterCreate, api_key: str = Depends(verify_api_key)):
    # country optional
    shooter = Shooter(
        id=data.id, 
        name=data.name, 
        country=getattr(data, "country", None),
        start_number=getattr(data, "start_number", None)
    )
    competition.shooters[data.id] = shooter
    save_runtime_state()
    return {"message": "Shooter upserted", "shooter_id": data.id}


@app.post("/series")
async def create_or_update_series(series_data: SeriesCreate, api_key: str = Depends(verify_api_key)):
    # shooter must exist
    if series_data.shooter_id not in competition.shooters:
        raise HTTPException(status_code=404, detail="Shooter not found")

    if series_data.id in competition.series:
        competition.series[series_data.id].round_number = series_data.round_number
        competition.series[series_data.id].shots_per_series = series_data.shots_per_series
        save_runtime_state()
        return {"message": "Series updated", "series_id": series_data.id}

    competition.series[series_data.id] = Series(
        id=series_data.id,
        shooter_id=series_data.shooter_id,
        round_number=series_data.round_number,
        shots_per_series=series_data.shots_per_series,
        shots=[],
    )
    save_runtime_state()
    return {"message": "Series created", "series_id": series_data.id}


@app.post("/series/{series_id}/shot")
async def add_or_update_shot(series_id: str, shot_data: ShotCreate, api_key: str = Depends(verify_api_key)):
    """Fügt einen Schuss hinzu oder aktualisiert einen bestehenden"""
    if series_id not in competition.series:
        raise HTTPException(status_code=404, detail="Series not found")
    
    series = competition.series[series_id]
    
    # Prüfen ob Schussnummer gültig ist
    if shot_data.shot_number < 1 or shot_data.shot_number > series.shots_per_series:
        raise HTTPException(
            status_code=400, 
            detail=f"shot_number must be between 1 and {series.shots_per_series}"
        )
    
    # Prüfen ob Schuss bereits existiert
    existing_shot_index = None
    for i, shot in enumerate(series.shots):
        if shot.shot_number == shot_data.shot_number:
            existing_shot_index = i
            break
    
    # Determine if this is an inner ten (score 11)
    is_inner_ten = shot_data.score == 11.0
    
    new_shot = Shot(
        shot_number=shot_data.shot_number,
        score=shot_data.score,
        timestamp=datetime.now()
    )
    
    if existing_shot_index is not None:
        # Aktualisieren
        series.shots[existing_shot_index] = new_shot
        action = "aktualisiert"
    else:
        # Hinzufügen
        series.shots.append(new_shot)
        # Sortieren nach Schussnummer
        series.shots.sort(key=lambda x: x.shot_number)
        action = "hinzugefügt"
    
    save_runtime_state()
    return {
        "message": f"Schuss {shot_data.shot_number} {action}",
        "series_id": series_id,
        "shot": jsonable_encoder(new_shot),
        "series_sum": series_sum(series)
    }


@app.delete("/series/{series_id}/shot/{shot_number}")
async def delete_shot(series_id: str, shot_number: int, api_key: str = Depends(verify_api_key)):
    if series_id not in competition.series:
        raise HTTPException(status_code=404, detail="Series not found")

    series = competition.series[series_id]
    before = len(series.shots)
    series.shots = [s for s in series.shots if s.shot_number != shot_number]
    after = len(series.shots)

    if before == after:
        raise HTTPException(status_code=404, detail="Shot not found")

    save_runtime_state()
    return {"message": "Shot deleted", "series_id": series_id, "series_sum": series_sum(series)}


@app.delete("/series/{series_id}")
async def delete_series(series_id: str, api_key: str = Depends(verify_api_key)):
    if series_id not in competition.series:
        raise HTTPException(status_code=404, detail="Series not found")
    del competition.series[series_id]
    save_runtime_state()
    return {"message": f"Series {series_id} deleted"}


@app.delete("/shooters/{shooter_id}")
async def delete_shooter(shooter_id: str, api_key: str = Depends(verify_api_key)):
    if shooter_id not in competition.shooters:
        raise HTTPException(status_code=404, detail="Shooter not found")

    series_to_delete = [sid for sid, s in competition.series.items() if s.shooter_id == shooter_id]
    for sid in series_to_delete:
        del competition.series[sid]

    del competition.shooters[shooter_id]
    save_runtime_state()
    return {"message": f"Shooter {shooter_id} deleted", "deleted_series": len(series_to_delete)}


@app.get("/ko/state")
async def get_ko_state(api_key: str = Depends(verify_api_key)):
    return jsonable_encoder(ko_state)


@app.post("/ko/start")
async def start_ko(data: dict = None, api_key: str = Depends(verify_api_key)):
    pairs = (data or {}).get("pairs")
    result = generate_ko_bracket_from_competitors(pairs)
    save_runtime_state()
    return jsonable_encoder(result)


@app.post("/ko/reset")
async def reset_ko(api_key: str = Depends(verify_api_key)):
    ko_state.clear()
    ko_state.update(default_ko_state())
    save_runtime_state()
    return jsonable_encoder(ko_state)


@app.post("/ko/matches/{match_id}/shot")
async def set_ko_shot(match_id: str, data: dict, api_key: str = Depends(verify_api_key)):
    if not ko_state.get("active"):
        raise HTTPException(status_code=400, detail="KO mode is not active")

    match = find_ko_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="KO match not found")

    shoot_off = bool(data.get("shoot_off", False))
    slot = int(data.get("slot", -1))
    end_number = 0 if shoot_off else int(data.get("end_number", 0))
    shot_number = 1 if shoot_off else int(data.get("shot_number", 0))
    if slot not in (0, 1):
        raise HTTPException(status_code=400, detail="slot must be 0 or 1")
    if not shoot_off and (end_number < 1 or end_number > KO_MAX_ENDS):
        raise HTTPException(status_code=400, detail=f"end_number must be between 1 and {KO_MAX_ENDS}")
    if not shoot_off and (shot_number < 1 or shot_number > KO_SHOTS_PER_END):
        raise HTTPException(status_code=400, detail=f"shot_number must be between 1 and {KO_SHOTS_PER_END}")
    if match["competitors"][slot] is None:
        raise HTTPException(status_code=400, detail="This KO slot has no competitor")

    raw_score = data.get("score")
    score = None
    if raw_score is not None:
        score = int(raw_score)
        if score < 0 or (score > 10 and score != 11):
            raise HTTPException(status_code=400, detail="score must be 0-10 or 11 for inner ten")

    if shoot_off:
        match["shoot_off"][slot] = score
    else:
        match["ends"][slot][end_number - 1][shot_number - 1] = score
    match["manual_winner_slot"] = None
    recalculate_ko_advancement()
    save_runtime_state()
    return jsonable_encoder(ko_state)


@app.post("/ko/matches/{match_id}/winner")
async def set_ko_manual_winner(match_id: str, data: dict, api_key: str = Depends(verify_api_key)):
    if not ko_state.get("active"):
        raise HTTPException(status_code=400, detail="KO mode is not active")

    match = find_ko_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="KO match not found")

    slot = data.get("slot")
    if slot is None:
        match["manual_winner_slot"] = None
    else:
        slot = int(slot)
        if slot not in (0, 1):
            raise HTTPException(status_code=400, detail="slot must be 0 or 1")
        if match["competitors"][slot] is None:
            raise HTTPException(status_code=400, detail="This KO slot has no competitor")
        match["manual_winner_slot"] = slot

    recalculate_ko_advancement()
    save_runtime_state()
    return jsonable_encoder(ko_state)

@app.get("/api/sponsors")
async def list_sponsors(api_key: str = Depends(verify_api_key)):
    return {
        "sponsors": [
            {"name": path.name, "url": f"/sponsors/{path.name}"}
            for path in sponsor_files()
        ],
        "folder": str(SPONSOR_DIR),
    }


@app.post("/api/sponsors")
async def upload_sponsor(file: UploadFile = File(...), api_key: str = Depends(verify_api_key)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SPONSOR_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PNG/JPG sponsor images are allowed")

    target = SPONSOR_DIR / clean_sponsor_filename(file.filename or "sponsor.png")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Sponsor image is too large")
    target.write_bytes(content)
    return {"message": "Sponsor uploaded", "name": target.name, "url": f"/sponsors/{target.name}"}


@app.delete("/api/sponsors/{name}")
async def delete_sponsor(name: str, api_key: str = Depends(verify_api_key)):
    target = SPONSOR_DIR / clean_sponsor_filename(name)
    if target.parent != SPONSOR_DIR or not target.exists():
        raise HTTPException(status_code=404, detail="Sponsor not found")
    target.unlink()
    return {"message": "Sponsor deleted", "name": target.name}


@app.get("/export")
async def export_excel(api_key: str = Depends(verify_api_key)):
    if not competition.shooters:
        raise HTTPException(status_code=400, detail="No data to export")

    try:
        excel_buffer = export_competition_to_excel(competition, sponsor_files(), ko_state)
        filename = f"feldarmbrust_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return Response(
            content=excel_buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel export failed: {str(e)}")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "version": "1.0.0"}


@app.get("/ca.cer")
async def download_ca_cer():
    ca_path = CERT_DIR / "ca.cer"
    if not ca_path.exists():
        ca_path = CERT_DIR / "ca.crt"
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate not found")
    return FileResponse(
        ca_path,
        media_type="application/x-x509-ca-cert",
        filename="feldarmbrust_ca.cer",
    )


@app.get("/ca.crt")
async def download_ca_crt():
    ca_path = CERT_DIR / "ca.crt"
    if not ca_path.exists():
        ca_path = CERT_DIR / "ca.cer"
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="CA certificate not found")
    return FileResponse(
        ca_path,
        media_type="application/x-x509-ca-cert",
        filename="feldarmbrust_ca.crt",
    )


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    base_url = str(request.base_url).rstrip("/")
    host = request.url.hostname or "SERVER-IP"
    return f"""
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Feldarmbrust Tablet Setup</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f4f7fb; color: #172033; }}
    main {{ max-width: 860px; margin: 0 auto; padding: 28px 18px 46px; }}
    h1 {{ margin: 0 0 12px; color: #274b7a; }}
    h2 {{ margin: 24px 0 8px; color: #274b7a; }}
    .panel {{ background: #fff; border: 1px solid #d8e1ee; border-radius: 8px; padding: 18px; margin: 14px 0; }}
    .url {{ display: block; padding: 12px; background: #edf3fb; border-radius: 6px; overflow-wrap: anywhere; font-weight: 700; }}
    .btn {{ display: inline-block; margin: 8px 8px 8px 0; padding: 12px 15px; border-radius: 6px; background: #2f6097; color: #fff; text-decoration: none; font-weight: 700; }}
    ol {{ padding-left: 22px; }}
    li {{ margin: 9px 0; }}
    .small {{ color: #52627a; font-size: 14px; }}
  </style>
</head>
<body>
  <main>
    <h1>Feldarmbrust Tablet Setup</h1>
    <p>Diese Seite am Tablet offen lassen und die Schritte der Reihe nach ausfuehren.</p>

    <section class="panel">
      <h2>1. Zertifikat installieren</h2>
      <p>Das Tablet muss dem lokalen Feldarmbrust-Server einmal vertrauen.</p>
      <a class="btn" href="{base_url}/ca.cer">Tablet-Zertifikat herunterladen</a>
      <a class="btn" href="{base_url}/ca.crt">Alternative .crt herunterladen</a>
      <ol>
        <li>Datei <strong>feldarmbrust_ca.cer</strong> herunterladen.</li>
        <li>Android-Einstellungen oeffnen.</li>
        <li><strong>Sicherheit</strong> oder <strong>Passwoerter & Sicherheit</strong> oeffnen.</li>
        <li><strong>Verschluesselung & Anmeldedaten</strong> waehlen.</li>
        <li><strong>Zertifikat installieren</strong> und dann <strong>CA-Zertifikat</strong> waehlen.</li>
        <li>Die heruntergeladene Datei auswaehlen und als <strong>Feldarmbrust</strong> benennen.</li>
      </ol>
      <p class="small">Android kann je nach Hersteller leicht andere Menunamen anzeigen.</p>
    </section>

    <section class="panel">
      <h2>2. App verbinden</h2>
      <p>In der Tablet-App diese Server-URL eintragen:</p>
      <code class="url">{base_url}</code>
      <p class="small">Falls diese Seite ueber localhost geoeffnet wurde, am Tablet stattdessen die WLAN-IP des Laptops verwenden, z.B. <strong>https://{host}:8000</strong>.</p>
    </section>

    <section class="panel">
      <h2>3. Passwort</h2>
      <p>Als API Key/Passwort in der App das Passwort eintragen, das beim Start der Server-EXE angezeigt wird.</p>
    </section>
  </main>
</body>
</html>
"""


@app.post("/shutdown")
async def shutdown_server(api_key: str = Depends(verify_api_key)):
    save_runtime_state()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"message": "Server is shutting down"}


@app.post("/reset-storage")
async def reset_storage(api_key: str = Depends(verify_api_key)):
    competition.shooters.clear()
    competition.series.clear()
    ko_state.clear()
    ko_state.update(default_ko_state())
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    return {"message": "Saved JSON and current data reset"}


# ----------------------------
# Web UI (English, shots per End, X for inner circle)
# ----------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Field Crossbow Scoring System</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; color:#1f2937; }
    body.dark { background:#0b1220; color:#e5e7eb; }
    .container { max-width: 1400px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 10px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
    body.dark .container { background:#0f1a30; box-shadow: 0 2px 12px rgba(0,0,0,0.28); }
    h1 { color: #366092; text-align: center; margin: 8px 0 18px; }
    body.dark h1, body.dark .koRound h3, body.dark .koTotal { color:#93c5fd; }
    .topbar { display:flex; justify-content: flex-end; align-items:center; gap:10px; margin-bottom: 8px; flex-wrap:wrap; }
    .btn { background:#366092; color:#fff; padding:10px 14px; border:none; border-radius:6px; cursor:pointer; text-decoration:none; }
    .btn:hover { background:#2a4d7a; }
    .dangerBtn { background:#b91c1c; }
    .dangerBtn:hover { background:#991b1b; }
    .stats { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 10px 0 18px; }
    .stat { background:#366092; color:#fff; padding:14px; border-radius:10px; }
    .stat .n { font-size: 1.8em; font-weight: 800; }
    .stat .l { opacity: .9; }
    table { width:100%; border-collapse: collapse; margin-top: 10px; }
    th, td { padding: 10px; border-bottom: 1px solid #e6e6e6; vertical-align: top; }
    th { background:#366092; color:#fff; text-align:left; position: sticky; top: 0; }
    tr:hover td { background:#fafafa; }
    body.dark th { background:#1d4ed8; }
    body.dark td { border-bottom-color:rgba(255,255,255,.10); }
    body.dark tr:hover td { background:#111f38; }
    .score { font-weight: 800; color:#366092; }
    .endCell { line-height: 1.35; }
    .shotsLine { font-weight: 700; }
    .endTotal { opacity: .75; font-size: 12px; margin-top: 4px; }
    .muted { opacity: .7; }
    .pill { display:inline-block; padding: 2px 8px; border-radius: 999px; background:#eef3fb; color:#2a4d7a; font-weight:700; }
    .sponsorBar { display:flex; flex-wrap:wrap; gap:14px; align-items:center; justify-content:center; margin: 8px 0 18px; padding: 10px; border: 1px dashed #ccd6e2; border-radius: 10px; background:#fbfdff; }
    .sponsorBar img { max-height: 70px; max-width: 180px; object-fit: contain; }
    .sponsorHeader { display:flex; align-items:center; justify-content:space-between; gap:10px; margin: 8px 0 6px; }
    .sponsorHeader::before { content:""; width:42px; height:42px; }
    .gearBtn { width: 42px; height: 42px; border-radius: 999px; border: 1px solid #ccd6e2; background:#fff; color:#366092; font-size:22px; font-weight:800; cursor:pointer; }
    .gearBtn:hover { background:#eef3fb; }
    .sponsorTools { display:none; flex-wrap:wrap; gap:10px; align-items:center; justify-content:center; margin-bottom: 14px; padding: 10px; border-radius: 10px; background:#f8fbff; }
    .sponsorTools.open { display:flex; }
    .fileInput { padding: 9px; border: 1px solid #ccd6e2; border-radius: 6px; background:#fff; }
    body.dark .sponsorBar, body.dark .sponsorTools, body.dark .fileInput, body.dark .koMatch { background:#111f38; border-color:rgba(255,255,255,.14); color:#e5e7eb; }
    body.dark .gearBtn { background:#111f38; border-color:rgba(255,255,255,.14); color:#93c5fd; }
    body.dark .pill { background:#1e293b; color:#bfdbfe; }
    .themeSwitch { display:inline-flex; align-items:center; gap:8px; min-height:38px; cursor:pointer; user-select:none; }
    .themeSwitch input { position:absolute; opacity:0; pointer-events:none; }
    .switchTrack { width:54px; height:30px; padding:3px; border-radius:999px; border:1px solid #ccd6e2; background:#e5e7eb; }
    .switchThumb { display:block; width:22px; height:22px; border-radius:999px; background:#366092; transition:transform .18s ease, background .18s ease; }
    .themeSwitch input:checked + .switchTrack { background:#14532d; border-color:#22c55e; }
    .themeSwitch input:checked + .switchTrack .switchThumb { transform:translateX(24px); background:#22c55e; }
    .koBoard { display:flex; gap:14px; align-items:stretch; overflow-x:auto; padding-bottom:10px; margin-top: 12px; }
    .koRound { min-width:280px; display:flex; flex-direction:column; gap:12px; }
    .koRound h3 { margin:0; color:#366092; }
    .koMatch { border:1px solid #d7e0eb; border-radius:10px; padding:10px; background:#fbfdff; }
    .koMatchTitle { font-weight:800; margin-bottom:8px; color:#2a4d7a; }
    .koCompetitor { display:grid; grid-template-columns: 1fr auto auto; gap:8px; align-items:center; padding:7px; border-radius:7px; border:1px solid #edf2f7; margin-top:6px; }
    .koWinner { background:#e8f7ee; border-color:#9fddb6; }
    .koShots { display:flex; gap:3px; }
    .koCell { min-width:24px; min-height:24px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #cfd9e6; background:#fff; font-weight:700; }
    .koTotal { min-width:32px; text-align:right; font-weight:900; color:#366092; }
    .koWinnerBanner { margin:16px 0; padding:14px; border-radius:10px; background:#e8f7ee; border:1px solid #9fddb6; font-weight:900; color:#174d2a; }
    .koEndList { display:grid; gap:4px; font-size:12px; color:#4b5563; margin-top:8px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🏹 Field Crossbow Scoring System</h1>

    <div class="topbar">
      <label class="themeSwitch">
        <input id="darkModeToggle" type="checkbox" onchange="setDarkMode(this.checked)" />
        <span class="switchTrack" aria-hidden="true"><span class="switchThumb"></span></span>
        <span>Darkmode</span>
      </label>
      <button class="btn" onclick="location.reload()">🔄 Refresh</button>
      <button class="btn" onclick="exportExcel()">📊 Excel Export</button>
      <button class="btn dangerBtn" onclick="resetStorage()">Reset JSON</button>
      <button class="btn dangerBtn" onclick="shutdownServer()">Stop Server</button>
    </div>

    <div id="content">Loading…</div>
  </div>

<script>
function getApiKey() {
  let key = sessionStorage.getItem("apiKey") || "";
  if (!key) {
    key = prompt("Server password / API key:") || "";
    if (key) sessionStorage.setItem("apiKey", key);
  }
  return key;
}

function askFreshApiKey(message) {
  return prompt(message || "Server password / API key:") || "";
}

function setDarkMode(enabled) {
  document.body.classList.toggle("dark", enabled);
  localStorage.setItem("webDarkMode", enabled ? "1" : "0");
  const toggle = document.getElementById("darkModeToggle");
  if (toggle) toggle.checked = enabled;
}

async function shutdownServer() {
  if (!confirm("Stop the server now?")) return;
  const key = askFreshApiKey("Password required to stop the server:");
  if (!key) return;
  await fetch("/shutdown", {
    method: "POST",
    headers: { "X-API-KEY": key }
  });
  document.body.innerHTML = "<div style='font-family:Arial;padding:30px'><h2>Server stopped.</h2><p>You can close this tab.</p></div>";
}

async function resetStorage() {
  if (!confirm("Reset saved JSON and clear current data? This cannot be undone.")) return;
  const key = askFreshApiKey("Password required to reset saved JSON:");
  if (!key) return;
  const res = await fetch("/reset-storage", {
    method: "POST",
    headers: { "X-API-KEY": key }
  });
  if (!res.ok) {
    alert("Reset failed. Wrong password?");
    return;
  }
  sessionStorage.setItem("apiKey", key);
  await render();
  alert("Saved JSON and current data were reset.");
}

async function exportExcel() {
  const key = getApiKey();
  if (!key) return;
  window.open(`/export?key=${encodeURIComponent(key)}`, "_blank", "noopener");
}

function setupSponsorUi() {
  const content = document.getElementById("content");
  const sponsorHeader = document.createElement("div");
  sponsorHeader.className = "sponsorHeader";
  sponsorHeader.innerHTML = `
    <strong>Sponsors</strong>
    <button class="gearBtn" onclick="toggleSponsorTools()" title="Manage sponsors" aria-label="Manage sponsors">⚙</button>
  `;

  const sponsorBar = document.createElement("div");
  sponsorBar.id = "sponsorBar";
  sponsorBar.className = "sponsorBar";

  const tools = document.createElement("div");
  tools.className = "sponsorTools";
  tools.innerHTML = `
    <input id="sponsorFile" class="fileInput" type="file" accept="image/png,image/jpeg" />
    <button class="btn" onclick="uploadSponsor()">Upload sponsor</button>
    <button class="btn" onclick="loadSponsors()">Refresh sponsors</button>
  `;

  content.before(sponsorHeader);
  content.before(sponsorBar);
  content.before(tools);
}

function toggleSponsorTools() {
  document.querySelector(".sponsorTools")?.classList.toggle("open");
}

function cleanNum(v) {
  const n = Number(v);
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1);
}

function fmtShot(v) {
  // inner circle shown as X (still counts 10 points)
  if (Number(v) === 11) return "X";
  return cleanNum(v);
}

function points(v) {
  const n = Number(v);
  return (n === 11) ? 10 : n;   // <-- IMPORTANT: 11 counts as 10 points
}

function sumShots(shots) {
  return (shots || []).reduce((a, s) => a + points(s.score || 0), 0);
}

function koShotText(v) {
  if (v === null || v === undefined) return "";
  if (Number(v) === 11) return "X";
  return String(v);
}

function koSlotTotal(shots) {
  return (shots || []).reduce((sum, value) => sum + points(value ?? 0), 0);
}

function koEndTotal(match, slot, endIndex) {
  return koSlotTotal(match.ends?.[slot]?.[endIndex] || []);
}

function koEndShots(match, slot, endIndex) {
  return (match.ends?.[slot]?.[endIndex] || []).map(koShotText).join(" ");
}

function finalKoWinner(ko) {
  const rounds = ko.rounds || [];
  const finalRound = rounds[rounds.length - 1];
  const finalMatch = finalRound?.matches?.[0];
  if (!finalMatch || finalMatch.winner_slot === null || finalMatch.winner_slot === undefined) return null;
  return finalMatch.competitors?.[finalMatch.winner_slot] || null;
}

function renderKo(ko) {
  let html = "<h2>KO System</h2>";
  const overallWinner = finalKoWinner(ko);
  if (overallWinner) {
    html += `<div class="koWinnerBanner">Overall KO Winner: ${overallWinner.start_number || "-"} ${overallWinner.name}</div>`;
  }
  html += "<div class='koBoard'>";
  (ko.rounds || []).forEach(round => {
    html += `<div class="koRound"><h3>${round.name}</h3>`;
    (round.matches || []).forEach(match => {
      html += `<div class="koMatch"><div class="koMatchTitle">Match ${match.match_number} (${match.match_points?.[0] || 0}:${match.match_points?.[1] || 0})</div>`;
      [0, 1].forEach(slot => {
        const competitor = match.competitors?.[slot];
        const isWinner = match.winner_slot === slot;
        const name = competitor ? `${competitor.start_number || "-"} ${competitor.name}` : "Free";
        html += `<div class="koCompetitor ${isWinner ? "koWinner" : ""}">
          <strong>${name}</strong>
          <div class="koShots">${(match.ends?.[slot]?.flat() || []).map(v => `<span class="koCell">${koShotText(v)}</span>`).join("")}</div>
          <div class="koTotal">${match.match_points?.[slot] || 0}</div>
        </div>`;
      });
      html += "<div class='koEndList'>";
      for (let endIndex = 0; endIndex < (ko.max_ends || 5); endIndex++) {
        const left = koEndShots(match, 0, endIndex);
        const right = koEndShots(match, 1, endIndex);
        if (left || right) {
          html += `<div>End ${endIndex + 1}: ${left || "-"} (${koEndTotal(match, 0, endIndex)}) / ${right || "-"} (${koEndTotal(match, 1, endIndex)})</div>`;
        }
      }
      if (match.needs_shoot_off || match.shoot_off?.some(v => v !== null && v !== undefined)) {
        html += `<div>Shoot-off: ${koShotText(match.shoot_off?.[0]) || "-"} / ${koShotText(match.shoot_off?.[1]) || "-"}</div>`;
      }
      html += "</div>";
      html += "</div>";
    });
    html += "</div>";
  });
  html += "</div>";
  return html;
}

async function loadState() {
  const key = getApiKey();
  if (!key) return null;
  const res = await fetch("/state", {
    headers: { "X-API-KEY": key }
  });
  if (res.status === 401) sessionStorage.removeItem("apiKey");
  if (!res.ok) return null;
  return await res.json();
}

async function loadSponsors() {
  const key = getApiKey();
  if (!key) return;
  const res = await fetch("/api/sponsors", {
    headers: { "X-API-KEY": key }
  });
  if (!res.ok) return;
  const data = await res.json();
  const sponsors = data.sponsors || [];
  const bar = document.getElementById("sponsorBar");
  if (!sponsors.length) {
    bar.innerHTML = "<span class='muted'>No sponsor logos uploaded.</span>";
    return;
  }
  bar.innerHTML = sponsors.map(s => `<img src="${s.url}" alt="${s.name}" title="${s.name}" />`).join("");
}

async function uploadSponsor() {
  const input = document.getElementById("sponsorFile");
  if (!input.files || !input.files.length) {
    alert("Please select a PNG/JPG first.");
    return;
  }
  const form = new FormData();
  form.append("file", input.files[0]);
  const key = getApiKey();
  if (!key) return;
  const res = await fetch("/api/sponsors", {
    method: "POST",
    headers: { "X-API-KEY": key },
    body: form
  });
  if (!res.ok) {
    alert("Sponsor upload failed.");
    return;
  }
  input.value = "";
  await loadSponsors();
}

async function render() {
  const data = await loadState();
  if (!data) {
    document.getElementById("content").innerHTML = "<div class='muted'>Server offline.</div>";
    return;
  }

  const lb = data.leaderboard || [];
  const stats = data.statistics || {};
  const seriesDict = (data.competition && data.competition.series) ? data.competition.series : {};

  // compute max ends (rounds)
  let maxRounds = 0;
  for (const sid in seriesDict) {
    const s = seriesDict[sid];
    maxRounds = Math.max(maxRounds, Number(s.round_number || 0));
  }

  let html = "";

    // stats
    html += "<div class='stats'>";
    html += `<div class='stat'><div class='n'>${stats.total_shooters ?? 0}</div><div class='l'>Competitors</div></div>`;
    html += `<div class='stat'><div class='n'>${stats.total_series ?? 0}</div><div class='l'>Ends</div></div>`;
    html += `<div class='stat'><div class='n'>${stats.total_shots ?? 0}</div><div class='l'>Shots</div></div>`;
    html += "</div>";

  html += "<h2>🏆 Ranking</h2>";
  html += "<div class='muted'>Tie-break: total points, then more inner tens (X).</div>";

  // table header
  html += "<table>";
  html += "<tr>";
  html += "<th>Rank</th><th>No</th><th>Competitor</th><th>Country</th>";
  for (let r = 1; r <= maxRounds; r++) html += `<th>End ${r}</th>`;
  html += "<th>Total</th><th>Inner Tens (X)</th>";
  html += "</tr>";

  // rows
  lb.forEach((row, idx) => {
    const shooterId = row?.shooter?.id;
    const shooterNo = row?.shooter?.start_number || "-";
    const shooterName = row?.shooter?.name || "";
    const shooterCountry = row?.shooter?.country || "";

    // gather series for shooter, indexed by round_number
    const ends = {};
    for (const sid in seriesDict) {
      const s = seriesDict[sid];
      if (s && s.shooter_id === shooterId) {
        const rn = Number(s.round_number || 0);
        ends[rn] = s;
      }
    }

    let running = 0;
    let lastEndTotal = 0;

    html += "<tr>";
    html += `<td><span class="pill">${idx + 1}</span></td>`;
    html += `<td>${shooterNo}</td>`;
    html += `<td><strong>${shooterName}</strong></td>`;
    html += `<td>${shooterCountry}</td>`;

    // Display individual shots for each end
    for (let r = 1; r <= maxRounds; r++) {
      const s = ends[r];
      if (!s) {
        html += "<td class='endCell muted'>-</td>";
        continue;
      }

      const shots = (s.shots || []).slice().sort((a,b) => Number(a.shot_number||0) - Number(b.shot_number||0));
      const shotsLine = shots.map(sh => fmtShot(sh.score)).join(" ");
      const endTotal = sumShots(shots);
      lastEndTotal = endTotal;
      running += endTotal;

      html += `<td class="endCell">
        <div class="shotsLine">${shotsLine || "-"}</div>
        <div class="endTotal">(End ${r}: ${cleanNum(endTotal)})</div>
      </td>`;
    }

    const finalTotal = Number(row.total_score || 0);
    const innerTens = Number(row.inner_tens || 0);

    html += `<td><strong>${cleanNum(running)}</strong></td>`;
    html += `<td><strong>${innerTens}</strong></td>`;
    html += "</tr>";
  });

  html += "</table>";

  if (data.ko && data.ko.active) {
    html += renderKo(data.ko);
  }

  document.getElementById("content").innerHTML = html;
}

setupSponsorUi();
setDarkMode(localStorage.getItem("webDarkMode") === "1");
loadSponsors();
render();

// Auto-refresh every 2 seconds
setInterval(render, 2000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    certfile = os.environ.get("FELDARMBRUST_TLS_CERTFILE")
    keyfile = os.environ.get("FELDARMBRUST_TLS_KEYFILE")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
