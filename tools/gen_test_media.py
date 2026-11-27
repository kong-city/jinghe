#!/usr/bin/env python3
"""程序化生成测试媒体：PNG 图片 / WAV 音频 / AVI 视频。
纯 Python 标准库，无第三方依赖、无积分消耗。
用途：给精核做端到端媒体处理测试。"""
from __future__ import annotations

import math
import struct
import wave
import zlib
from pathlib import Path

# --- 5x7 点阵字模（够拼 "JINGHE TEST 2026"）-----------------------------
FONT = {
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "6": ("00111", "01000", "10000", "11110", "10001", "10001", "01110"),
    " ": ("00000",) * 7,
}


def _draw_text(buf: bytearray, w: int, h: int, text: str, x0: int, y0: int,
               scale: int, rgb: tuple[int, int, int]) -> None:
    """把点阵文字画进 RGB buffer。"""
    cx = x0
    for ch in text.upper():
        glyph = FONT.get(ch, FONT[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                for sy in range(scale):
                    for sx in range(scale):
                        px, py = cx + gx * scale + sx, y0 + gy * scale + sy
                        if 0 <= px < w and 0 <= py < h:
                            i = (py * w + px) * 3
                            buf[i:i + 3] = bytes(rgb)
        cx += 6 * scale


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def gen_png(path: Path) -> dict:
    """生成 640x360 带彩色渐变与 'JINGHE TEST 2026' 文字的 PNG。"""
    w, h = 640, 360
    buf = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 3
            buf[i] = int(40 + 180 * x / w)
            buf[i + 1] = int(60 + 150 * y / h)
            buf[i + 2] = 200
    for yy in (70, 290):
        for x in range(40, w - 40):
            i = (yy * w + x) * 3
            buf[i:i + 3] = b"\xff\xff\xff"
    _draw_text(buf, w, h, "JINGHE TEST 2026", 120, 120, 6, (255, 255, 255))
    _draw_text(buf, w, h, "PNG IMAGE", 220, 220, 3, (20, 20, 90))

    raw = b"".join(b"\x00" + bytes(buf[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    png = (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + _png_chunk(b"IDAT", zlib.compress(raw, 9))
           + _png_chunk(b"IEND", b""))
    path.write_bytes(png)
    return {"size": len(png), "w": w, "h": h}


def gen_wav(path: Path) -> dict:
    """生成 3 秒 44.1kHz 16bit 单声道 WAV：和弦 + 节奏脉冲。"""
    rate, secs = 44100, 3
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for n in range(rate * secs):
            t = n / rate
            tone = (math.sin(2 * math.pi * 261.63 * t)
                    + math.sin(2 * math.pi * 329.63 * t)
                    + math.sin(2 * math.pi * 392.00 * t)) / 3
            pulse = 0.6 if (t % 1.0) < 0.15 else 1.0
            env = 0.45 * (0.7 + 0.3 * math.sin(2 * math.pi * 0.5 * t))
            sample = int(max(-1, min(1, tone * env * pulse)) * 32767)
            frames += struct.pack("<h", sample)
        wf.writeframes(bytes(frames))
    return {"size": path.stat().st_size, "rate": rate, "secs": secs}


def _avi_chunk(tag: bytes, data: bytes) -> bytes:
    pad = b"\x00" if len(data) % 2 else b""
    return tag + struct.pack("<I", len(data)) + data + pad


def gen_avi(path: Path) -> dict:
    """生成 2 秒 10fps 320x240 未压缩 AVI：移动彩色方块 + 背景渐变。"""
    w, h, fps, secs = 320, 240, 10, 2
    nframes = fps * secs
    stride = w * 3 + ((4 - (w * 3) % 4) % 4)

    frames = []
    for f in range(nframes):
        buf = bytearray(w * h * 3)
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 3
                buf[i] = 30 + (x * 200 // w)
                buf[i + 1] = 40 + (y * 160 // h)
                buf[i + 2] = 120
        bx, by = 30 + f * 22, 90
        for yy in range(by, by + 50):
            for xx in range(bx, min(bx + 50, w)):
                i = (yy * w + xx) * 3
                buf[i:i + 3] = bytes((250, 230, 60))
        raw = bytearray()
        for y in range(h - 1, -1, -1):
            raw += buf[y * w * 3:(y + 1) * w * 3] + b"\x00" * (stride - w * 3)
        frames.append(bytes(raw))

    strh = struct.pack(
        "<4s4sIHHIIIIIIIIhhhh",
        b"vids", b"DIB ", 0, 0, 0, 0, 1, fps, 0,
        nframes, stride * h, 0xFFFFFFFF, 0, 0, 0, w, h,
    )
    strf = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, stride * h, 0, 0, 0, 0)
    strl = _avi_chunk(b"strh", strh) + _avi_chunk(b"strf", strf)
    avih = struct.pack(
        "<IIIIIIIIII4I",
        int(1_000_000 / fps), stride * h * fps, 0, 0x10,
        nframes, 0, 1, stride * h, w, h, 0, 0, 0, 0,
    )
    hdrl = _avi_chunk(b"avih", avih) + _avi_chunk(b"LIST", b"strl" + strl)

    movi_data = b""
    idx = bytearray()
    for fr in frames:
        offset = len(movi_data)
        movi_data += _avi_chunk(b"00dc", fr)
        idx += struct.pack("<4sIII", b"00dc", 0x10, offset, len(fr))
    movi = _avi_chunk(b"LIST", b"movi" + movi_data)
    riff_body = b"AVI " + _avi_chunk(b"LIST", b"hdrl" + hdrl) + movi + _avi_chunk(b"idx1", bytes(idx))
    path.write_bytes(b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body)
    return {"size": path.stat().st_size, "w": w, "h": h, "fps": fps, "frames": nframes}


def main() -> None:
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_media")
    out.mkdir(parents=True, exist_ok=True)
    results = {
        "image": gen_png(out / "精核测试图片.png"),
        "audio": gen_wav(out / "精核测试音频.wav"),
        "video": gen_avi(out / "精核测试视频.avi"),
    }
    for k, v in results.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
