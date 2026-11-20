"""Frozen demo snapshots: trends, proposals, complete editorial runs and Archiv-Revival results, committed to the repo.

The live sources (Wikimedia, Brave, gateway) change or can fail; a snapshot lets the demo run from
fixed, reproducible data. Restoring never deletes anything: the current runs/ files are backed up first.

  python -m storage.snapshot save <name> [run_id ...]   (default: all runs + all revival results)
  python -m storage.snapshot restore <name>
  python -m storage.snapshot list
"""
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

from storage import runs

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "snapshots"
TOP_FILES = ["trends.json", "proposals.json"]


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def list_snapshots() -> list[dict]:
    out = []
    for d in sorted(SNAP_DIR.glob("*/manifest.json"), reverse=True):
        out.append(json.loads(d.read_text(encoding="utf-8")))
    return out


def _revivals() -> list[str]:
    return sorted(p.name for p in runs.RUNS.glob("revival_*") if p.is_dir())


def save(name: str, run_ids: list[str] | None = None) -> Path:
    revival_ids = [r for r in (run_ids or []) if r.startswith("revival_")] or (_revivals() if not run_ids else [])
    run_ids = [r for r in (run_ids or []) if r.startswith("run_")] or (runs.list_runs() if not run_ids else [])
    target = SNAP_DIR / name
    if target.exists():
        raise FileExistsError(f"Snapshot {name} exists already; choose a new name")
    target.mkdir(parents=True)
    for f in TOP_FILES:
        if (runs.RUNS / f).exists():
            shutil.copy2(runs.RUNS / f, target / f)
    run_info = []
    for rid in run_ids:
        shutil.copytree(runs.run_dir(rid), target / rid)
        sel, st = runs.selection(rid), runs.state(rid)
        recipes = runs.latest_recipes(rid)
        run_info.append({"run_id": rid, "proposal": f"{sel['proposal_id']} {sel['proposal'].get('title_de')}",
                         "editor": sel["editor"], "status": st["status"],
                         "recipes": {s: f"v{r['version']} {r.get('title')} ({r.get('status')})" for s, r in recipes.items()}})
    revival_info = []
    for rid in revival_ids:
        shutil.copytree(runs.RUNS / rid, target / rid)
        data = runs.read_json(runs.RUNS / rid / "revival.json") or {}
        revival_info.append({"revival_id": rid, "seed": data.get("seed"),
                             "items": [i["title"] for i in data.get("items", [])],
                             "images": sum(1 for i in data.get("items", []) if i.get("image"))})
    trends = runs.read_json(runs.TRENDS) or {}
    proposals = runs.read_json(runs.PROPOSALS) or {}
    manifest = {
        "name": name, "created_at": dt.datetime.now().isoformat(timespec="seconds"), "code_commit": _git_commit(),
        "trends_generated_at": trends.get("generated_at"), "wikimedia_window": trends.get("sources", {}).get("wikimedia", {}).get("live_window"),
        "proposals_generated_at": proposals.get("generated_at"),
        "proposals": [f"{p['proposal_id']} {p.get('title_de')}" for p in proposals.get("proposals", [])],
        "runs": run_info,
        "revivals": revival_info,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def restore(name: str) -> dict:
    source = SNAP_DIR / name
    if not (source / "manifest.json").exists():
        raise FileNotFoundError(f"No snapshot named {name}")
    backup = runs.RUNS / f"_backup_{dt.datetime.now():%Y%m%d_%H%M%S}"
    backup.mkdir(parents=True)
    for f in TOP_FILES:
        if (runs.RUNS / f).exists():
            shutil.copy2(runs.RUNS / f, backup / f)
    restored = []
    for item in source.iterdir():
        if item.name in TOP_FILES:
            shutil.copy2(item, runs.RUNS / item.name)
        elif item.is_dir() and item.name.startswith(("run_", "revival_")):
            dest = runs.run_dir(item.name)
            if dest.exists():
                shutil.move(str(dest), str(backup / item.name))
            shutil.copytree(item, dest)
            restored.append(item.name)
    return {"restored_runs": restored, "backup_of_previous_files": str(backup.relative_to(ROOT))}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "save":
        print(save(sys.argv[2], sys.argv[3:] or None))
    elif cmd == "restore":
        print(json.dumps(restore(sys.argv[2]), indent=1))
    else:
        for m in list_snapshots():
            print(m["name"], m["created_at"], [r["proposal"] for r in m["runs"]])
