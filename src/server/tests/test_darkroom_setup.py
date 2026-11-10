# SPDX-License-Identifier: GPL-2.0-only
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from mfilm_server import config as config_mod
from mfilm_server.darkroom.app import create_app
from mfilm_server.store import Store

API = "/api/v1/darkroom"

@pytest.fixture
def clean_setup(tmp_path):
    store = Store(tmp_path / "data")
    store.init()
    cfg_file = tmp_path / "config.toml"
    cfg = config_mod.Config(data_dir=store.root)
    config_mod.save(cfg_file, cfg)
    app = create_app(store, cfg, config_path=cfg_file)
    client = TestClient(app)
    return client, store, cfg_file, cfg

def test_setup_status_onboarding_needed(clean_setup):
    client, store, cfg_file, cfg = clean_setup
    r = client.get(f"{API}/setup/status")
    assert r.status_code == 200
    data = r.json()
    assert data["onboarding_needed"] is True
    assert data["auth_configured"] is False
    assert data["photoprism_configured"] is False
    assert "data_dir" in data["config"]

def test_setup_save_initial_flow(clean_setup):
    client, store, cfg_file, cfg = clean_setup
    # 1. Weak password rejected
    r_bad = client.post(f"{API}/setup/save", json={"password": "short"})
    assert r_bad.status_code == 400
    assert r_bad.json()["error_code"] == "WEAK_PASSWORD"

    # 2. Complete setup
    orig_dir = store.root / "photos"
    orig_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "password": "supersecretpassword123",
        "data_dir": str(store.root),
        "photoprism_url": "http://127.0.0.1:2342",
        "photoprism_token": "app-token-xyz-12345",
        "photoprism_originals_dir": str(orig_dir),
        "photoprism_web_folder": "Chromurgy/Developed",
        "photoprism_index_template": "docker exec photoprism photoprism index {path}",
        "worker_jobs": 2
    }
    r = client.post(f"{API}/setup/save", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["authenticated"] is True
    # Session cookie must be set
    assert "mfilm_session" in client.cookies

    # 3. Status now indicates onboarding is done
    st = client.get(f"{API}/setup/status").json()
    assert st["onboarding_needed"] is False
    assert st["auth_configured"] is True
    assert st["config"]["photoprism_url"] == "http://127.0.0.1:2342"
    assert st["config"]["photoprism_token_set"] is True
    assert st["config"]["worker_jobs"] == 2

    # 4. Verify config.toml on disk
    loaded_cfg = config_mod.load(cfg_file)
    assert loaded_cfg.photoprism.url == "http://127.0.0.1:2342"
    assert loaded_cfg.jobs == 2
    assert loaded_cfg.photoprism.token_file.is_file()
    assert loaded_cfg.photoprism.token_file.read_text().strip() == "app-token-xyz-12345"
