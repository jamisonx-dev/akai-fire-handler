"""
akai_fire_handler.device -- a friendly high-level wrapper around one Akai Fire.

    from akai_fire_handler import AkaiFire

    fire = AkaiFire()                     # finds the Fire by MIDI port name
    fire.clear_pads()
    fire.set_pad(0, 0, 127, 0, 0)         # top-left pad red
    fire.oled_text("HELLO", "akai fire")

    def pad(row, col, velocity):
        fire.set_pad(row, col, 0, 127, 0)
    fire.on_pad = pad

    fire.on_button = lambda name: print("button:", name)

    fire.run()                            # blocking input loop (Ctrl-C to stop)

Callbacks are plain attributes you assign (each optional; unhandled events are
ignored):

    on_pad(row, col, velocity)     on_pad_release(row, col)
    on_button(name)                on_button_release(name)
    on_dial(knob_index, delta)     on_dial_touch(knob_index)
    on_select(delta)               on_select_press()
    on_mute(row)

Output methods are thread-safe (they share oled.IO_LOCK), so you can paint from
a callback and from another thread at the same time.
"""

import threading

import mido

from . import protocol, oled


def find_fire(names):
    """Return the first MIDI port name containing 'FIRE' (case-insensitive)."""
    for n in names:
        if "FIRE" in n.upper():
            return n
    return None


class AkaiFire:
    def __init__(self, port_name=None, input_name=None, output_name=None):
        """Open the Fire's MIDI in + out.

        port_name: substring to match for BOTH in and out (default: 'FIRE').
        input_name / output_name: override either side explicitly.
        """
        in_names = mido.get_input_names()
        out_names = mido.get_output_names()

        def _match(names, override):
            if override:
                return override
            pool = names
            if port_name:
                pool = [n for n in names if port_name.upper() in n.upper()]
            return find_fire(pool) or find_fire(names)

        i = _match(in_names, input_name)
        o = _match(out_names, output_name)
        if i is None or o is None:
            raise RuntimeError(
                "Akai Fire MIDI port not found "
                f"(inputs={in_names!r}, outputs={out_names!r})")
        self._in = mido.open_input(i)
        self._out = mido.open_output(o)
        self.input_name, self.output_name = i, o

        # Callbacks -- assign any of these; all optional.
        self.on_pad = None            # (row, col, velocity)
        self.on_pad_release = None    # (row, col)
        self.on_button = None         # (name)
        self.on_button_release = None  # (name)
        self.on_dial = None           # (knob_index, delta)
        self.on_dial_touch = None     # (knob_index)
        self.on_select = None         # (delta)
        self.on_select_press = None   # ()
        self.on_mute = None           # (row)

        self._running = False
        self._thread = None

    # -- output ------------------------------------------------------------- #

    def _send_pads(self, cells):
        if not cells:
            return
        data = protocol.pad_leds_sysex(cells)
        with oled.IO_LOCK:
            self._out.send(mido.Message("sysex", data=data))

    def set_pad_index(self, index, r, g, b):
        """Light one pad by 0..63 index."""
        self._send_pads([(index, r, g, b)])

    def set_pad(self, row, col, r, g, b):
        """Light one pad by (row, col)."""
        self._send_pads([(protocol.pad_index(row, col), r, g, b)])

    def set_pads(self, cells):
        """Light many pads at once. Each cell is (row, col, r, g, b) or
        (index, r, g, b). Only the pads you pass change."""
        norm = []
        for c in cells:
            if len(c) == 5:
                row, col, r, g, b = c
                norm.append((protocol.pad_index(row, col), r, g, b))
            else:
                norm.append(tuple(c))
        self._send_pads(norm)

    def clear_pads(self):
        """Turn every pad off."""
        n = protocol.N_ROWS * protocol.N_COLS
        self._send_pads([(i, 0, 0, 0) for i in range(n)])

    def oled(self, draws):
        """Coalesced OLED update. draws: list of (text, x, y, scale)."""
        oled.show_lines(draws, self._out)

    def oled_now(self, draws):
        """Synchronous OLED update (bypasses the coalescer)."""
        oled.show_lines_now(draws, self._out)

    def oled_text(self, *lines, scale=1, x=2):
        """Convenience: draw up to a few left-aligned lines, top to bottom."""
        draws = []
        y = 0
        for text in lines:
            draws.append((str(text), x, y, scale))
            y += oled.line_h(scale)
        self.oled(draws)

    # -- input -------------------------------------------------------------- #

    def _dispatch(self, msg):
        name, args = protocol.route_event(
            getattr(msg, "type", None),
            note=getattr(msg, "note", None),
            velocity=getattr(msg, "velocity", 0),
            control=getattr(msg, "control", None),
            value=getattr(msg, "value", 0),
        )
        if name is None:
            return
        cb = getattr(self, name, None)
        if cb is not None:
            cb(*args)

    def poll(self):
        """Process any pending input once, non-blocking. Call from your own
        loop if you don't want run()/start() to own a thread."""
        for msg in self._in.iter_pending():
            self._dispatch(msg)

    def run(self):
        """Blocking input loop. Ctrl-C to stop."""
        self._running = True
        try:
            for msg in self._in:
                if not self._running:
                    break
                self._dispatch(msg)
        except KeyboardInterrupt:
            pass

    def start(self):
        """Run the input loop on a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run, name="akai-fire-input",
                                        daemon=True)
        self._thread.start()

    def close(self):
        self._running = False
        for port in (self._in, self._out):
            try:
                port.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
