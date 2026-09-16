"""
akai_fire.oled -- render text/graphics to the Akai Fire's 128x64 OLED.

This is the battle-tested rendering path from the reference instrument. It:

  * rasterises text with Pillow into a 1-bit 128x64 image,
  * packs it through the SEGGER pixel remap (see protocol.plot),
  * sends it as a single SysEx frame, and
  * coalesces rapid updates onto a background worker so a fast stream of
    frames (e.g. a knob sweep updating a readout) can never (a) blink the
    panel or (b) starve your other threads under CPython's GIL.

The render + pack is ~7 ms of GIL-holding pure Python per frame on a Pi 4.
show_lines() therefore never renders on the calling thread -- it stores the
latest draw list and wakes one daemon worker that renders at most once per
MIN_INTERVAL, always painting a trailing frame. show_lines_now() is the
synchronous escape hatch for the rare frame that must be on the glass before
the call returns (a boot banner, say).

Fonts: DejaVu Sans Mono is used if found (it is monospace at every size, which
lets max_chars()/fits() compute line budgets as pure arithmetic with no font
stack -- handy for testing off-hardware). Call set_font_paths() to point at
your own TTFs; otherwise Pillow's built-in default is the fallback.
"""

import threading
import time

from . import protocol

OLED_W, OLED_H = protocol.OLED_W, protocol.OLED_H

# One serialization point for EVERY MIDI write to the Fire. The OLED frame and
# the pad-LED grid are BIG SysEx messages; if they interleave on the wire
# (different threads, maybe different ports) the device draws a corrupted OLED
# frame. Both senders take THIS lock so a frame is always handed over whole.
# device.AkaiFire uses it for pad writes too.
IO_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Fonts                                                                        #
# --------------------------------------------------------------------------- #
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
_FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
_font_cache = {}


def set_font_paths(regular=None, bold=None):
    """Override the TTF paths used for rendering. Clears the font cache."""
    global _FONT_PATH, _FONT_PATH_BOLD
    if regular is not None:
        _FONT_PATH = regular
    if bold is not None:
        _FONT_PATH_BOLD = bold
    _font_cache.clear()


def _get_font(bold=False, size=9):
    key = (bold, size, _FONT_PATH_BOLD if bold else _FONT_PATH)
    if key not in _font_cache:
        from PIL import ImageFont
        path = _FONT_PATH_BOLD if bold else _FONT_PATH
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except Exception:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# --------------------------------------------------------------------------- #
# Text budget (pure arithmetic -- no PIL needed)                              #
# --------------------------------------------------------------------------- #
# DejaVuSansMono advance width is a fixed ~0.602 em at every size, so how many
# characters fit on a line is arithmetic. This lets line-length assertions run
# off-hardware with no font stack. Measured budgets at x=2 on the 128px panel:
# 16 / 14 / 10 / 5 chars for scales 1..4.
_SCALE_PT = {1: 13, 2: 14, 3: 20, 4: 36}
_ADV_EM = 0.602


def scale_pt(scale):
    """Point size render() uses for a given scale."""
    if scale <= 1:
        return _SCALE_PT[1]
    if scale == 2:
        return _SCALE_PT[2]
    if scale == 3:
        return _SCALE_PT[3]
    return _SCALE_PT[4]


def char_w(scale):
    """Advance width in pixels of one character at this scale."""
    return _ADV_EM * scale_pt(scale)


def max_chars(scale=1, x=2):
    """How many characters fit from x to the right edge at this scale."""
    return max(0, int((OLED_W - x) // char_w(scale)))


def line_h(scale):
    """Vertical space one line occupies below its y, descenders included."""
    return scale_pt(scale) + 3


def fits(text, x=2, scale=1):
    """True if text renders fully inside the panel horizontally."""
    return len(text) <= max_chars(scale, x)


def fits_box(text, x=2, y=0, scale=1):
    """True if text fits horizontally AND vertically at (x, y)."""
    return fits(text, x, scale) and 0 <= y and y + line_h(scale) <= OLED_H


# Every truncation fit() performs, as (why, text, budget). Useful for a test to
# read + clear -- a fit() with no `why` means a fixed string (or a value) is
# being silently clipped, which should be fixed by writing the line shorter.
TRUNCATIONS = []


def fit(text, x=2, scale=1, why=None):
    """Truncate text to what will actually render on the panel."""
    budget = max_chars(scale, x)
    if len(text) > budget:
        TRUNCATIONS.append((why, text, budget))
    return text[:budget]


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #

def render(draws):
    """draws: list of (text, x, y, scale). Returns a 128x64 mode-'1' image.

    scale 1 -> small 13px, 2 -> bold 14px, 3 -> bold 20px, 4 -> bold 36px.
    """
    from PIL import Image, ImageDraw
    img = Image.new("1", (OLED_W, OLED_H), 0)
    d = ImageDraw.Draw(img)
    for text, x, y, scale in draws:
        if scale <= 1:
            font = _get_font(bold=False, size=13)
        elif scale == 2:
            font = _get_font(bold=True, size=14)
        elif scale == 3:
            font = _get_font(bold=True, size=20)
        else:
            font = _get_font(bold=True, size=36)
        d.text((x, y), text, fill=1, font=font)
    return img


def image_to_buf(img):
    """PIL 128x64 image (nonzero pixel = lit) -> a 1175-byte OLED payload."""
    buf = protocol.new_oled_buffer()
    px = img.load()
    for y in range(OLED_H):
        for x in range(OLED_W):
            if px[x, y]:
                protocol.plot(buf, x, y, 1)
    return buf


# --------------------------------------------------------------------------- #
# Sending                                                                      #
# --------------------------------------------------------------------------- #

def send_image(img, out, _last={}, _last_t={}):
    """Render `img` to a mido output port `out` (an opened mido output).

    De-duplicates: an identical frame sent within 20 ms is skipped, so a
    repeated readout does not blink the panel.
    """
    import mido
    buf = image_to_buf(img)
    key = id(out)
    now = time.monotonic()
    if _last.get(key) == buf and (now - _last_t.get(key, 0)) < 0.020:
        return
    with IO_LOCK:
        out.send(mido.Message("sysex", data=protocol.oled_buffer_to_sysex(buf)))
        _last[key] = bytes(buf)
        _last_t[key] = now


# --------------------------------------------------------------------------- #
# Push coalescer                                                               #
# --------------------------------------------------------------------------- #
MIN_INTERVAL = 0.04            # cap actual OLED pushes to ~25 fps
_oled_lock = threading.Lock()
_oled_pending = {}             # out -> latest draws awaiting render
_oled_last_t = {}             # id(out) -> monotonic of last actual push
_oled_wake = threading.Event()
_oled_worker_started = False


def _oled_worker():
    while True:
        _oled_wake.wait()
        _oled_wake.clear()
        while True:
            with _oled_lock:
                if not _oled_pending:
                    break
                out = next(iter(_oled_pending))
                last = _oled_last_t.get(id(out), 0.0)
            wait = last + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)   # let further updates coalesce into pending
            with _oled_lock:
                draws = _oled_pending.pop(out, None)
                _oled_last_t[id(out)] = time.monotonic()
            if draws is not None:
                try:
                    send_image(render(draws), out)
                except Exception:
                    pass


def _ensure_oled_worker():
    global _oled_worker_started
    if _oled_worker_started:
        return
    with _oled_lock:
        if _oled_worker_started:
            return
        threading.Thread(target=_oled_worker, name="akai-fire-oled",
                         daemon=True).start()
        _oled_worker_started = True


def show_lines(draws, out):
    """Queue a frame for the OLED on mido output `out`. Non-blocking: the
    render + SysEx push happen on the coalescing worker, at most once per
    MIN_INTERVAL, latest draws winning."""
    _ensure_oled_worker()
    with _oled_lock:
        _oled_pending[out] = draws
    _oled_wake.set()


def show_lines_now(draws, out):
    """Synchronous render + push, bypassing the coalescer."""
    send_image(render(draws), out)
