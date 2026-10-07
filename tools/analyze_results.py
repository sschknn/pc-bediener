"""Fasse das Latenz-Ranking und die neue Fallback-Logik zusammen."""
# -*- coding: utf-8 -*-
import os, sys, codecs

# Force UTF-8 für die Konsole
if sys.stdout.encoding != 'utf-8':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

print("=" * 70)
print("FINALER LATENZ-RANKING: Alle kostenlosen Text-Modelle")
print("=" * 70)
print("Teststart T0: 2026-10-04T21:12:14.792 UTC")
print()

results = [
    ("Apodex 1.1 Mini (free)        ", "33.1s", "~2-3ms", ""),
    ("LongCat 2.5 Preview Free      ", "20.9s", "~0-5ms", ""),
    ("Dots3-Note Preview (free)     ", "22.1s", "~8-15ms", ""),
    ("Space Bunny Free              ", "10.4s", "~54-92ms", ""),
    ("Space Bunny Alpha (OpenRouter)", "11.7s", "~51-65ms", ""),
    ("Ling 3.1 Flash Free           ", "77.0s", "~44ms", ""),
    ("Gemma 4 31B IT (Google)       ", "FEHLER", "Quota", "Google Free-Tier erschöpft"),
    ("Fledge Alpha Free             ", "25.5s", "~5-6ms (Run2)", ""),
    ("Nemotron 3.5 Lightning Free    ", "22.1s", "2.3-3.6s", "VERSCHLEPPT"),
    ("North Mini Code (free)        ", "21.7s", "2.5-2.7s", "VERSCHLEPPT"),
    ("LFM2.5-2.6B (free)            ", "25.2s", "4.1s (R1)", "VERSCHLEPPT"),
    ("Free Models Router (OR)       ", "23.0s", "4.7-5.4s", "VERSCHLEPPT"),
    ("Laguna S 2.1 (free)           ", "7.6s", "3.7-5.7s", "VERSCHLEPPT"),
    ("Laguna XS 2.1 (free)          ", "25.9s", "2.7s (R1)", "VERSCHLEPPT"),
]

failed = [
    "Big Pickle, Muse Spark, MiMo-V2.6: OpenCode Zen Rate Limited",
    "Ling 3.1 Flash OR, Fusion, Pareto Code: OpenRouter Credits",
    "Body Builder: keine Tool-Use-Endpunkte",
]

print(f"{'Rang':<5}{'Modell':<34}{'Erste Aktion':<14}{'Pro-Turn-Latenz':<18}{'Status'}")
print("-" * 85)
for i, (name, first, per_turn, status) in enumerate(results, 1):
    print(f"{i:<5}{name:<34}{first:<14}{per_turn:<18}{status}")

print()
print("FEHLGESCHLAGEN (Rate Limit / Credits / Quota):")
for f in failed:
    print(f"  - {f}")
print()
print("=" * 70)
print("FALLBACK-LOGIK: Neu implementiert in runtime.py + config.py")
print("=" * 70)
print("model_chain: 16 priorisierte Free-Modelle (Latenz-getestet, schnellste zuerst)")
print("Pro-Modell-Status: failures, last_failure, cooldown_until")
print("Cooldown: 60s (config: model_cooldown_s)")
print("Max Failures: 3 (config: model_max_failures)")
print()
print("Neue Tools:")
print("  - vision_model(): zeigt Kette + live-Status aller Modelle")
print("  - model_chain_set(<id>): setzt Modell an 1. Stelle, resettet Fehler")
print("  - model_chain_reset(): leert alle Fehlerzähler + Cooldowns")
print()
print("Test-Ergebnis (Simulation):")
print("  Ling (3x Fehler) -> Nicht verfügbar")
print("  next_available -> Space Bunny Free")
print("  Nach Reset -> Ling wieder verfügbar")
