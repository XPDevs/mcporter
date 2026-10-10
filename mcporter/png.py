"""
Minimal pure-stdlib PNG decoder/encoder.

Minecraft item textures are frequently split into multiple layers
(layer0..layer3).  Luanti craftitems only accept a single inventory image, so
we alpha-composite the layers ourselves.  We also need to do this without any
third-party imaging library, hence this module.

Supported decode:  bit depth 8/16, colour types 0(gray), 2(RGB), 3(palette),
                   4(gray+alpha), 6(RGBA), non-interlaced.
Supported encode:  RGBA8, non-interlaced.
"""

from __future__ import annotations

import struct
import zlib
from typing import Optional

PNG_SIG = b"\x89PNG\r\n\x1a\n"


class PNGError(Exception):
    pass


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


class Image:
    __slots__ = ("width", "height", "pixels")

    def __init__(self, width: int, height: int, pixels: bytearray):
        self.width = width
        self.height = height
        # pixels: flat RGBA, 4 bytes per pixel
        self.pixels = pixels

    def get(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        p = self.pixels
        return p[i], p[i + 1], p[i + 2], p[i + 3]

    def set(self, x: int, y: int, r: int, g: int, b: int, a: int) -> None:
        i = (y * self.width + x) * 4
        p = self.pixels
        p[i] = r
        p[i + 1] = g
        p[i + 2] = b
        p[i + 3] = a

    def copy(self) -> "Image":
        return Image(self.width, self.height, bytearray(self.pixels))


def _chunks(data: bytes):
    if data[:8] != PNG_SIG:
        raise PNGError("not a PNG file")
    off = 8
    n = len(data)
    while off + 8 <= n:
        (length,) = struct.unpack(">I", data[off:off + 4])
        ctype = data[off + 4:off + 8]
        start = off + 8
        end = start + length
        if end + 4 > n:
            raise PNGError("truncated PNG chunk")
        yield ctype, data[start:end]
        off = end + 4  # skip CRC


def decode(data: bytes) -> Image:
    width = height = 0
    bit_depth = 8
    colour_type = 6
    palette: list[tuple[int, int, int]] = []
    trns: bytes = b""
    idat = bytearray()
    interlace = 0

    for ctype, payload in _chunks(data):
        if ctype == b"IHDR":
            width, height, bit_depth, colour_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", payload[:13]
            )
        elif ctype == b"PLTE":
            palette = [
                (payload[i], payload[i + 1], payload[i + 2])
                for i in range(0, len(payload) - 2, 3)
            ]
        elif ctype == b"tRNS":
            trns = payload
        elif ctype == b"IDAT":
            idat += payload
        elif ctype == b"IEND":
            break

    if width == 0 or height == 0:
        raise PNGError("missing IHDR")
    if interlace != 0:
        raise PNGError("interlaced PNG unsupported")
    if bit_depth not in (1, 2, 4, 8, 16):
        raise PNGError(f"unsupported bit depth {bit_depth}")

    raw = zlib.decompress(bytes(idat))

    # number of channels per colour type
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    bits_per_pixel = channels * bit_depth
    bytes_per_pixel = max(1, bits_per_pixel // 8)
    stride = (width * bits_per_pixel + 7) // 8

    # Unfilter scanlines.
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _y in range(height):
        if pos >= len(raw):
            break
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        if len(line) < stride:
            line.extend(b"\x00" * (stride - len(line)))
        pos += stride
        if ft == 1:  # Sub
            for i in range(bytes_per_pixel, stride):
                line[i] = (line[i] + line[i - bytes_per_pixel]) & 0xFF
        elif ft == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:  # Average
            for i in range(stride):
                a = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:  # Paeth
            for i in range(stride):
                a = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                b = prev[i]
                c = prev[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        out += line
        prev = line

    pixels = bytearray(width * height * 4)
    maxval = (1 << bit_depth) - 1

    def sample(row: bytearray, idx: int, chan: int) -> int:
        """Return 0..255 for channel `chan` of pixel `idx` in a scanline."""
        if bit_depth == 16:
            hi = row[idx * bytes_per_pixel + chan * 2]
            return hi  # take high byte -> 8-bit
        if bit_depth == 8:
            return row[idx * bytes_per_pixel + chan]
        # sub-byte depths only occur for gray/palette with 1 channel
        bitpos = idx * bit_depth
        byte = row[bitpos // 8]
        shift = 8 - bit_depth - (bitpos % 8)
        return (byte >> shift) & maxval

    for y in range(height):
        row = out[y * stride:(y + 1) * stride]
        for x in range(width):
            if colour_type == 6:
                r = sample(row, x, 0)
                g = sample(row, x, 1)
                b = sample(row, x, 2)
                a = sample(row, x, 3)
            elif colour_type == 2:
                r = sample(row, x, 0)
                g = sample(row, x, 1)
                b = sample(row, x, 2)
                a = 255
            elif colour_type == 0:
                v = sample(row, x, 0)
                r = g = b = v
                a = 255
            elif colour_type == 4:
                v = sample(row, x, 0)
                r = g = b = v
                a = sample(row, x, 1)
            elif colour_type == 3:
                pi = sample(row, x, 0)
                if pi < len(palette):
                    r, g, b = palette[pi]
                else:
                    r = g = b = 0
                a = trns[pi] if pi < len(trns) else 255
            else:
                r = g = b = 0
                a = 0
            i = (y * width + x) * 4
            pixels[i] = r
            pixels[i + 1] = g
            pixels[i + 2] = b
            pixels[i + 3] = a

    return Image(width, height, pixels)


def encode(img: Image) -> bytes:
    raw = bytearray()
    stride = img.width * 4
    for y in range(img.height):
        raw.append(0)  # filter type None
        raw += img.pixels[y * stride:(y + 1) * stride]

    def chunk(ctype: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + ctype
            + payload
            + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0)
    return (
        PNG_SIG
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def composite_layers(layers: list[bytes]) -> Optional[bytes]:
    """Alpha-composite encoded PNG layers (bottom first) into one PNG.

    Returns None if any layer fails to decode.
    """
    imgs: list[Image] = []
    for layer in layers:
        try:
            imgs.append(decode(layer))
        except (PNGError, zlib.error, struct.error):
            return None
    if not imgs:
        return None
    w = max(i.width for i in imgs)
    h = max(i.height for i in imgs)
    base = Image(w, h, bytearray(w * h * 4))
    for src in imgs:
        for y in range(src.height):
            for x in range(src.width):
                sr, sg, sb, sa = src.get(x, y)
                if sa == 0:
                    continue
                br, bg, bb, ba = base.get(x, y)
                # standard source-over
                out_a = sa + ba * (255 - sa) // 255
                if out_a == 0:
                    continue
                nr = (sr * sa + br * ba * (255 - sa) // 255) // out_a
                ng = (sg * sa + bg * ba * (255 - sa) // 255) // out_a
                nb = (sb * sa + bb * ba * (255 - sa) // 255) // out_a
                base.set(x, y, nr, ng, nb, out_a)
    return encode(base)
