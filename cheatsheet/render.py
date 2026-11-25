#!/usr/bin/env python3
"""
Draw printable cheatsheets from the ZMK keymap.

    python3 cheatsheet/render.py config/lily58.keymap keymap-drawer/silakka54_layout.json cheatsheet

Writes to the output folder:
  silakka54-cheatsheet.pdf            A4 landscape: Symbols, Nav (left half), Numpad (right half)
  silakka54-cheatsheet-portrait.pdf   A4 portrait: Base, Symbols, Nav, Numpad
  layers/N-<layer>.png                one image per layer

Needs Python 3 and rsvg-convert (librsvg). Fonts: Inter, DejaVu Sans Mono.
Run automatically by .github/workflows/draw-keymaps.yml when the keymap changes.
"""
import json
import math
import re
import subprocess
import sys
from html import escape
from pathlib import Path

# ============================================================ settings for this keyboard
LAYER_TITLES = {  # keymap layer node name -> title (unlisted layers use their node name)
    "base": "Base", "hrm_off": "HRM off", "symbols": "Symbols",
    "numpad": "Numpad", "nav": "Nav", "control": "Control",
}
LAYER_NOTES = {  # extra text after the title (added after any "hold ..." text worked out from the keymap)
    "base": "home row mods on",
    "hrm_off": "or press F + J together",
}
SPC_TOP, SPC_LEFT, SPC_RIGHT, SPC_BASE = "symbols", "nav", "numpad", "base"
HELP = "Toggle HRM with F+J (chord) or Tab (held)"
THUMBS = set(range(50, 58))  # key positions of the thumb row (lily58 shield order)
ABSENT = {42, 43, 53, 54}    # lily58 positions the silakka54 doesn't have (also hidden in keymap_drawer.config.yaml)
CENTRE_X = 7.0               # x (in key units) between the two halves of the layout file
SPC_GAP_U = 0.9              # gap between halves on the cheatsheet when thumbs are left out

KEYS = {
    "GRAVE": "`", "EQUAL": "=", "MINUS": "-", "TAB": "Tab", "ESC": "Esc", "ESCAPE": "Esc", "SQT": "'",
    "SINGLE_QUOTE": "'", "APOS": "'", "DQT": '"', "SEMICOLON": ";", "SEMI": ";", "COLON": ":",
    "COMMA": ",", "DOT": ".", "PERIOD": ".", "FSLH": "/", "SLASH": "/", "QUESTION": "?", "QMARK": "?",
    "LSHFT": "Shift", "RSHFT": "Shift", "LSHIFT": "Shift", "RSHIFT": "Shift",
    "LALT": "Alt", "RALT": "Alt", "LGUI": "GUI", "RGUI": "GUI", "LCTRL": "Ctrl", "RCTRL": "Ctrl",
    "SPACE": "Space", "BACKSPACE": "Bksp", "BSPC": "Bksp", "ENTER": "Enter", "RET": "Enter",
    "DELETE": "Del", "DEL": "Del", "CAPSLOCK": "Caps\nLock", "CAPS": "Caps\nLock", "INSERT": "Ins",
    "EXCLAMATION": "!", "EXCL": "!", "AT_SIGN": "@", "AT": "@", "HASH": "#", "POUND": "#",
    "DOLLAR": "$", "DLLR": "$", "PERCENT": "%", "PRCNT": "%", "CARET": "^", "AMPERSAND": "&", "AMPS": "&",
    "ASTRK": "*", "ASTERISK": "*", "STAR": "*",
    "LEFT_PARENTHESIS": "(", "LPAR": "(", "RIGHT_PARENTHESIS": ")", "RPAR": ")",
    "LEFT_BRACKET": "[", "LBKT": "[", "RIGHT_BRACKET": "]", "RBKT": "]",
    "LEFT_BRACE": "{", "LBRC": "{", "RIGHT_BRACE": "}", "RBRC": "}",
    "LESS_THAN": "<", "LT": "<", "GREATER_THAN": ">", "GT": ">",
    "TILDE": "~", "PIPE": "|", "BACKSLASH": "\\", "BSLH": "\\", "UNDER": "_", "UNDERSCORE": "_", "PLUS": "+",
    "NUMBER_0": "0",
    "HOME": "Home", "END": "End", "PG_UP": "PgUp", "PAGE_UP": "PgUp", "PG_DN": "PgDn", "PAGE_DOWN": "PgDn",
    "UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→", "UP_ARROW": "↑", "DOWN_ARROW": "↓",
    "LEFT_ARROW": "←", "RIGHT_ARROW": "→",
    "K_BACK": "Back", "K_FORWARD": "Fwd",
    "LG(MINUS)": "Zoom\n−", "LG(EQUAL)": "Zoom\n+",
    "C_BRIGHTNESS_DEC": "Bright\n−", "C_BRIGHTNESS_INC": "Bright\n+",
    "C_MUTE": "Mute", "K_MUTE": "Mute", "C_VOL_DN": "Vol −", "K_VOLUME_DOWN": "Vol −",
    "C_VOL_UP": "Vol +", "K_VOLUME_UP": "Vol +", "C_PP": "Play\nPause", "K_PLAY_PAUSE": "Play\nPause",
    "C_NEXT": "Next", "C_PREV": "Prev",
}
MODS = {"LEFT_GUI": "GUI", "RIGHT_GUI": "GUI", "LGUI": "GUI", "RGUI": "GUI",
        "LCTRL": "Ctrl", "RCTRL": "Ctrl", "LEFT_CONTROL": "Ctrl", "RIGHT_CONTROL": "Ctrl",
        "LEFT_ALT": "Alt", "RIGHT_ALT": "Alt", "LALT": "Alt", "RALT": "Alt",
        "LEFT_SHIFT": "Shift", "RIGHT_SHIFT": "Shift", "LSHFT": "Shift", "RSHFT": "Shift", "LSHIFT": "Shift"}
RAW = {  # whole bindings -> (tap legend, small legend)
    "&type_uname": ("User-\nname", "macro"),
    "&caps_word": ("Caps\nWord", ""),
    "&msc SCRL_UP": ("Scroll\n↑", ""), "&msc SCRL_DOWN": ("Scroll\n↓", ""),
    "&mkp LCLK": ("Left\nclick", ""), "&mkp RCLK": ("Right\nclick", ""), "&mkp MCLK": ("Mid\nclick", ""),
    "&bt BT_CLR": ("BT\nclear", ""), "&bt BT_CLR_ALL": ("BT clr\nall", ""),
}

# ============================================================ parse keymap
KEYMAP, LAYOUT_JSON, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
(OUT / "layers").mkdir(parents=True, exist_ok=True)

src = re.sub(r"//[^\n]*", "", KEYMAP.read_text())
src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)

# hold-tap behaviors: name -> [hold behavior, tap behavior]
HOLD_TAPS = {"&lt": ["&mo", "&kp"], "&mt": ["&kp", "&kp"]}
for m in re.finditer(r"(\w+)\s*:\s*\w+\s*\{[^{}]*?compatible\s*=\s*\"zmk,behavior-hold-tap\"[^{}]*?\}", src, re.S):
    b = re.search(r"bindings\s*=\s*(<[^;]*);", m.group(0))
    if b:
        HOLD_TAPS["&" + m.group(1)] = re.findall(r"&\w+", b.group(1))

km = src[src.index('compatible = "zmk,keymap"'):]
layers = []
for m in re.finditer(r"(\w+)\s*\{([^{}]*?)bindings\s*=\s*<(.*?)>;", km, re.S):
    name, _, body = m.groups()
    binds = [b.split() for b in re.findall(r"&\w+(?:\s+[^&\s]+)*", body)]
    layers.append((name, binds))
NAMES = [n for n, _ in layers]
NKEYS = len(layers[0][1])
assert all(len(b) == NKEYS for _, b in layers), "layers have different key counts"
L = {n: i for i, n in enumerate(NAMES)}
TITLE = {i: LAYER_TITLES.get(n, n) for i, n in enumerate(NAMES)}
print("layers:", NAMES, "keys:", NKEYS)

# ============================================================ physical layout
qmk = json.loads(LAYOUT_JSON.read_text())["layouts"]
KEYS_PHYS = next(iter(qmk.values()))["layout"]
assert len(KEYS_PHYS) == NKEYS, f"layout has {len(KEYS_PHYS)} keys, keymap has {NKEYS}"
PRESENT = [p for p in range(NKEYS) if p not in ABSENT]


def key_geom(p):
    k = KEYS_PHYS[p]
    x, y, w, h = k["x"], k["y"], k.get("w", 1.0), k.get("h", 1.0)
    r = k.get("r", 0.0)
    rx, ry = k.get("rx", x), k.get("ry", y)
    return x, y, w, h, r, rx, ry


def corners(p, dx=0.0):
    x, y, w, h, r, rx, ry = key_geom(p)
    pts = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    a = math.radians(r)
    out = []
    for px, py in pts:
        qx, qy = px - rx, py - ry
        out.append((rx + qx * math.cos(a) - qy * math.sin(a) + dx, ry + qx * math.sin(a) + qy * math.cos(a)))
    return out


def side(p):
    xs = [c[0] for c in corners(p)]
    return "L" if (min(xs) + max(xs)) / 2 < CENTRE_X else "R"


def bbox(positions, shift):
    pts = [c for p in positions for c in corners(p, shift(p))]
    xs, ys = [c[0] for c in pts], [c[1] for c in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ============================================================ legends
def kp(code):
    if code in KEYS:
        return KEYS[code]
    if re.fullmatch(r"N\d", code) or re.fullmatch(r"NUMBER_\d", code):
        return code[-1]
    if re.fullmatch(r"F\d+", code) or len(code) == 1:
        return code
    m = re.fullmatch(r"(L|R)(S|C|A|G)\((.+)\)", code)
    if m:
        return {"S": "Shift", "C": "Ctrl", "A": "Alt", "G": "GUI"}[m.group(2)] + "+\n" + kp(m.group(3))
    return code.removeprefix("C_").removeprefix("K_").replace("_", " ").title()


def legend(b, li):
    """-> (tap, small text, kind) with kind in trans/none/normal/layer"""
    beh, args = b[0], b[1:]
    raw = " ".join(b)
    if raw in RAW:
        t, h = RAW[raw]
        return t, h, "normal"
    if beh == "&trans":
        return "", "", "trans"
    if beh == "&none":
        return "", "", "none"
    if beh == "&kp":
        return kp(args[0]), "", "normal"
    if beh == "&sk":
        return kp(args[0]), "one-shot", "normal"
    if beh in ("&mo", "&tog", "&to", "&sl"):
        verb = {"&mo": "", "&tog": "Toggle\n", "&to": "To\n", "&sl": "One-shot\n"}[beh]
        return verb + TITLE[int(args[0])], "", "normal"
    if beh == "&bt" and args[0] == "BT_SEL":
        return f"BT {args[1]}", "", "normal"
    if beh in HOLD_TAPS and len(args) == 2:
        hold_b, tap_b = HOLD_TAPS[beh]
        tap = legend([tap_b, args[1]], li)[0]
        if hold_b == "&mo":
            lay = int(args[0])
            return (tap, TITLE[lay], "layer") if lay != li and lay != 0 else (tap, "", "normal")
        if hold_b == "&kp":
            return tap, MODS.get(args[0], kp(args[0])), "normal"
        return tap, legend([hold_b, args[0]], li)[0].replace("\n", " "), "normal"
    return beh.lstrip("&").replace("_", " "), "", "normal"


def layer_holds(target):
    """Keys that activate `target` while held: list of (position, layer it's on), base layer first."""
    found = []
    for li, (_, binds) in enumerate(layers):
        if li == target:
            continue
        for p, b in enumerate(binds):
            beh, args = b[0], b[1:]
            if beh == "&mo" and args and int(args[0]) == target:
                found.append((p, li))
            elif beh in HOLD_TAPS and HOLD_TAPS[beh][0] == "&mo" and len(args) == 2 and int(args[0]) == target:
                found.append((p, li))
        if found:
            return found  # stop at the first (lowest) layer that has one
    return found


def tap_name(p, li=0):
    t = legend(layers[li][1][p], li)[0].replace("\n", " ")
    return "' (quote)" if t == "'" else t


def hold_note(target):
    hs = layer_holds(target)
    extra = LAYER_NOTES.get(NAMES[target], "")
    if not hs:
        return extra
    names = " or ".join(tap_name(p, li) for p, li in hs)
    where = "" if hs[0][1] == 0 else f" on {TITLE[hs[0][1]]}"
    return f"hold {names}{where}" + (f", {extra}" if extra else "")


# ============================================================ drawing
FONT = "Inter, 'DejaVu Sans', sans-serif"
SYMFONT = "'DejaVu Sans Mono', monospace"
INK = "#1d1d1b"
C = {"key": ("#ffffff", "#6b6b66"), "trans": ("#f2f1ec", "#cfcdc4"), "held": ("#2c2c2a", "#2c2c2a"),
     "bracket": ("#eeedfe", "#534ab7")}
HOLD_COL = {"layer": "#0f6e56", "normal": "#5f5e5a"}
BRACKETS = set("()[]{}<>")


def text(cx, cy, s, size, weight, fill):
    if len(s) == 1:  # single glyph on a real baseline: _ sits low, - mid, ` and ' high
        fam = SYMFONT if not s.isalnum() else FONT
        return (f'<text x="{cx:.2f}" y="{cy + 0.36 * size:.2f}" font-family="{fam}" font-size="{size:.2f}" '
                f'font-weight="{weight}" fill="{fill}" text-anchor="middle">{escape(s)}</text>')
    lines = s.split("\n")
    lh = size * 1.12
    y0 = cy - lh * (len(lines) - 1) / 2
    return "".join(
        f'<text x="{cx:.2f}" y="{y0 + i * lh:.2f}" font-family="{FONT}" font-size="{size:.2f}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="middle" dominant-baseline="central">{escape(ln)}</text>'
        for i, ln in enumerate(lines))


def tap_size(tap, u, w):
    longest = max(len(l) for l in tap.split("\n"))
    if longest == 1:
        return (0.46 if tap.isalnum() else 0.56) * u
    size = min(0.27 * u, 0.80 * u * w / (longest * 0.58))
    return min(size, 0.24 * u) if "\n" in tap else size


def draw_key(p, ox, oy, u, dx, li, held=False, styles=None):
    x, y, w, h, r, rx, ry = key_geom(p)
    X, Y, W, H = ox + (x + dx) * u, oy + y * u, w * u, h * u
    tap, hold, kind = legend(layers[li][1][p], li)
    style = "held" if held else (styles or {}).get(tap) or ("trans" if kind == "trans" else "key")
    fill, stroke = C[style]
    pad = 0.05 * u
    s = [f'<rect x="{X + pad:.2f}" y="{Y + pad:.2f}" width="{W - 2 * pad:.2f}" height="{H - 2 * pad:.2f}" '
         f'rx="{0.12 * u:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{0.018 * u:.2f}"/>']
    cx, top = X + W / 2, Y + (H - u) / 2
    if held:
        base_tap = tap_name(p).replace(" (quote)", " quote")
        s.append(text(cx, top + 0.33 * u, "HOLD", 0.19 * u, 700, "#ffffff"))
        s.append(text(cx, top + 0.64 * u, base_tap, (0.34 if len(base_tap) == 1 else 0.2) * u, 700, "#ffffff"))
    elif tap:
        col = "#3c3489" if style == "bracket" else INK
        size = tap_size(tap, u, w) * (0.75 if hold and len(tap) == 1 else 1)
        s.append(text(cx, top + (0.43 if hold else 0.5) * u, tap, size, 600 if len(tap) == 1 else 500, col))
        if hold:
            s.append(text(cx, top + 0.80 * u, hold, 0.17 * u, 600 if kind == "layer" else 500, HOLD_COL[kind]))
    body = "".join(s)
    if r:
        return f'<g transform="rotate({r} {ox + (rx + dx) * u:.2f} {oy + ry * u:.2f})">{body}</g>'
    return body


def board(li, positions, ox, oy, u, shift, held=(), styles=None):
    """Draw `positions` of layer li with the top-left of their bounding box at (ox, oy)."""
    x0, y0, _, _ = bbox(positions, shift)
    return "".join(draw_key(p, ox - x0 * u, oy - y0 * u, u, shift(p), li, p in held, styles)
                   for p in positions if legend(layers[li][1][p], li)[2] != "none" or p in held)


def held_on(target):
    return {p for p, li in layer_holds(target)}


def styles_for(name):
    return {ch: "bracket" for ch in BRACKETS} if name == SPC_TOP else {}


NO_SHIFT = lambda p: 0.0
gap_shift = None  # set below once we know the halves' extents


def legend_bar(x, y, u, items):
    out, cx = [], x
    for label, style in items:
        f, s = C[style]
        out.append(f'<rect x="{cx:.1f}" y="{y:.1f}" width="{0.22*u:.1f}" height="{0.22*u:.1f}" rx="{0.04*u:.1f}" '
                   f'fill="{f}" stroke="{s}" stroke-width="{0.015*u:.2f}"/>')
        out.append(f'<text x="{cx + 0.3*u:.1f}" y="{y + 0.11*u:.1f}" font-family="{FONT}" font-size="{0.16*u:.1f}" '
                   f'fill="{INK}" dominant-baseline="central">{escape(label)}</text>')
        cx += 0.3 * u + len(label) * 0.095 * u + 0.35 * u
    return "".join(out)


def rsvg(svg_path, out_path, fmt=None):
    cmd = ["rsvg-convert", "-o", str(out_path)] + (["-f", fmt] if fmt else []) + [str(svg_path)]
    subprocess.run(cmd, check=True)


# ============================================================ per-layer images
def layer_image(li):
    name = NAMES[li]
    u = 200
    held = held_on(li)
    x0, y0, x1, y1 = bbox(PRESENT, NO_SHIFT)
    W, top = (x1 - x0) * u + 0.6 * u, 1.05 * u
    H = top + (y1 - y0) * u + 0.85 * u
    if li == 0:
        others = []
        for t in range(1, len(NAMES)):
            keys = [tap_name(p) for p, l in layer_holds(t) if l == 0]
            if keys:
                others.append(f"{' or '.join(keys)} for {TITLE[t]}")
        sub = "Hold " + ", ".join(others) if others else ""
    else:
        sub = hold_note(li)
        sub = sub[:1].upper() + sub[1:]
    if NAMES[li] in LAYER_NOTES and li == 0:
        sub = LAYER_NOTES[NAMES[li]].capitalize() + (". " + sub if sub else "")
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             f'<text x="{0.3*u}" y="{0.45*u}" font-family="{FONT}" font-size="{0.3*u}" font-weight="700" fill="{INK}">{escape(TITLE[li])}</text>',
             f'<text x="{0.3*u}" y="{0.82*u}" font-family="{FONT}" font-size="{0.17*u}" fill="#5f5e5a">{escape(sub)}</text>',
             board(li, PRESENT, 0.3 * u, top, u, NO_SHIFT, held, styles_for(name))]
    items = [("Key: big = tap, small = hold", "key")]
    if held:
        items.append(("Key you hold for this layer", "held"))
    if name == SPC_TOP:
        items.append(("Brackets", "bracket"))
    items.append(("Pass-through to base", "trans"))
    parts += [legend_bar(0.3 * u, H - 0.45 * u, u, items), "</svg>"]
    svg = OUT / "layers" / f"{li + 1}-{name.replace('_', '-')}.svg"
    svg.write_text("".join(parts))
    rsvg(svg, svg.with_suffix(".png"))
    svg.unlink()


for li in range(len(NAMES)):
    layer_image(li)
print("wrote layer images")

# ============================================================ one-page cheatsheets (A4, mm)
M, TITLE_H, BOX_PAD, GAP = 7.0, 9.0, 3.5, 3.0
NO_THUMBS = [p for p in PRESENT if p not in THUMBS]
LEFT = [p for p in NO_THUMBS if side(p) == "L"]
RIGHT = [p for p in NO_THUMBS if side(p) == "R"]
_lx1 = bbox(LEFT, NO_SHIFT)[2]
_rx0 = bbox(RIGHT, NO_SHIFT)[0]
_pull = (_rx0 - _lx1) - SPC_GAP_U
gap_shift = lambda p: -_pull if side(p) == "R" else 0.0


def dims(positions, shift):
    x0, y0, x1, y1 = bbox(positions, shift)
    return x1 - x0, y1 - y0


SECT = {
    "base": (PRESENT, NO_SHIFT),
    "top": (NO_THUMBS, gap_shift),
}
HALF_W = max(dims(LEFT, NO_SHIFT)[0], dims(RIGHT, NO_SHIFT)[0])
HALF_H = max(dims(LEFT, NO_SHIFT)[1], dims(RIGHT, NO_SHIFT)[1])


def box(x, y, w, h):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="2" fill="none" stroke="{INK}" stroke-width="0.45"/>'


def title(x, y, main, note=""):
    t = f'<text x="{x:.2f}" y="{y + TITLE_H - 2.6:.2f}" font-family="{FONT}" font-size="5.2" font-weight="700" fill="{INK}">{escape(main)}'
    if note:
        t += f'<tspan dx="3" font-weight="400" fill="#5f5e5a" font-size="4.2">{escape(note)}</tspan>'
    return t + "</text>"


def spc(PW, PH, with_base, fname):
    W, H = PW - 2 * M, PH - 2 * M
    sections = (["base"] if with_base else []) + ["top", "halves"]
    size = {s: dims(*SECT[s]) for s in SECT}
    size["halves"] = (HALF_W, HALF_H)
    fixed = len(sections) * (TITLE_H + 2 * BOX_PAD) + (len(sections) - 1) * GAP
    u_h = (H - fixed) / sum(size[s][1] for s in sections)
    u_full = min([u_h] + [(W - 2 * BOX_PAD) / size[s][0] for s in sections if s != "halves"])
    half_w_limit = ((W - GAP) / 2 - 2 * BOX_PAD) / HALF_W
    u_half = min(u_h, half_w_limit)
    used = fixed + sum(size[s][1] * (u_half if s == "halves" else u_full) for s in sections)
    if H - used > 0.5:  # full-width sections are width-limited: give the spare height to the halves
        u_half = min(u_half + (H - used) / HALF_H, half_w_limit)
        used = fixed + sum(size[s][1] * (u_half if s == "halves" else u_full) for s in sections)
    print(f"{fname}: key size {u_full:.1f} mm, halves {u_half:.1f} mm")
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{PW}mm" height="{PH}mm" viewBox="0 0 {PW} {PH}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>']
    y = M + max(0.0, H - used) / 2
    for i, s in enumerate(sections):
        if s == "halves":
            hw = (W - GAP) / 2
            bh = HALF_H * u_half + 2 * BOX_PAD
            for j, (name, pos) in enumerate(((SPC_LEFT, LEFT), (SPC_RIGHT, RIGHT))):
                li = L[name]
                hand = "left hand" if j == 0 else "right hand"
                bx = M + j * (hw + GAP)
                parts.append(title(bx + 1, y, TITLE[li], f"{hold_note(li)} · {hand}"))
                parts.append(box(bx, y + TITLE_H, hw, bh))
                pw, ph = dims(pos, NO_SHIFT)
                parts.append(board(li, pos, bx + (hw - pw * u_half) / 2, y + TITLE_H + BOX_PAD + (HALF_H - ph) * u_half / 2,
                                   u_half, NO_SHIFT, held_on(li) & set(pos), styles_for(name)))
            y += TITLE_H + bh
        else:
            name = SPC_BASE if s == "base" else SPC_TOP
            li = L[name]
            note = LAYER_NOTES.get(name, "") if li == 0 else hold_note(li)
            parts.append(title(M + 1, y, TITLE[li], note))
            if i == 0:
                parts.append(f'<text x="{M + W - 1:.2f}" y="{y + TITLE_H - 2.6:.2f}" font-family="{FONT}" '
                             f'font-size="3.8" fill="#5f5e5a" text-anchor="end">{escape(HELP)}</text>')
            pos, shift = SECT[s]
            sw, sh = size[s]
            bh = sh * u_full + 2 * BOX_PAD
            parts.append(box(M, y + TITLE_H, W, bh))
            held = held_on(li) & set(pos) if li != 0 else set()
            parts.append(board(li, pos, M + (W - sw * u_full) / 2, y + TITLE_H + BOX_PAD, u_full, shift, held, styles_for(name)))
            y += TITLE_H + bh
        y += GAP
    parts.append("</svg>")
    svg = OUT / f"{fname}.svg"
    svg.write_text("".join(parts))
    rsvg(svg, OUT / f"{fname}.pdf", "pdf")
    svg.unlink()


spc(297.0, 210.0, False, "silakka54-cheatsheet")
spc(210.0, 297.0, True, "silakka54-cheatsheet-portrait")
