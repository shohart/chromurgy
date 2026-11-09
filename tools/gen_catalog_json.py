#!/usr/bin/env python3
"""Regenerate the runtime JSON catalogs from the authoritative YAML (needs PyYAML; the server itself does not).

contracts/v0.7/optical-effects-catalog.yaml -> optical-effects-catalog.json
contracts/v0.7/curated-combos-v07.yaml      -> curated-combos-v07.json"""
import json
from pathlib import Path

import yaml

D = Path(__file__).resolve().parents[1] / "contracts" / "v0.7"
for name in ("optical-effects-catalog", "curated-combos-v07"):
    doc = yaml.safe_load((D / f"{name}.yaml").read_text(encoding="utf-8"))
    (D / f"{name}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    print("wrote", f"{name}.json")
