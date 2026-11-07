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
