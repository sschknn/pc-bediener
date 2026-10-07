"""Repariert das INSTRUCTIONS-Encoding und fügt Fallback-Doku hinzu."""
import re

path = r"C:\Users\frank\Documents\Projekte\pc bediener\src\pcbediener\mcp_server.py"
with open(path, "rb") as f:
    raw = f.read()

# Repariere Latin1->UTF8 Umwandlung: Bytes, die Latin1 interpretiert wurden,
# zurück in UTF-8
try:
    txt = raw.decode("utf-8")
    # Wenn es UTF-8 ist, aber defekte Zeichen enthält, versuche Latin1->UTF-8
    if "�" in txt:
        txt = raw.decode("latin1")
        txt = txt.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        # Noch bessere Reparatur: Latin1-Bytes als UTF-8 neu interpretieren
        txt = raw.decode("latin1").encode("latin1").decode("utf-8", errors="replace")
except Exception as e:
    print(f"Decode-Fehler: {e}")
    exit(1)

# Definiere den neuen INSTRUCTIONS-Block
new_instructions = '''INSTRUCTIONS = """\\
Du steuerst den lokalen Windows-PC über diese Werkzeuge.

Arbeitsweise:
1. Zerlege die Aufgabe in klare Teilschritte und plane sie, bevor du handelst.
2. Nutze Tastatur-Shortcuts, wenn ein Dialog erreichbar ist – sie sind
   zuverlässiger als Klicks. Für Klicks: erst screenshot(), dann Koordinaten
   bestimmen; oder screen_find_image() mit einem Bild des Elements.
3. Warte nach Starts/Klicks mit screen_wait_for_image() oder sleep(), statt
   zu raten, ob eine Oberfläche schon geladen ist.
4. Liest du stderr/stdout aus einem exec_*-Aufruf, analysiere die Fehlermeldung,
   korrigiere den Code und führe ihn erneut aus.
5. Reagiert ein Fenster nicht mehr (kein Menü öffnet sich): window_modal_state()
   prüfen – ein modaler Dialog (z.B. Umbenennen/Bestätigen) deaktiviert das
   Hauptfenster, bis er geschlossen wird.
6. Für überlappende Fenster (Menüs, Dialoge) gilt nur screenshot(), nie ein
   PrintWindow-Composite – letzteres ignoriert die Z-Reihenfolge.
7. Pfade und Sonderzeichen immer per clipboard_set() + Strg+V eingeben
   (keyboard_type mit use_clipboard=True nutzt das automatisch).
 8. Für Bild-/Screenshot-Analyse: Subagent mit opencode/space-bunny-free
    (primär). Hängt oder scheitert es, Fallback: opencode/fledge-alpha-free.
    Das Programm-Gedächtnis (appmem_*) und flstudio_info() liefern Kontext.
9. Programm-Gedächtnis (appmem_*): Vor jeder App-Bedienung die Regel lesen
   (app_rule_get), danach Ergebnis verifizieren und Regeldatei AKTUALISIEREN
   (app_rule_set bei Erfolg, app_rule_break bei Fehlschlag). Nur verifizierte
   Wege benutzen – nie wiederholen, was unter avoid/broken steht.

LLM-Fallback-System:
- vision_model() zeigt die aktuelle Fallback-Kette (model_chain) + Status aller
  Modelle. Ein Modell mit Fehlern (Rate Limit, Quota, Credits) wird automatisch
  nach hinten verschoben und im Cooldown (60 s) gesetzt.
- Bei einem Rate-Limit-/Quota-/Credits-Fehler beim Subagenten sofort mit
  vision_model() prüfen, welches Modell als nächstes kommt. Dann den
  Subagenten mit model_chain_set(<nächstes_modell>) neu starten.
- model_chain_set(<Modell>) setzt ein Modell an die erste Stelle und löscht
  seinen Fehlerzähler – nützlich, wenn ein früherer Modell-Fehler behoben ist.
- model_chain_reset() leert alle Fehlerzähler und Cooldowns – für Neustarts.

Sicherheit:
- Destruktive Aktionen (exec_*, file_delete, file_write, file_move, process_kill,
  process_start, mouse_click) verlangen confirm=True, solange safety_mode
  "confirm" ist. Die Sperrliste in safety.py gilt immer, auch bei "auto".
- Dateizugriffe sind auf die Pfade in safety_status() begrenzt.
- Erkläre in einem kurzen Satz, was eine riskante Aktion bewirken würde, bevor
  du confirm=True setzt.
"""'''

# Finde den alten INSTRUCTIONS-Block und ersetze ihn
# Pattern: INSTRUCTIONS = """ ... """
pattern = r'INSTRUCTIONS\s*=\s*"""(?:.*?)\s*"""'
match = re.search(pattern, txt, re.DOTALL)
if not match:
    print("INSTRUCTIONS-Block nicht gefunden!")
    exit(1)

print(f"ALTER BLOCK ({match.group()[:50]}...): {len(match.group())} Zeichen")
print(f"Ersetzte durch neuen Block: {len(new_instructions)} Zeichen")

new_txt = txt[:match.start()] + new_instructions + txt[match.end():]

with open(path, "w", encoding="utf-8") as f:
    f.write(new_txt)

print("Datei geschrieben.")
