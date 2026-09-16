"""Fill the 4x16 pad grid with a scrolling rainbow. Ctrl-C to stop."""
import time
from akai_fire_handler import AkaiFire, hsv, N_ROWS, N_COLS

fire = AkaiFire()
try:
    t = 0.0
    while True:
        cells = []
        for row in range(N_ROWS):
            for col in range(N_COLS):
                hue = (col / N_COLS + row * 0.05 + t) % 1.0
                r, g, b = hsv(hue, 1.0, 0.6)
                cells.append((row, col, r, g, b))
        fire.set_pads(cells)
        t += 0.02
        time.sleep(1 / 30)
except KeyboardInterrupt:
    fire.clear_pads()
