import sys, os
sys.path.insert(0, "addon")
import pcbediener_addon as a
a.sleep(15)
windows = a.window_list("")
fl = None
for w in windows["windows"]:
    print(f"Titel: {w['title']}, x={w['x']}, y={w['y']}, w={w['width']}, h={w['height']}")
    if "FL Studio" in w["title"]:
        fl = w

if fl:
    print("FL Studio gefunden!")
else:
    print("FL Studio NICHT gefunden")