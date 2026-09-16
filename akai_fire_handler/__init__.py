"""
akai_fire_handler -- a Python library for the Akai Fire controller.

Full control of the 4x16 RGB pad grid, the 128x64 OLED, and all input
(pads, four endless knobs, the SELECT encoder, and every button), over MIDI.

Quick start:

    from akai_fire_handler import AkaiFire
    fire = AkaiFire()
    fire.set_pad(0, 0, 127, 0, 0)
    fire.oled_text("hello", "akai fire")
    fire.on_pad = lambda r, c, v: fire.set_pad(r, c, 0, 127, 0)
    fire.run()

The `protocol` submodule holds the pure wire format (constants + SysEx builders
+ decoders) with no I/O and no third-party dependencies -- import it directly
if you want to speak to the Fire through your own MIDI stack.
"""

from . import protocol, oled
from .device import AkaiFire, find_fire
from .protocol import (
    pad_index, note_to_rc, decode_relative, hsv,
    classify_note, classify_cc,
    BUTTON_NOTE, NOTE_BUTTON, DIAL_CC, SELECT_CC,
    N_ROWS, N_COLS, OLED_W, OLED_H,
)

__version__ = "0.1.0"

__all__ = [
    "AkaiFire", "find_fire", "protocol", "oled",
    "pad_index", "note_to_rc", "decode_relative", "hsv",
    "classify_note", "classify_cc",
    "BUTTON_NOTE", "NOTE_BUTTON", "DIAL_CC", "SELECT_CC",
    "N_ROWS", "N_COLS", "OLED_W", "OLED_H",
]
