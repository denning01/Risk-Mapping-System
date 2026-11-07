import importlib
import json

import pytest

from pipeline.lib.paths import data_root

wf = importlib.import_module("pipeline.09_web_forecast")

KEYS = {"as_of", "icpac", "short_range", "suggested_scenario"}


@pytest.mark.parametrize("area,band,mm,cells", [("nyando", [70, 80], 19.4, 9), ("nairobi", [80, 90], 11.9, 6)])
def test_web_forecast_uses_the_aoi_mean_wettest_day_from_the_cached_snapshot(area, band, mm, cells):
    p = data_root() / "processed" / area / "forecast" / "forecast.json"
    if not p.exists():
        pytest.skip(f"no cached snapshot at {p}")
    out = wf.build(json.loads(p.read_text()))
    assert set(out) == KEYS
    assert out["icpac"]["above_normal_pct"] == band and out["icpac"]["url"].startswith("https://www.icpac.net/")
    sr = out["short_range"]
    assert sr["wettest_day_mm"] == mm  # the AOI mean, never wettest_day_point_max_mm (Nyando 27.8)
    assert f"mean of {cells} model cells" in sr["source"] and sr["url"].startswith("https://api.open-meteo.com/")
    assert out["suggested_scenario"] is None and out["as_of"] == "2026-11-06T11:02:00Z"


def _snap(tmp_path, dir_area, **over):
    snap = {"area": dir_area, "provenance": {"git_commit": "88c271a", "dirty": False}} | over
    p = tmp_path / "processed" / dir_area / "forecast" / "forecast.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(snap))
    return snap


def test_load_snapshot_refuses_a_dirty_run_a_missing_stamp_and_another_areas_snapshot(tmp_path):
    _snap(tmp_path, "nyando")
    assert wf.load_snapshot("nyando", tmp_path)["area"] == "nyando"
    _snap(tmp_path, "nairobi", provenance={"git_commit": "88c271a", "dirty": True})
    with pytest.raises(SystemExit, match="not a clean committed run"):
        wf.load_snapshot("nairobi", tmp_path)
    (tmp_path / "x").mkdir()
    _snap(tmp_path / "x", "nairobi", provenance={"dirty": False})
    with pytest.raises(SystemExit, match="not a clean committed run"):
        wf.load_snapshot("nairobi", tmp_path / "x")
    (tmp_path / "y").mkdir()
    _snap(tmp_path / "y", "nairobi", area="nyando")
    with pytest.raises(SystemExit, match="is for area 'nyando', not 'nairobi'"):
        wf.load_snapshot("nairobi", tmp_path / "y")


def test_main_goes_through_the_guard(tmp_path, monkeypatch):
    _snap(tmp_path, "nyando", provenance={"git_commit": "88c271a", "dirty": True})
    monkeypatch.setattr(wf, "data_root", lambda: tmp_path)
    with pytest.raises(SystemExit, match="REFUSED"):
        wf.main(["nyando", "--out", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()
