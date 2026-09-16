# akai-fire-handler

A clean, dependency-light Python library for the **Akai Fire** controller —
full control of the 4×16 RGB pad grid, the 128×64 OLED, and all input (pads,
the four endless knobs, the SELECT encoder, and every button) over MIDI.

It works on Linux, macOS, and Windows — anywhere `mido` + `python-rtmidi` run.
No FL Studio required.

```python
from akai_fire_handler import AkaiFire

fire = AkaiFire()                       # finds the Fire by its MIDI port name
fire.clear_pads()
fire.set_pad(0, 0, 127, 0, 0)           # top-left pad, red (r, g, b each 0–127)
fire.oled_text("AKAI FIRE", "hello")

fire.on_pad = lambda row, col, vel: fire.set_pad(row, col, 0, 127, 0)
fire.on_button = lambda name: print("button:", name)
fire.run()                              # blocking input loop (Ctrl-C to stop)
```

## Install

```bash
pip install akai-fire-handler
```

Works on Windows, macOS, and Linux. Dependencies — `mido`, `python-rtmidi`
(MIDI I/O), and `Pillow` (OLED text rendering) — install automatically.

Or the latest straight from source:

```bash
pip install git+https://github.com/jamisonx-dev/akai-fire-handler.git
```

## Why this exists

The Akai Fire is a lovely, cheap grid controller, but its protocol is
undocumented by Akai and it's normally locked to FL Studio. The pieces have
been reverse-engineered before (the OLED remap especially — see credits), but
there was no single, tested Python library that does the whole job: OLED
rendering **and** RGB pads **and** input **and** the threading that keeps it
usable in a real application.

This library is extracted from a headless music instrument that has driven a
physical Fire in daily use for months. The wire protocol in
[`akai_fire_handler/protocol.py`](akai_fire_handler/protocol.py) is verified **byte-for-byte**
against that instrument's proven code (8192/8192 OLED pixels, the pad-LED SysEx
over hundreds of random inputs, and every input constant — see
[`tests/`](tests/)).

## API

### Output

| Method | Does |
|---|---|
| `set_pad(row, col, r, g, b)` | light one pad (r/g/b 0–127) |
| `set_pad_index(i, r, g, b)` | light pad `i` (0–63) |
| `set_pads(cells)` | light many at once; cells are `(row,col,r,g,b)` or `(index,r,g,b)` |
| `clear_pads()` | all pads off |
| `oled(draws)` | update the OLED (coalesced, ~25 fps, GIL-friendly) |
| `oled_now(draws)` | update the OLED synchronously |
| `oled_text(*lines, scale=1)` | convenience: draw stacked left-aligned lines |

`draws` is a list of `(text, x, y, scale)`. Scale 1 = small, 2 = bold 14px,
3 = 20px, 4 = 36px.

### Input (assign any; all optional)

```
on_pad(row, col, velocity)     on_pad_release(row, col)
on_button(name)                on_button_release(name)
on_dial(knob_index, delta)     on_dial_touch(knob_index)
on_select(delta)               on_select_press()
on_mute(row)
```

Button names: `STEP NOTE DRUM PERFORM SHIFT ALT PAT_SONG PLAY STOP REC
PATTERN_UP PATTERN_DOWN BROWSER GRID_LEFT GRID_RIGHT MODE MUTE1..4`.

Knob deltas are signed (turn left = negative). Drive input with `run()`
(blocking), `start()` (background thread), or `poll()` (from your own loop).

### Low-level

`akai_fire_handler.protocol` is pure — no MIDI, no Pillow, just constants and the
SysEx byte builders (`pad_leds_sysex`, `oled_buffer_to_sysex`, `plot`,
`classify_note`, `classify_cc`, `decode_relative`, …). Use it if you want to
talk to the Fire through your own MIDI stack.

## Examples

- [`examples/hello_oled.py`](examples/hello_oled.py) — text on the screen
- [`examples/rainbow_pads.py`](examples/rainbow_pads.py) — scrolling rainbow grid
- [`examples/input_echo.py`](examples/input_echo.py) — a tour of every input callback

## Tests

The protocol core is proven with no hardware attached:

```bash
python -m pytest        # or: python tests/test_protocol.py
```

## Credits

The 128×64 OLED pixel remap is the reverse-engineering published by **SEGGER**
in ["Decoding the Akai Fire" (part 3)](https://blog.segger.com/decoding-the-akai-fire-part-3/).
Everything else (pad-LED SysEx, the full input map, the rendering/coalescing
and high-level API) was captured and built for a real instrument.

## License

MIT — see [LICENSE](LICENSE). "Akai" and "Fire" are trademarks of inMusic /
Akai Professional; this project is an independent, unofficial tool, not
affiliated with or endorsed by them. The device name is used only to describe
what the library talks to.
