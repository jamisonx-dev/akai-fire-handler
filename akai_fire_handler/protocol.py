"""
akai_fire_handler.protocol -- the Akai Fire wire protocol, as pure data + math.

Nothing in this module does any I/O. It has no third-party dependencies (no
mido, no Pillow) -- only the standard library. That is deliberate: this is the
correctness-critical core, and it can be unit-tested byte-for-byte on any
machine with no hardware and no audio/graphics stack attached.

PROVENANCE
==========
Every constant and byte layout here is [measured] -- captured on a physical
Akai Fire, not read off a spec sheet -- with one cited exception:

  * The 128x64 OLED bit-remap (`BITMUTATE`, `plot`) is the reverse-engineering
    published by SEGGER ("Decoding the Akai Fire", blog.segger.com, part 3).
    It is [third-party-measured] and additionally [confirmed] here: this exact
    table has driven a physical Fire OLED in continuous daily use for months.

The pad/button/dial input map and the pad-LED SysEx were captured on-device.

SysEx framing note
------------------
The byte sequences returned by the *_sysex() builders below are the payload
that sits BETWEEN the F0 (start) and F7 (end) status bytes -- i.e. what most
MIDI libraries (mido included) want when you hand them `data=`. The leading
`0x47 0x7F 0x43` is Akai's manufacturer/device header; the next byte is the
command (0x0E = OLED bitmap, 0x65 = pad LEDs); then a 2-byte big-endian,
7-bit-per-byte length; then the command payload.
"""

# --------------------------------------------------------------------------- #
# Hardware geometry & input map  [measured -- on-device]                       #
# --------------------------------------------------------------------------- #

OLED_W, OLED_H = 128, 64

PAD_NOTE_BASE = 54            # top-left pad
PAD_NOTE_MAX = 117           # bottom-right pad
N_ROWS, N_COLS = 4, 16       # 64 pads, row-major

# The four endless knobs above the pads. control_change; value is a relative
# (two's-complement) delta -- see decode_relative(). The map value is the
# 0-based knob index (0 = leftmost).
DIAL_CC = {16: 0, 17: 1, 18: 2, 19: 3}
# The same four knobs are touch-sensitive; touching one emits a note_on.
DIAL_TOUCH_NOTE = {16, 17, 18, 19}

# The SELECT encoder (top-right). Turn = relative CC; press = note_on 25.
SELECT_CC = 118

# Every non-pad button, by note number. [measured -- on-device]
BUTTON_NOTE = {
    "STEP": 44, "NOTE": 45, "DRUM": 46, "PERFORM": 47,
    "SHIFT": 48, "ALT": 49, "PAT_SONG": 50,
    "PLAY": 51, "STOP": 52, "REC": 53,
    "PATTERN_UP": 31, "PATTERN_DOWN": 32, "BROWSER": 33,
    "GRID_LEFT": 34, "GRID_RIGHT": 35,
    "SELECT_PRESS": 25, "MODE": 26,
    "MUTE1": 36, "MUTE2": 37, "MUTE3": 38, "MUTE4": 39,
}
# note -> button name (inverse of BUTTON_NOTE)
NOTE_BUTTON = {v: k for k, v in BUTTON_NOTE.items()}

# The four MUTE buttons double as row selectors; map note -> row index.
MUTE_ROW_NOTE = {36: 0, 37: 1, 38: 2, 39: 3}


# --------------------------------------------------------------------------- #
# Pure helpers  [measured -- on-device]                                        #
# --------------------------------------------------------------------------- #

def pad_index(row, col):
    """(row, col) -> 0..63 pad index, row-major."""
    return row * N_COLS + col


def note_to_rc(note):
    """Pad note number (54..117) -> (row, col)."""
    i = note - PAD_NOTE_BASE
    return i // N_COLS, i % N_COLS


def decode_relative(value):
    """A Fire endless-knob CC value -> signed delta.

    The knobs send 1..63 for clockwise (+1..+63) and 127..65 for
    counter-clockwise (-1..-63) as a 7-bit two's-complement number.
    """
    return value if value < 64 else value - 128


def hsv(h, s=1.0, v=0.7):
    """HSV (h,s,v in 0..1) -> (r, g, b) each 0..127, ready for a pad LED.

    Transcribed verbatim from the engine that drives the Fire's LED effects.
    """
    import math  # noqa: F401  (kept to mirror the source; not strictly needed)
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    p, q, t_ = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    rr, gg, bb = [(v, t_, p), (q, v, p), (p, v, t_),
                  (p, q, v), (t_, p, v), (v, p, q)][i % 6]
    return int(rr * 127), int(gg * 127), int(bb * 127)


# --------------------------------------------------------------------------- #
# Input classification (pure)                                                  #
# --------------------------------------------------------------------------- #
# These take the raw pieces of a MIDI message (not a mido object) so they can
# be tested with no dependencies. device.py feeds them mido message fields.

def classify_note(note):
    """Classify a note_on/note_off's note number.

    Returns one of:
        ("pad", row, col)
        ("dial_touch", knob_index)
        ("mute", row)
        ("button", name)
        (None,)                 # unrecognised
    """
    if PAD_NOTE_BASE <= note <= PAD_NOTE_MAX:
        r, c = note_to_rc(note)
        return ("pad", r, c)
    if note in DIAL_TOUCH_NOTE:
        return ("dial_touch", DIAL_CC.get(note, 0))
    if note in MUTE_ROW_NOTE:
        return ("mute", MUTE_ROW_NOTE[note])
    if note in NOTE_BUTTON:
        return ("button", NOTE_BUTTON[note])
    return (None,)


def classify_cc(control, value):
    """Classify a control_change. Returns one of:

        ("dial", knob_index, signed_delta)
        ("select", signed_delta)
        (None,)
    """
    if control in DIAL_CC:
        return ("dial", DIAL_CC[control], decode_relative(value))
    if control == SELECT_CC:
        return ("select", decode_relative(value))
    return (None,)


def route_event(mtype, note=None, velocity=0, control=None, value=0):
    """Map a raw MIDI event to (callback_name, args_tuple).

    This is the single, pure routing table shared by the high-level device
    wrapper. Keeping it here -- with no mido dependency -- means the full
    input dispatch can be unit-tested off-hardware, so a callback can never
    drift out of sync with what classify_note/classify_cc return.

    Returns (None, ()) for anything unrecognised.
    """
    if mtype == "note_on" and velocity > 0:
        k = classify_note(note)
        if k[0] == "pad":
            return ("on_pad", (k[1], k[2], velocity))
        if k[0] == "dial_touch":
            return ("on_dial_touch", (k[1],))
        if k[0] == "mute":
            return ("on_mute", (k[1],))
        if k[0] == "button":
            if k[1] == "SELECT_PRESS":
                return ("on_select_press", ())
            return ("on_button", (k[1],))
    elif mtype == "note_off" or (mtype == "note_on" and velocity == 0):
        k = classify_note(note)
        if k[0] == "pad":
            return ("on_pad_release", (k[1], k[2]))
        if k[0] == "button" and k[1] != "SELECT_PRESS":
            return ("on_button_release", (k[1],))
    elif mtype == "control_change":
        k = classify_cc(control, value)
        if k[0] == "dial":
            return ("on_dial", (k[1], k[2]))
        if k[0] == "select":
            return ("on_select", (k[1],))
    return (None, ())


# --------------------------------------------------------------------------- #
# Pad-LED SysEx  (command 0x65)  [measured -- on-device]                       #
# --------------------------------------------------------------------------- #

def pad_leds_sysex(cells):
    """Build the pad-LED SysEx payload for a list of cells.

    cells: iterable of (index, r, g, b) where index is 0..63 and r/g/b are
           0..127. Only the pads you pass are changed; others keep their state.

    Returns a list[int] of the data BETWEEN F0 and F7.
    """
    payload = []
    for idx, r, g, b in cells:
        payload += [idx & 0x3F, r & 0x7F, g & 0x7F, b & 0x7F]
    n = len(payload)
    return [0x47, 0x7F, 0x43, 0x65, (n >> 7) & 0x7F, n & 0x7F] + payload


# --------------------------------------------------------------------------- #
# OLED bitmap  (command 0x0E)                                                  #
# --------------------------------------------------------------------------- #
# SEGGER _aBitMutate[8][7]: reference bit number for each (Y%8, X%7) cell.
# [third-party-measured: blog.segger.com/decoding-the-akai-fire-part-3;
#  confirmed by continuous use on hardware]
BITMUTATE = (
    (13, 19, 25, 31, 37, 43, 49),
    (0, 20, 26, 32, 38, 44, 50),
    (1, 7, 27, 33, 39, 45, 51),
    (2, 8, 14, 34, 40, 46, 52),
    (3, 9, 15, 21, 41, 47, 53),
    (4, 10, 16, 22, 28, 48, 54),
    (5, 11, 17, 23, 29, 35, 55),
    (6, 12, 18, 24, 30, 36, 42),
)

OLED_PAYLOAD_LEN = 1175       # 4-byte band/column header + packed pixels


def new_oled_buffer():
    """A blank 1175-byte OLED payload whose header selects the whole panel."""
    buf = bytearray(OLED_PAYLOAD_LEN)
    buf[0] = 0x00   # start band
    buf[1] = 0x07   # end band  (8 bands of 8px = full height)
    buf[2] = 0x00   # start column
    buf[3] = 0x7F   # end column (full width)
    return buf


def plot(buf, x, y, on=1):
    """Set/clear one pixel in an OLED buffer via the SEGGER remap."""
    if 0 <= x < OLED_W and 0 <= y < OLED_H:
        X = x + 128 * (y // 8)      # unwind 128x64 -> 1024x8
        Y = y % 8
        rb = BITMUTATE[Y][X % 7]
        idx = 4 + (X // 7) * 8 + rb // 7
        bit = 1 << (rb % 7)
        if on:
            buf[idx] |= bit
        else:
            buf[idx] &= ~bit


def oled_buffer_to_sysex(buf):
    """Wrap a 1175-byte OLED payload as the SysEx data between F0 and F7."""
    n = len(buf)
    return [0x47, 0x7F, 0x43, 0x0E, (n >> 7) & 0x7F, n & 0x7F] + list(buf)
