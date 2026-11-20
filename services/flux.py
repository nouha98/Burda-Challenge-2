"""Black Forest Labs FLUX image generation (async: submit -> poll -> download).

Delivery URLs expire, so the image is downloaded right away and stored locally.
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
API = "https://api.bfl.ai/v1"
MODEL = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))["image"]


class FluxError(RuntimeError):
    pass


FAILED = {"Error", "Failed", "Content Moderated", "Request Moderated", "Task not found"}


def _headers() -> dict:
    key = os.environ.get("BFL_API_KEY")
    if not key:
        raise FluxError("BFL_API_KEY missing")
    return {"x-key": key, "accept": "application/json"}


def submit(prompt: str, width: int = 1024, height: int = 1024, output_format: str | None = "jpeg") -> dict:
    payload = {"prompt": prompt, "width": width, "height": height}
    if output_format is not None:
        payload["output_format"] = output_format
    resp = requests.post(f"{API}/{MODEL}", headers=_headers(), timeout=30, json=payload)
    if resp.status_code != 200:
        raise FluxError(f"submit HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def wait(job: dict, timeout_s: int = 240) -> dict:
    """Poll until Ready. Any status that is not an explicit failure (Pending, Queued, Generating, …) means: keep waiting."""
    polling_url = job.get("polling_url") or f"{API}/get_result?id={job['id']}"
    started = time.time()
    while time.time() - started < timeout_s:
        r = requests.get(polling_url, headers=_headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "Ready":
            img = requests.get(data["result"]["sample"], timeout=60)
            img.raise_for_status()
            return {"job_id": job.get("id"), "model": MODEL, "bytes": img.content, "cost_credits": job.get("cost"),
                    "seconds": round(time.time() - started, 1), "seed": data["result"].get("seed")}
        if status in FAILED:
            raise FluxError(f"job {job.get('id')} ended with status {status}: {str(data)[:300]}")
        time.sleep(1.5)
    raise FluxError(f"job {job.get('id')} not ready after {timeout_s} s (job ID kept – resume with wait())")


def generate(prompt: str, width: int = 1024, height: int = 1024, timeout_s: int = 240) -> dict:
    return wait(submit(prompt, width, height), timeout_s)
