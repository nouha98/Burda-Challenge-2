"""Black Forest Labs FLUX image generation (async: submit -> poll -> download).

Delivery URLs expire, so the image is downloaded right away and stored locally.
"""
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
API = "https://api.bfl.ai/v1"
MODEL = "flux-2-pro"


class FluxError(RuntimeError):
    pass


def generate(prompt: str, width: int = 1024, height: int = 1024, timeout_s: int = 180) -> dict:
    key = os.environ.get("BFL_API_KEY")
    if not key:
        raise FluxError("BFL_API_KEY missing")
    headers = {"x-key": key, "accept": "application/json"}
    resp = requests.post(f"{API}/{MODEL}", headers=headers, timeout=30,
                         json={"prompt": prompt, "width": width, "height": height, "output_format": "jpeg"})
    if resp.status_code != 200:
        raise FluxError(f"submit HTTP {resp.status_code}: {resp.text[:300]}")
    job = resp.json()
    polling_url = job.get("polling_url") or f"{API}/get_result?id={job['id']}"
    started = time.time()
    while time.time() - started < timeout_s:
        time.sleep(1.5)
        r = requests.get(polling_url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "Ready":
            sample_url = data["result"]["sample"]
            img = requests.get(sample_url, timeout=60)
            img.raise_for_status()
            return {"job_id": job.get("id"), "model": MODEL, "bytes": img.content,
                    "seconds": round(time.time() - started, 1), "seed": data["result"].get("seed")}
        if status not in ("Pending", "Processing", "Queued"):
            raise FluxError(f"job {job.get('id')} ended with status {status}: {str(data)[:300]}")
    raise FluxError(f"job {job.get('id')} not ready after {timeout_s} s")
