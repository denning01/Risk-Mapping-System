"""M-17 e2e fixture: a flat terrarium DEM tile (256x256) at a known height, so the browser test can check the decode.

terrarium (github.com/tilezen/joerd/blob/master/docs/formats.md): height = (R*256 + G + B/256) - 32768.
1600 m -> 34368 = 134*256 + 64 + 0/256 -> RGB (134, 64, 0).
"""
import struct
import zlib
from pathlib import Path

H = 1600
v = H + 32768
rgb = (v // 256, v % 256, 0)
assert (rgb[0] * 256 + rgb[1] + rgb[2] / 256) - 32768 == H
out = Path(__file__).with_name("terrarium-1600.png")
# a plain 8-bit RGB PNG written with the standard library (no new dependency)
chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
raw = b"".join(b"\x00" + bytes(rgb) * 256 for _ in range(256))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
out.write_bytes(png)
print(out, rgb)
