"""Draws docs/slides/figures/methods_chain.png (M-10). Values come from audited rounds R5-R8.

    .venv/bin/python docs/slides/figures/make_methods_chain.py docs/slides/figures/methods_chain.png
"""
import sys, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
out = sys.argv[1]
fig, ax = plt.subplots(figsize=(13, 6.2)); ax.set_xlim(0, 13); ax.set_ylim(0, 6.2); ax.axis("off")
def box(x, y, w, h, title, body, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12", fc=fc, ec="#333", lw=1))
    ax.text(x + w / 2, y + h - 0.2, title, ha="center", va="top", fontsize=10.5, weight="bold")
    ax.text(x + w / 2, y + h - 0.55, body, ha="center", va="top", fontsize=8.6, linespacing=1.35)
def arrow(x0, y0, x1, y1):
    ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="-|>", color="#333", lw=1.3))
IN, MID, CAL = "#e8eef7", "#eef6ea", "#fbefe3"
box(0.2, 4.15, 2.9, 1.8, "Terrain", "DEM 30 m (Nyando GLO-30,\nNairobi FABDEM)\nfill, D8 flow, channels\nHAND = height above\nnearest drainage", IN)
box(0.2, 2.15, 2.9, 1.8, "Runoff", "CN from ESA WorldCover\n+ SoilGrids soil group\nSCS-CN: rain P (mm/24 h)\n-> runoff Q (mm)", IN)
box(0.2, 0.15, 2.9, 1.8, "Scenarios", "P = 50..250 mm / 24 h\nEl Niño: P x CHIRPS\nOND 2023 / 1991-2020\n(Nyando x1.42, Nairobi x1.15)", IN)
box(3.9, 2.15, 3.2, 1.8, "Stage", "upstream runoff volume V\nstage h = k * V^0.4\n(Leopold & Maddock 1953)", MID)
box(7.9, 2.15, 2.6, 1.8, "Flood mask", "HAND < h\nslope < 15°\nconnected to a channel\npermanent water removed", MID)
box(11.0, 2.15, 1.8, 1.8, "Depth", "h - HAND (m)\n<0.3 low\n0.3-1 medium\n>1 high", MID)
box(3.9, 4.15, 6.6, 1.8, "Calibration of k (Nyando, Nov 2023)", "Sentinel-1 VH change (UN-SPIDER: ratio > 1.25, slope < 5 %, speckle removed)\n"
    "k = argmax F1 over 41 values -> k = 0.0126\nF1 0.19 · IoU 0.10 (terrain-only baseline F1 0.18)\nNairobi: urban SAR does not identify k -> Nyando k transferred", CAL)
arrow(3.1, 3.05, 3.9, 3.05)                       # runoff Q -> stage
arrow(1.65, 1.95, 1.65, 2.15)                     # scenario P -> runoff
arrow(5.5, 4.15, 5.5, 3.95); ax.text(5.6, 4.02, "k", fontsize=9, weight="bold")
arrow(3.1, 4.5, 3.9, 3.7); ax.text(3.15, 4.0, "flow\naccum.", fontsize=7.5, color="#444")
arrow(7.1, 3.05, 7.9, 3.05); arrow(10.5, 3.05, 11.0, 3.05)
ax.annotate("", (9.2, 3.95), (3.1, 4.3), arrowprops=dict(arrowstyle="-|>", color="#888", lw=1, connectionstyle="arc3,rad=-0.08"))
ax.text(8.6, 4.0, "HAND", fontsize=8, color="#666")
ax.text(3.9, 0.95, "Screening-level: a calibrated terrain + runoff approximation, not a hydraulic model.\n"
        "Scenarios are 'what if this much rain falls in 24 h', not forecasts.", ha="left", fontsize=9.5, style="italic")
fig.savefig(out, dpi=150, bbox_inches="tight"); print("wrote", out)
