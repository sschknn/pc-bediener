import sys, os
sys.path.insert(0, "addon")
import pcbediener_addon as a

for attempt in range(6):
    a.sleep(10)
    windows = a.window_list("")
    fl = None
    for w in windows["windows"]:
        if "FL Studio" in w["title"]:
            fl = w
            print(f"Versuch {attempt+1}: FL Studio gefunden! x={w['x']}, y={w['y']}, w={w['width']}, h={w['height']}")
            break
    if fl:
        # Fenster fokussieren
        a.window_focus("FL Studio 2026")
        print("FL Studio fokussiert")
        break
    print(f"Versuch {attempt+1}: FL Studio nicht gefunden, weiter warten...")