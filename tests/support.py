"""Shared fixtures for the combat bot tests."""
from __future__ import annotations

import copy
import gzip
import json
import os
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_stream():
    path = os.path.join(ROOT, "check", "stream.jsonl.gz")
    with gzip.open(path, "rt") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def schema():
    path = os.path.join(ROOT, "check", "check.py")
    spec = importlib.util.spec_from_file_location("mfcheck", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Schema(os.path.join(ROOT, "mechfight.schema.json"))


def hello_without_map(stream=None):
    stream = stream or load_stream()
    hello = copy.deepcopy(stream[0])
    hello["map"]["dir"] = "/tmp/phantom-duelist-no-such-arena"
    return hello


def fresh_obs(stream=None):
    stream = stream or load_stream()
    obs = copy.deepcopy(next(msg for msg in stream if msg.get("type") == "obs"))
    obs["mechs"] = []
    obs["projectiles"] = []
    obs["crates"] = []
    obs["cubes"] = []
    obs["pickups"] = []
    obs["sounds"] = []
    obs["beams"] = []
    obs["events"] = []
    obs["drops"] = []
    obs["offer"] = None
    return obs
