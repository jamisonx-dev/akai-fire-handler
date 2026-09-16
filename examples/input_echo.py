"""Light a pad while it's held; print every button, knob and encoder event.

A minimal tour of the input callbacks. Ctrl-C to stop.
"""
from akai_fire import AkaiFire, hsv

fire = AkaiFire()
fire.clear_pads()
fire.oled_now([("press pads,", 2, 0, 1),
               ("turn knobs...", 2, 16, 1)])

# A counter per knob so we can show accumulated position on the OLED.
pos = [0, 0, 0, 0]


def pad_down(row, col, vel):
    r, g, b = hsv((row * 16 + col) / 64.0, 1.0, 0.7)
    fire.set_pad(row, col, r, g, b)


def pad_up(row, col):
    fire.set_pad(row, col, 0, 0, 0)


def dial(i, delta):
    pos[i] = max(0, min(127, pos[i] + delta))
    fire.oled([(f"knob {i+1}: {pos[i]}", 2, 0, 2)])


fire.on_pad = pad_down
fire.on_pad_release = pad_up
fire.on_dial = dial
fire.on_button = lambda name: print("button:", name)
fire.on_button_release = lambda name: print("release:", name)
fire.on_select = lambda d: print("select turn:", d)
fire.on_select_press = lambda: print("select press")

print(f"listening on {fire.input_name}  (Ctrl-C to stop)")
fire.run()
