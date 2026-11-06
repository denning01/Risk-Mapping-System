"""M-06: hand-off rasters must cover the area's bbox (exposure 07_scenarios.py refuses less, to half a pixel)."""
from affine import Affine
from pyproj import Transformer

from pipeline.lib import config, handoff

EQ_BOX = [35.0, -2.0, 37.0, 2.0]     # straddles the equator: the projected east edge bows out between the corners


def test_grid_for_covers_the_densified_bbox_with_at_least_one_pixel():
    for crs, box in ((32736, config.load("nyando")["handoff_bbox"]), (32737, config.load("nairobi")["handoff_bbox"]),
                     (32736, EQ_BOX)):
        tr, w, h = handoff.grid_for(box, crs, 30.0, pad_px=1)
        m = handoff.margin_px(tr, w, h, crs, box)
        assert 1.0 <= m < 2.0, (box, m)
        assert handoff.covers(tr, w, h, crs, box)
        # one pixel less on the east side and it no longer has the 1 px margin
        assert not handoff.covers(tr, w - 1, h, crs, box)


def test_a_grid_sized_from_the_four_corners_under_covers_a_bowed_edge():
    t = Transformer.from_crs(4326, 32736, always_xy=True)
    x0, y0, x1, y1 = t.transform_bounds(*EQ_BOX, densify_pts=0)       # corners only
    tr = Affine(30.0, 0, x0, 0, -30.0, y1)
    w, h = round((x1 - x0) / 30.0), round((y1 - y0) / 30.0)
    assert handoff.margin_px(tr, w, h, 32736, EQ_BOX) < -1.0          # the densified east edge sticks out (~270 m)


def test_handoff_bbox_is_the_ruled_nyando_box_and_inside_the_export_box():
    cfg = config.load("nyando")
    assert cfg["handoff_bbox"] == [34.80, -0.45, 35.30, 0.00]       # operator ruling 2026-11-05
    hb, eb = cfg["handoff_bbox"], cfg["export_bbox"]
    assert eb[0] <= hb[0] and eb[1] <= hb[1] and eb[2] >= hb[2] and eb[3] >= hb[3]
    assert config.load("nairobi")["handoff_bbox"] == config.load("nairobi")["bbox"]


RULED_NYANDO = [34.80, -0.45, 35.30, 0.00]   # operator ruling 2026-11-06: hand-off covers 34.80 even while bbox is 34.85


def test_every_nyando_handoff_raster_on_disk_covers_the_ruled_box():
    """Runs over the REAL hand-off rasters (skips only if the model has not been run on this machine)."""
    import pytest
    import rasterio
    from pipeline.lib.paths import model_dir
    m = model_dir("nyando")
    files = [m / "scenarios" / f"{r}_{e}_depth.tif" for e in ("normal", "elnino") for r in (50, 100, 150, 200, 250)]
    files += [m / "hand.tif", m / "channels.tif"]
    if not all(f.exists() for f in files):
        pytest.skip(f"Nyando hand-off rasters not on this machine ({m})")
    for f in files:
        with rasterio.open(f) as ds:
            assert ds.crs.to_epsg() == 32736, f
            assert handoff.margin_px(ds.transform, ds.width, ds.height, ds.crs, RULED_NYANDO) >= 1.0, f
            assert ds.tags().get("calibrated") in ("false", "true"), f


def test_rewriting_rasters_named_by_a_posted_handoff_is_refused(tmp_path, monkeypatch):
    """Operator ruling 2026-11-06: exposure read a mix of two versions when the depth rasters were rewritten in place."""
    import pytest
    from pipeline.lib import paths
    (tmp_path / "rms-audit" / "handoffs").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path / "repo")
    paths.refuse_if_posted("nyando", allow=False)                       # no hand-off posted: allowed
    f = tmp_path / "rms-audit" / "handoffs" / "flood-nyando.md"
    f.write_text("**WITHDRAWN — do not use.**\n")
    paths.refuse_if_posted("nyando", allow=False)                       # withdrawn: names nothing
    f.write_text("**k = 0.0191 is PROVISIONAL**\n# Hand-off\n")
    with pytest.raises(SystemExit, match="about to rewrite nyando rasters"):
        paths.refuse_if_posted("nyando", allow=False)
    paths.refuse_if_posted("nyando", allow=True)                        # explicit --rewrite-posted


def test_margin_counts_every_side():
    box = config.load("nyando")["handoff_bbox"]
    tr, w, h = handoff.grid_for(box, 32736, 30.0, pad_px=1)
    from affine import Affine
    shrunk = {
        "west": (Affine(30.0, 0, tr.c + 60, 0, -30.0, tr.f), w - 2, h),
        "east": (tr, w - 2, h),
        "north": (Affine(30.0, 0, tr.c, 0, -30.0, tr.f - 60), w, h - 2),
        "south": (tr, w, h - 2),
    }
    for side, (t2, w2, h2) in shrunk.items():
        assert handoff.margin_px(t2, w2, h2, 32736, box) < 0, side


def test_handoff_refuses_dirty_or_unstamped_runs():
    import pytest
    assert handoff.check_provenance("x.json", {"provenance": {"git_commit": "abc1234", "dirty": False}}) == "abc1234"
    for rep in ({}, {"provenance": {"git_commit": "abc1234", "dirty": True}}, {"provenance": {"git_commit": "", "dirty": False}}):
        with pytest.raises(SystemExit, match="REFUSED"):
            handoff.check_provenance("x.json", rep)


def test_no_posted_nyando_depth_raster_floods_worldcover_water():
    """F5.4: the WorldCover-80 exclusion, checked on the REAL rasters (a bypass inside 03 would otherwise pass)."""
    import numpy as np
    import pytest
    import rasterio
    from rasterio.warp import Resampling
    from pipeline.lib.paths import model_dir, raw_dir
    from pipeline.lib.rio import grid_of, to_utm
    m = model_dir("nyando")
    files = [m / "scenarios" / f"{r}_{e}_depth.tif" for e in ("normal", "elnino") for r in (50, 100, 150, 200, 250)]
    wc = raw_dir("nyando") / "worldcover_2021.tif"
    if not wc.exists() or not all(f.exists() for f in files):
        pytest.skip("Nyando rasters not on this machine")
    lc, _ = to_utm(wc, 32736, Resampling.mode, like=grid_of(files[0]))
    for f in files:
        with rasterio.open(f) as ds:
            assert not (np.isfinite(ds.read(1)) & (lc == 80)).any(), f
