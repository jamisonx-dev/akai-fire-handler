"""
Correctness tests for akai_fire_handler.protocol -- the wire format, proven byte for
byte with no hardware, no mido, and no Pillow.

Run with pytest (`python -m pytest`) or directly (`python tests/test_protocol.py`).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from akai_fire_handler import protocol as P  # noqa: E402


# --- pad index <-> (row, col) --------------------------------------------- #

def test_pad_index_roundtrip():
    for row in range(P.N_ROWS):
        for col in range(P.N_COLS):
            idx = P.pad_index(row, col)
            note = P.PAD_NOTE_BASE + idx
            assert P.note_to_rc(note) == (row, col)


def test_pad_corners():
    assert P.note_to_rc(P.PAD_NOTE_BASE) == (0, 0)
    assert P.note_to_rc(P.PAD_NOTE_MAX) == (3, 15)
    assert P.pad_index(0, 0) == 0
    assert P.pad_index(3, 15) == 63


# --- relative-encoder decode ---------------------------------------------- #

def test_decode_relative():
    assert P.decode_relative(0) == 0
    assert P.decode_relative(1) == 1
    assert P.decode_relative(63) == 63
    assert P.decode_relative(64) == -64
    assert P.decode_relative(65) == -63
    assert P.decode_relative(127) == -1


# --- input classification ------------------------------------------------- #

def test_classify_note_pad():
    assert P.classify_note(54) == ("pad", 0, 0)
    assert P.classify_note(117) == ("pad", 3, 15)


def test_classify_note_button():
    assert P.classify_note(51) == ("button", "PLAY")
    assert P.classify_note(48) == ("button", "SHIFT")
    assert P.classify_note(25) == ("button", "SELECT_PRESS")


def test_classify_note_dial_touch_and_mute():
    assert P.classify_note(16) == ("dial_touch", 0)
    assert P.classify_note(19) == ("dial_touch", 3)
    assert P.classify_note(36) == ("mute", 0)
    assert P.classify_note(39) == ("mute", 3)


def test_classify_note_unknown():
    assert P.classify_note(0) == (None,)


def test_classify_cc():
    assert P.classify_cc(16, 1) == ("dial", 0, 1)
    assert P.classify_cc(19, 127) == ("dial", 3, -1)
    assert P.classify_cc(118, 1) == ("select", 1)
    assert P.classify_cc(118, 127) == ("select", -1)
    assert P.classify_cc(7, 64) == (None,)


# --- event routing (pure dispatch table) ---------------------------------- #

def test_route_pad_press_and_release():
    assert P.route_event("note_on", note=54, velocity=100) == ("on_pad", (0, 0, 100))
    assert P.route_event("note_off", note=54) == ("on_pad_release", (0, 0))
    # note_on with velocity 0 is a release
    assert P.route_event("note_on", note=117, velocity=0) == ("on_pad_release", (3, 15))


def test_route_buttons():
    assert P.route_event("note_on", note=51, velocity=127) == ("on_button", ("PLAY",))
    assert P.route_event("note_off", note=51) == ("on_button_release", ("PLAY",))
    # SELECT press routes to its own callback, not on_button
    assert P.route_event("note_on", note=25, velocity=127) == ("on_select_press", ())
    # ...and its release is not a button_release
    assert P.route_event("note_off", note=25) == (None, ())


def test_route_mute_and_dial_touch():
    assert P.route_event("note_on", note=36, velocity=127) == ("on_mute", (0,))
    assert P.route_event("note_on", note=16, velocity=127) == ("on_dial_touch", (0,))


def test_route_dial_turn():
    assert P.route_event("control_change", control=16, value=1) == ("on_dial", (0, 1))
    assert P.route_event("control_change", control=19, value=127) == ("on_dial", (3, -1))


def test_route_select_turn_regression():
    # Regression: on_select must receive the signed delta as its ONLY arg.
    # This is the case a real encoder twist exposed (classify_cc returns a
    # 2-tuple for select; an earlier consumer wrongly read index 2).
    assert P.route_event("control_change", control=118, value=1) == ("on_select", (1,))
    assert P.route_event("control_change", control=118, value=127) == ("on_select", (-1,))


def test_route_unknown():
    assert P.route_event("control_change", control=7, value=64) == (None, ())
    assert P.route_event("note_on", note=0, velocity=100) == (None, ())
    assert P.route_event("clock") == (None, ())


# --- pad-LED SysEx (command 0x65) ----------------------------------------- #

def test_pad_leds_sysex_one_cell():
    data = P.pad_leds_sysex([(0, 127, 0, 0)])
    assert data == [0x47, 0x7F, 0x43, 0x65, 0, 4, 0, 127, 0, 0]


def test_pad_leds_sysex_masks_7bit_and_index():
    # index masked to 6 bits (0x3F), colours to 7 bits (0x7F)
    data = P.pad_leds_sysex([(64, 200, 130, 255)])
    assert data[6:] == [64 & 0x3F, 200 & 0x7F, 130 & 0x7F, 255 & 0x7F]
    assert data[6:] == [0, 72, 2, 127]


def test_pad_leds_sysex_length_field():
    # 64 cells -> 256 payload bytes -> length hi=2, lo=0 (7-bit big-endian)
    data = P.pad_leds_sysex([(i, 0, 0, 0) for i in range(64)])
    assert data[:4] == [0x47, 0x7F, 0x43, 0x65]
    assert data[4] == (256 >> 7) & 0x7F == 2
    assert data[5] == 256 & 0x7F == 0
    assert len(data) == 6 + 256


# --- OLED bitmap (command 0x0E) ------------------------------------------- #

def test_new_oled_buffer_header():
    buf = P.new_oled_buffer()
    assert len(buf) == P.OLED_PAYLOAD_LEN == 1175
    assert list(buf[:4]) == [0x00, 0x07, 0x00, 0x7F]
    assert all(b == 0 for b in buf[4:])


def test_plot_top_left_pixel():
    # Pixel (0,0): X=0,Y=0, rb=BITMUTATE[0][0]=13, idx=4+0+13//7=5, bit=1<<6=64.
    buf = P.new_oled_buffer()
    P.plot(buf, 0, 0, 1)
    assert buf[5] == 64
    assert sum(buf[4:]) == 64  # nothing else set


def test_plot_clear():
    buf = P.new_oled_buffer()
    P.plot(buf, 0, 0, 1)
    P.plot(buf, 0, 0, 0)
    assert sum(buf[4:]) == 0


def test_plot_out_of_bounds_is_noop():
    buf = P.new_oled_buffer()
    P.plot(buf, -1, 0, 1)
    P.plot(buf, 0, 64, 1)
    P.plot(buf, 128, 0, 1)
    assert sum(buf[4:]) == 0


def test_oled_buffer_to_sysex_framing():
    buf = P.new_oled_buffer()
    data = P.oled_buffer_to_sysex(buf)
    assert data[:4] == [0x47, 0x7F, 0x43, 0x0E]
    # length 1175 -> hi = 1175>>7 = 9, lo = 1175 & 0x7F = 23
    assert data[4] == 9
    assert data[5] == 23
    assert len(data) == 6 + 1175


# --- colour helper -------------------------------------------------------- #

def test_hsv_range_and_primaries():
    for h in (0.0, 0.25, 0.5, 0.75, 0.999):
        r, g, b = P.hsv(h, 1.0, 1.0)
        assert 0 <= r <= 127 and 0 <= g <= 127 and 0 <= b <= 127
    # hue 0 at full sat/val is pure red
    assert P.hsv(0.0, 1.0, 1.0) == (127, 0, 0)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
