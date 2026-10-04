import sys, os
sys.path.insert(0, "addon")
import pcbediener_addon as a
windows = a.window_list("")
for w in windows["windows"]:
    print(f'Titel: {w["title"]}, x={w["x"]}, y={w["y"]}, w={w["width"]}, h={w["height"]}')