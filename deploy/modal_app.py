"""The ShelfReady API on Modal (serverless), so the live demo works when the author's laptop is off.

    python -m modal deploy deploy/modal_app.py      # from the project folder

What it needs on Modal:
* a secret named "shelfready" holding GEMINI_API_KEY (and optionally GEMINI_FALLBACK_API_KEY);
* the volume "shelfready-runs" (created on first deploy), mounted as backend/runs: reviews, waivers and
  cached AI answers live there, so shared review links survive the container stopping when idle.

One container at most (max_containers=1): run folders, waivers and the AI cache are files, and a single
container keeps them consistent. It stops 10 minutes after the last request and starts again on the next
one (the first request after a pause waits for it to start). The web address is fixed, so the web app on
Vercel is built once with it.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
WEB_ORIGINS = ",".join([
    "http://localhost:3000",
    "https://shelfready-check.vercel.app",
    "https://shelfready-iota.vercel.app",
    "https://shelfready-praharj123barman-3726s-projects.vercel.app",
])

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libglib2.0-0", "libgl1")  # OpenCV, used by the OCR engine, links against these
    .pip_install_from_requirements(str(ROOT / "backend" / "requirements.txt"))
    .env({"CORS_ORIGINS": WEB_ORIGINS, "REVIEW_PROCESSES": "1"})
    .add_local_dir(ROOT / "backend", "/app/backend",
                   ignore=["**/__pycache__/**", "**/.pytest_cache/**", "runs/**", "tests/**", "eval/**"])
    .add_local_dir(ROOT / "rules", "/app/rules")
    .add_local_dir(ROOT / "samples", "/app/samples")
)
runs = modal.Volume.from_name("shelfready-runs", create_if_missing=True)
app = modal.App("shelfready", image=image)


@app.function(
    secrets=[modal.Secret.from_name("shelfready")],
    volumes={"/app/backend/runs": runs},
    cpu=1.0,  # one physical core (two vCPUs): enough for OCR and PDF work, about $0.06 per hour while running
    memory=2048,  # peak use measured at about 530 MB, plus the OCR engine
    timeout=300,
    scaledown_window=600,
    max_containers=1,
)
@modal.concurrent(max_inputs=8)
@modal.asgi_app(label="shelfready-api")
def api():
    import os
    import sys

    sys.path.insert(0, "/app/backend")
    os.chdir("/app/backend")
    from app import app as fastapi_app  # backend/app.py, unchanged

    return fastapi_app
