import json
from pathlib import Path

from services import flux


def test_application_configures_flux_3_image_klein():
    root = Path(__file__).resolve().parents[1]
    configured = json.loads((root / "config" / "models.json").read_text(encoding="utf-8"))["image"]
    assert configured == "flux-3-image-klein"
    assert flux.MODEL == configured


def test_submit_omits_output_format_only_when_the_endpoint_does_not_accept_it(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"id": "job-test", "polling_url": "https://example.test/poll"}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(flux, "_headers", lambda: {})
    monkeypatch.setattr(flux.requests, "post", fake_post)
    monkeypatch.setattr(flux, "MODEL", "flux-3-image")

    flux.submit("A finished recipe", width=768, height=768, output_format=None)
    monkeypatch.setattr(flux, "MODEL", "flux-3-image-klein")
    flux.submit("A finished recipe", width=768, height=768)

    assert calls[0]["json"] == {"prompt": "A finished recipe", "width": 768, "height": 768}
    assert calls[1]["json"]["output_format"] == "jpeg"
    assert calls[0]["url"].endswith("/flux-3-image")
    assert calls[1]["url"].endswith("/flux-3-image-klein")
