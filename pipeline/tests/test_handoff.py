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
