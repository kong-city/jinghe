#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标真源生成器：深蓝渐变圆角底 + 中心圆点 + 三条菱形轨道线。

纯 Python 标准库实现（struct/zlib/math），无第三方依赖，可复现。
设计意图：仿 Electron 默认原子图标的构图，把椭圆轨道替换为菱形线条，
去掉文字，保证 16px 托盘 / 32px 任务栏 / 大尺寸桌面图标都清晰。

用法：
    python tools/generate_icon.py                    # 生成到 electron/build/icon.png
    python tools/generate_icon.py -o /path/out.png   # 指定输出
"""
import argparse
import math
import struct
import zlib

# ---------- 画布与几何参数 ----------
SIZE = 1024                      # 正方形画布
CENTER = SIZE / 2.0              # 中心点
BADGE_HALF = 458.0               # 圆角矩形半边长
BADGE_RADIUS = 205.0             # 圆角半径
AA = 1.4                         # 抗锯齿过渡宽度（像素）

R_LONG = 250.0                   # 菱形长半轴（竖向）—— 候选B 修长轨道
R_SHORT = 92.0                   # 菱形短半轴（横向）—— 候选B 修长轨道
ORBIT_ANGLES = (0.0, 60.0, 120.0)  # 三条轨道旋转角（度）
ORBIT_HALF_WIDTH = 9.0           # 轨道线半宽（线宽 18px）
CORE_RADIUS = 58.0               # 中心圆点半径
CORE_GLOW = 26.0                 # 中心圆点外发光宽度

# 配色（sRGB）
BG_TOP = (44.0, 122.0, 196.0)    # 背景渐变顶部 亮蓝
BG_BOTTOM = (13.0, 48.0, 96.0)   # 背景渐变底部 深蓝
ORBIT_COLOR = (255.0, 255.0, 255.0)   # 菱形轨道线 白
CORE_COLOR = (150.0, 224.0, 255.0)    # 中心圆点 亮青
GLOW_COLOR = (96.0, 190.0, 246.0)     # 中心发光 青蓝


def clamp(v, lo=0.0, hi=255.0):
    return lo if v < lo else (hi if v > hi else v)


def smoothstep(edge0, edge1, x):
    """标准平滑（要求 edge0 < edge1）：x<=edge0 返回 0，x>=edge1 返回 1。"""
    t = (x - edge0) / (edge1 - edge0)
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def rounded_box_sdf(px, py, half, radius):
    """圆角矩形有向距离：<0 在内部，>0 在外部，单位为像素。"""
    qx = abs(px) - (half - radius)
    qy = abs(py) - (half - radius)
    ox = max(qx, 0.0)
    oy = max(qy, 0.0)
    outside = math.hypot(ox, oy)
    inside = min(max(qx, qy), 0.0)
    return outside + inside - radius


def point_segment_dist(px, py, ax, ay, bx, by):
    """点到线段的最短距离。"""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    c1 = vx * wx + vy * wy
    if c1 <= 0.0:
        return math.hypot(wx, wy)
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(px - bx, py - by)
    t = c1 / c2
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def orbit_vertices(angle_deg):
    """生成一条菱形轨道的四个顶点（相对中心坐标）。"""
    base = [(0.0, -R_LONG), (R_SHORT, 0.0), (0.0, R_LONG), (-R_SHORT, 0.0)]
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(x * ca - y * sa, x * sa + y * ca) for x, y in base]


def orbit_alpha(px, py, vertices):
    """像素到菱形轨道线的覆盖度（抗锯齿）。"""
    best = 1e9
    for i in range(4):
        ax, ay = vertices[i]
        bx, by = vertices[(i + 1) % 4]
        d = point_segment_dist(px, py, ax, ay, bx, by)
        if d < best:
            best = d
            if best < ORBIT_HALF_WIDTH - AA:
                break
    return 1.0 - smoothstep(ORBIT_HALF_WIDTH - AA, ORBIT_HALF_WIDTH + AA, best)


def build_pixels():
    """逐像素光栅化，返回 RGBA bytearray。"""
    buf = bytearray(SIZE * SIZE * 4)
    orbits = [orbit_vertices(a) for a in ORBIT_ANGLES]
    max_orbit_reach = R_LONG + ORBIT_HALF_WIDTH + AA + 4.0

    for y in range(SIZE):
        py = y + 0.5 - CENTER
        row = y * SIZE * 4
        for x in range(SIZE):
            px = x + 0.5 - CENTER
            idx = row + x * 4

            # 圆角矩形底
            d = rounded_box_sdf(px, py, BADGE_HALF, BADGE_RADIUS)
            badge_a = 1.0 - smoothstep(-AA, AA, d)
            if badge_a <= 0.0:
                # 画布透明区
                buf[idx + 3] = 0
                continue

            # 背景线性渐变（沿 y 从顶到底）
            t = clamp((py + BADGE_HALF) / (2.0 * BADGE_HALF), 0.0, 1.0)
            r = BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t
            g = BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t
            b = BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t

            dist_center = math.hypot(px, py)

            # 三条菱形轨道
            if dist_center <= max_orbit_reach:
                for verts in orbits:
                    a = orbit_alpha(px, py, verts)
                    if a > 0.0:
                        r += (ORBIT_COLOR[0] - r) * a
                        g += (ORBIT_COLOR[1] - g) * a
                        b += (ORBIT_COLOR[2] - b) * a

            # 中心发光
            if dist_center < CORE_RADIUS + CORE_GLOW:
                ga = 1.0 - smoothstep(CORE_RADIUS - 2.0, CORE_RADIUS + CORE_GLOW, dist_center)
                r += (GLOW_COLOR[0] - r) * ga * 0.55
                g += (GLOW_COLOR[1] - g) * ga * 0.55
                b += (GLOW_COLOR[2] - b) * ga * 0.55

            # 中心圆点
            ca = 1.0 - smoothstep(CORE_RADIUS - AA, CORE_RADIUS + AA, dist_center)
            if ca > 0.0:
                r += (CORE_COLOR[0] - r) * ca
                g += (CORE_COLOR[1] - g) * ca
                b += (CORE_COLOR[2] - b) * ca

            buf[idx] = int(clamp(r) + 0.5)
            buf[idx + 1] = int(clamp(g) + 0.5)
            buf[idx + 2] = int(clamp(b) + 0.5)
            buf[idx + 3] = int(clamp(badge_a * 255.0) + 0.5)
    return buf


def write_png(path, width, height, pixels):
    """写入标准 PNG（RGBA, 8bit, filter=0）。"""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter none
        raw.extend(pixels[y * stride:(y + 1) * stride])

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    global R_LONG, R_SHORT, ORBIT_HALF_WIDTH, CORE_RADIUS
    parser = argparse.ArgumentParser(description="生成精核菱形轨道图标")
    parser.add_argument("-o", "--output", default=None, help="输出 PNG 路径")
    parser.add_argument("--long", type=float, default=None, help="菱形长半轴（默认 %s）" % R_LONG)
    parser.add_argument("--short", type=float, default=None, help="菱形短半轴（默认 %s）" % R_SHORT)
    parser.add_argument("--width", type=float, default=None, help="轨道线半宽（默认 %s）" % ORBIT_HALF_WIDTH)
    parser.add_argument("--core", type=float, default=None, help="中心圆半径（默认 %s）" % CORE_RADIUS)
    args = parser.parse_args()

    if args.long is not None:
        R_LONG = args.long
    if args.short is not None:
        R_SHORT = args.short
    if args.width is not None:
        ORBIT_HALF_WIDTH = args.width
    if args.core is not None:
        CORE_RADIUS = args.core

    import os
    default_out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "electron", "build", "icon.png")
    out = args.output or default_out
    os.makedirs(os.path.dirname(out), exist_ok=True)

    print("正在光栅化 %dx%d 图标..." % (SIZE, SIZE))
    pixels = build_pixels()
    write_png(out, SIZE, SIZE, pixels)
    print("已生成:", out)


if __name__ == "__main__":
    main()
