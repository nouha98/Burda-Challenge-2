"""Durable workflow state: one folder per editorial run under runs/<run_id>/.

Files
  state.json          status + event history (who did what, when)
  selection.json      the editor's choice (proposal + recipe specification)
  recipe_<A|B>_v<N>.json   versioned recipe drafts
Other stages (review, nutrition, cards) add their own files.
"""
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
PROPOSALS = RUNS / "proposals.json"
TRENDS = RUNS / "trends.json"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_runs() -> list[str]:
    return sorted((p.name for p in RUNS.glob("run_*") if p.is_dir()), reverse=True)


def run_dir(run_id: str) -> Path:
    return RUNS / run_id


def state(run_id: str) -> dict:
    return read_json(run_dir(run_id) / "state.json", {"status": "unknown", "events": []})


def log_event(run_id: str, status: str, detail: str = "", **extra) -> None:
    st = state(run_id)
    st["status"] = status
    st["events"].append({"at": _now(), "status": status, "detail": detail, **extra})
    write_json(run_dir(run_id) / "state.json", st)


def create_run(proposal: dict, spec: dict, editor: str, proposals_generated_at: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", proposal["topic"].lower()).strip("-")[:24]
    run_id = f"run_{dt.datetime.now():%Y%m%d_%H%M%S}_{slug}"
    write_json(run_dir(run_id) / "selection.json", {
        "run_id": run_id,
        "selected_at": _now(),
        "editor": editor,
        "proposal_id": proposal["proposal_id"],
        "proposals_generated_at": proposals_generated_at,
        "proposal": proposal,
        "spec": spec,
    })
    log_event(run_id, "awaiting_recipes", f"Editor {editor} selected {proposal['proposal_id']} ({proposal['topic']})")
    return run_id


def selection(run_id: str) -> dict:
    return read_json(run_dir(run_id) / "selection.json")


def save_recipe(run_id: str, recipe: dict) -> Path:
    path = run_dir(run_id) / f"recipe_{recipe['slot']}_v{recipe['version']}.json"
    write_json(path, recipe)
    return path


def latest_recipes(run_id: str) -> dict:
    """slot -> latest version of that recipe."""
    out = {}
    for p in run_dir(run_id).glob("recipe_*_v*.json"):
        r = read_json(p)
        if r["slot"] not in out or r["version"] > out[r["slot"]]["version"]:
            out[r["slot"]] = r
    return dict(sorted(out.items()))


def recipe_history(run_id: str, slot: str) -> list[dict]:
    return sorted((read_json(p) for p in run_dir(run_id).glob(f"recipe_{slot}_v*.json")), key=lambda r: r["version"])
