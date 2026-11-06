"""M-05: the Sentinel-1 observed-flood rule (UN-SPIDER), the scores, and 03 picking up the calibrated k."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bt = _load("05_backtest.py")


def test_scores_match_hand_calculation():
    obs = np.array([1, 1, 1, 0, 0, 0, 1, 0], bool)
    mod = np.array([1, 1, 0, 1, 1, 0, 0, 0], bool)
    dom = np.array([1, 1, 1, 1, 1, 1, 1, 0], bool)   # last cell outside the domain
    s = bt.scores(mod, obs, dom)
    # tp 2, fp 2, fn 2: precision 0.5, recall 0.5, F1 0.5, IoU 2/6
    assert (s["tp"], s["fp"], s["fn"]) == (2, 2, 2)
    assert s["precision"] == 0.5 and s["recall"] == 0.5 and s["f1"] == 0.5 and s["iou"] == pytest.approx(0.3333, abs=1e-4)
    assert s["model_km2"] == pytest.approx(4 * 900 / 1e6, abs=0.01)


def _scene(n=40):
    before = np.full((n, n), -15.0)
    event = before.copy()
    event[5:15, 5:15] = -20.0         # 100 px patch, ratio 1.333 > 1.25 -> flood
    event[25, 25] = -25.0             # single pixel: speckle, dropped (connected to <= 8 neighbours)
    event[30:33, 5:8] = -25.0         # 9 px patch: each pixel has <= 8 connected neighbours -> dropped
    event[20:30, 30:38] = -18.0       # ratio 1.2 < 1.25 -> not flood
    return before, event


def test_observed_follows_the_un_spider_rule():
    before, event = _scene()
    water = np.zeros(before.shape, bool)
    slope = np.zeros(before.shape)
    o = bt.observed(before, event, water, slope)
    assert o[7:13, 7:13].all()                        # interior of the real patch
    assert not o[25, 25] and not o[30:33, 5:8].any()   # speckle and a 9-px patch dropped
    assert not o[20:30, 30:38].any()                   # below the 1.25 ratio
    # water and slopes over 5 % are never observed flood
    water[5:15, 5:10] = True
    slope[5:15, 10:15] = 3.0                           # tan(3 deg) = 5.24 % > 5 %
    o2 = bt.observed(before, event, water, slope)
    assert not o2[5:15, 5:15].any()
    slope[5:15, 10:15] = 2.8                           # 4.89 % -> kept (patch 10x5 = 50 px)
    assert bt.observed(before, event, water, slope)[7:13, 11:14].all()


def test_03_takes_k_from_the_backtest_when_one_exists(tmp_path, monkeypatch):
    rf = _load("03_runoff_flood.py")
    monkeypatch.setenv("RMS_DATA", str(tmp_path))
    assert rf.calibrated_k("nyando") is None                 # no backtest -> provisional k
    d = tmp_path / "processed" / "nyando" / "model" / "backtest"
    d.mkdir(parents=True)
    (d / "backtest.json").write_text(json.dumps({"provenance": {"git_commit": "abc1234"}, "best": {
        "k": 0.0126, "all": {"f1": 0.19, "iou": 0.1, "precision": 0.12, "recall": 0.46}}}))
    c = rf.calibrated_k("nyando")
    assert c["k"] == 0.0126 and c["f1"] == 0.19 and c["commit"] == "abc1234"


REAL = Path("/Users/mac/IGAD/data/processed/nyando/model/backtest/backtest.json")


@pytest.mark.skipif(not REAL.exists(), reason="no local backtest")
def test_real_backtest_is_consistent_and_not_suspiciously_good():
    b = json.loads(REAL.read_text())
    best = b["best"]
    assert best["all"]["f1"] == max(r["all"]["f1"] for r in b["curve"])
    s = best["all"]
    p, r = s["tp"] / (s["tp"] + s["fp"]), s["tp"] / (s["tp"] + s["fn"])
    assert s["f1"] == pytest.approx(2 * p * r / (p + r), abs=1e-4)
    assert 0 < s["observed_km2"] < b["domain_km2"] * 0.2          # not empty, not everything
    assert len(b["event"]) >= 1 and all(a["date"].startswith("2023-11") for a in b["event"])
