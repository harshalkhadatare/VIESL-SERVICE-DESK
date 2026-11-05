"""Generates the small animated GIFs used in notification emails (app/assets/email/*.gif).

GIF is the only animation that works in Gmail, Outlook web/mobile and Apple Mail (CSS animation is stripped
by most email clients). Outlook for Windows shows the first frame, so every first frame is a complete picture.
Run:  python scripts/make_email_art.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "app" / "assets" / "email"
SIZE = 132          # final pixels (shown at 66 px → sharp on phones)
SS = 4              # supersampling for smooth edges
S = SIZE * SS
FRAMES = 24
DURATION = 70       # ms per frame

COL = {
    "blue": ((29, 95, 196), (228, 238, 251)), "indigo": ((90, 72, 214), (235, 232, 253)),
    "green": ((21, 122, 82), (227, 244, 236)), "amber": ((196, 120, 10), (253, 241, 220)),
    "orange": ((214, 98, 22), (253, 236, 222)), "red": ((180, 35, 24), (253, 236, 235)),
    "slate": ((75, 91, 114), (232, 236, 242)), "teal": ((15, 138, 133), (222, 244, 242)),
}


def canvas(tint):
    im = Image.new("RGB", (S, S), (255, 255, 255))
    d = ImageDraw.Draw(im)
    m = 6 * SS
    d.ellipse([m, m, S - m, S - m], fill=tint)
    return im, d


def finish(im):
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


def P(x, y):
    return (x * S / 100, y * S / 100)


def circle(d, cx, cy, r, **kw):
    d.ellipse([*P(cx - r, cy - r), *P(cx + r, cy + r)], **kw)


def line(d, pts, w, fill):
    d.line([P(*p) for p in pts], fill=fill, width=int(w * S / 100), joint="curve")
    for p in (pts[0], pts[-1]):
        circle(d, p[0], p[1], w / 2, fill=fill)


def check(d, prog, color, cx=50, cy=52, scale=1.0, w=7):
    """Check mark drawn progressively (prog 0..1)."""
    a, b, c = (cx - 16 * scale, cy), (cx - 5 * scale, cy + 11 * scale), (cx + 17 * scale, cy - 12 * scale)
    l1 = math.dist(a, b)
    l2 = math.dist(b, c)
    L = (l1 + l2) * prog
    if L <= 0:
        return
    if L <= l1:
        t = L / l1
        line(d, [a, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)], w, color)
    else:
        t = (L - l1) / l2
        line(d, [a, b, (b[0] + (c[0] - b[0]) * t, b[1] + (c[1] - b[1]) * t)], w, color)


def save(name, frames, durations=None):
    OUT.mkdir(parents=True, exist_ok=True)
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    pal[0].save(OUT / f"{name}.gif", save_all=True, append_images=pal[1:], loop=0,
                duration=durations or DURATION, optimize=True, disposal=1)
    print(f"{name}.gif  {(OUT / f'{name}.gif').stat().st_size // 1024} KB")


# ------------------------------------------------------------------ pictures
def received():
    c, t = COL["blue"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        k = i / FRAMES
        bob = math.sin(k * 2 * math.pi) * 2.2
        # envelope
        d.rounded_rectangle([*P(24, 36 + bob), *P(76, 72 + bob)], radius=6 * SS, fill=(255, 255, 255), outline=c,
                            width=4 * SS)
        line(d, [(26, 39 + bob), (50, 57 + bob), (74, 39 + bob)], 4, c)
        # check badge pops in and pulses
        s = min(1, k * 3) if i < FRAMES // 3 else 1 + 0.06 * math.sin((k - 1 / 3) * 6 * math.pi)
        s = max(s, 0.001) if i else 1        # first frame complete (Outlook shows only frame 1)
        circle(d, 72, 70, 13 * s, fill=COL["green"][0])
        check(d, 1, (255, 255, 255), cx=72, cy=71, scale=0.42 * s, w=3.6)
        frames.append(finish(im))
    save("received", frames)


def bell():
    c, t = COL["amber"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        k = i / FRAMES
        ang = math.sin(k * 4 * math.pi) * (18 if k < 0.5 else 18 * (1 - (k - 0.5) * 2)) if i else 0
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.pieslice([*P(28, 26), *P(72, 74)], 180, 360, fill=c)
        ld.rectangle([*P(28, 49), *P(72, 64)], fill=c)
        ld.rounded_rectangle([*P(22, 62), *P(78, 69)], radius=3 * SS, fill=c)
        circle(ld, 50, 24, 4, fill=c)
        layer = layer.rotate(ang, center=P(50, 22), resample=Image.BICUBIC)
        im.paste(layer, (0, 0), layer)
        circle(d, 50 + ang * 0.35, 75, 6, fill=c)
        if i and abs(ang) > 6:   # motion lines
            for side in (-1, 1):
                line(d, [(50 + side * 34, 36), (50 + side * 39, 31)], 3, c)
        frames.append(finish(im))
    save("bell", frames)


def assigned():
    c, t = COL["indigo"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        k = i / FRAMES
        r = 24 + 16 * k
        a = int(255 * (1 - k))
        ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse([*P(50 - r, 50 - r), *P(50 + r, 50 + r)], outline=(*c, a), width=3 * SS)
        im.paste(ring, (0, 0), ring)
        circle(d, 50, 40, 11, fill=c)                                       # head
        d.pieslice([*P(28, 54), *P(72, 98)], 180, 360, fill=c)              # shoulders
        circle(d, 69, 66, 10, fill=COL["green"][0])
        check(d, 1, (255, 255, 255), cx=69, cy=67, scale=0.33, w=3)
        frames.append(finish(im))
    save("assigned", frames)


def gear_shape(d, cx, cy, r_out, r_in, teeth, rot, fill, hole):
    pts = []
    for j in range(teeth * 4):
        a = rot + j * (2 * math.pi / (teeth * 4))
        r = r_out if j % 4 in (0, 1) else r_in
        pts.append(P(cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, fill=fill)
    circle(d, cx, cy, hole, fill=(255, 255, 255))


def working():
    c, t = COL["blue"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        rot = i / FRAMES * (2 * math.pi / 8)
        gear_shape(d, 44, 46, 22, 17, 8, rot, c, 7)
        gear_shape(d, 68, 68, 13, 10, 6, -rot * 8 / 6 + 0.3, COL["teal"][0], 4)
        frames.append(finish(im))
    save("working", frames)


def bubble(d, color):
    d.rounded_rectangle([*P(22, 28), *P(78, 66)], radius=12 * SS, fill=color)
    d.polygon([P(34, 64), P(30, 78), P(48, 65)], fill=color)


def question():
    c, t = COL["amber"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        bubble(d, c)
        k = i / FRAMES
        y = -abs(math.sin(k * 2 * math.pi)) * 4
        # question mark
        d.arc([*P(41, 33 + y), *P(59, 51 + y)], 200, 90, fill=(255, 255, 255), width=5 * SS)
        line(d, [(50, 51 + y), (50, 54 + y)], 5, (255, 255, 255))
        circle(d, 50, 60 + y, 3, fill=(255, 255, 255))
        frames.append(finish(im))
    save("question", frames)


def reply():
    c, t = COL["blue"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        bubble(d, c)
        k = i / FRAMES
        for j, x in enumerate((37, 50, 63)):
            ph = (k - j * 0.15) % 1
            y = -math.sin(ph * 2 * math.pi) * 4 if ph < 0.5 else 0
            circle(d, x, 47 + y, 4.6, fill=(255, 255, 255))
        frames.append(finish(im))
    save("reply", frames)


def resolved():
    c, t = COL["green"]
    frames = []
    durs = []
    n = 28
    for i in range(n):
        im, d = canvas(t)
        k = i / (n - 1)
        circle(d, 50, 50, 27, fill=c)
        prog = 1 if i == 0 else min(1, k * 2.2)          # frame 1 already complete for Outlook
        if i:
            prog = min(1, max(0.0, (k - 0.05) * 2.2))
        check(d, prog if i else 1, (255, 255, 255), scale=0.95, w=7)
        if k > 0.45:  # sparkles
            sk = (k - 0.45) / 0.55
            for a in range(8):
                ang = a * math.pi / 4
                r1, r2 = 31 + sk * 6, 35 + sk * 10
                col = COL["amber"][0] if a % 2 else c
                alpha_ok = sk < 0.85
                if alpha_ok:
                    line(d, [(50 + r1 * math.cos(ang), 50 + r1 * math.sin(ang)),
                             (50 + r2 * math.cos(ang), 50 + r2 * math.sin(ang))], 3, col)
        frames.append(finish(im))
        durs.append(900 if i == n - 1 else 55)
    save("resolved", frames, durs)


def reopened():
    c, t = COL["orange"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        rot = i / FRAMES * 360
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for start in (20, 200):
            ld.arc([*P(27, 27), *P(73, 73)], start, start + 130, fill=c, width=7 * SS)
            a = math.radians(start + 130)
            tip = (50 + 23 * math.cos(a), 50 + 23 * math.sin(a))
            perp = a + math.pi / 2
            ld.polygon([P(tip[0] + 8 * math.cos(perp), tip[1] + 8 * math.sin(perp)),
                        P(tip[0] - 7 * math.cos(a), tip[1] - 7 * math.sin(a)),
                        P(tip[0] + 7 * math.cos(a), tip[1] + 7 * math.sin(a))], fill=c)
        layer = layer.rotate(-rot, center=P(50, 50), resample=Image.BICUBIC)
        im.paste(layer, (0, 0), layer)
        frames.append(finish(im))
    save("reopened", frames)


def closed():
    c, t = COL["slate"]
    frames = []
    durs = []
    n = 20
    for i in range(n):
        im, d = canvas(t)
        k = i / (n - 1)
        lift = 0 if i == 0 else 9 * (1 - ease(min(1, k * 1.6)))
        d.arc([*P(36, 24 - lift), *P(64, 52 - lift)], 180, 360, fill=c, width=6 * SS)
        line(d, [(36, 38 - lift), (36, 47)], 6, c)
        line(d, [(64, 38 - lift), (64, 47)], 6, c)
        d.rounded_rectangle([*P(28, 46), *P(72, 76)], radius=6 * SS, fill=c)
        circle(d, 50, 58, 4, fill=(255, 255, 255))
        line(d, [(50, 60), (50, 66)], 3, (255, 255, 255))
        frames.append(finish(im))
        durs.append(1000 if i == n - 1 else 50)
    save("closed", frames, durs)


def priority():
    c, t = COL["red"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        y = -abs(math.sin(i / FRAMES * 2 * math.pi)) * 6
        d.polygon([P(50, 24 + y), P(72, 48 + y), P(58, 48 + y), P(58, 74 + y), P(42, 74 + y), P(42, 48 + y),
                   P(28, 48 + y)], fill=c)
        frames.append(finish(im))
    save("priority", frames)


def alert():
    c, t = COL["red"]
    frames = []
    for i in range(FRAMES):
        im, d = canvas(t)
        circle(d, 50, 50, 26, fill=(255, 255, 255), outline=c, width=5 * SS)
        for h in range(12):
            a = h * math.pi / 6
            line(d, [(50 + 21 * math.cos(a), 50 + 21 * math.sin(a)), (50 + 23 * math.cos(a), 50 + 23 * math.sin(a))],
                 2.2, c)
        a = -math.pi / 2 + i / FRAMES * 2 * math.pi
        line(d, [(50, 50), (50 + 17 * math.cos(a), 50 + 17 * math.sin(a))], 3.5, c)
        line(d, [(50, 50), (50, 39)], 4.5, c)
        circle(d, 50, 50, 3.5, fill=c)
        frames.append(finish(im))
    save("alert", frames)


if __name__ == "__main__":
    for fn in (received, bell, assigned, working, question, reply, resolved, reopened, closed, priority, alert):
        fn()
