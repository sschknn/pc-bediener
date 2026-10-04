import os, sys
sys.path.insert(0, "addon")
project_dir = r"C:\Users\frank\Documents\Hardtekk_Project"
samples = ["lacazette_ALC_vocals.wav","hardtekk_drums.wav","hardtekk_bass.wav","hardtekk_synth.wav","hardtekk2_drums.wav"]
print("=== Projekt-Status ===")
for s in samples:
    exists = os.path.exists(os.path.join(project_dir, s))
    print(f"OK {s}" if exists else f"FEHLT {s}")