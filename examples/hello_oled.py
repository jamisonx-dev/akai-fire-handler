"""Put a couple of lines of text on the Fire's OLED."""
from akai_fire_handler import AkaiFire

fire = AkaiFire()
fire.oled_now([
    ("AKAI FIRE", 2, 0, 2),      # scale 2 = bold 14px
    ("akai-fire-handler", 2, 22, 1),
    ("hello, world", 2, 40, 1),
])
print(f"drew to {fire.output_name}")
