import sys, os
sys.path.insert(0, "addon")
import pcbediener_addon as a
# FL Studio starten
a.process_start("C:\\Users\\frank\\Downloads\\FL_Studio_2026_26.1.4.5589_official.exe", "", False, True)
print("FL Studio gestartet")