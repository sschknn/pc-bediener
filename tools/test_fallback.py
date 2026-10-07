import sys
sys.path.insert(0, r'C:\Users\frank\Documents\Projekte\pc bediener/src')
import pcbediener.runtime as rt

rt.reset_model_state()
cfg = rt.get_config()

print('=== Fallback-Kette ===')
print(f'Erste 5 Modelle: {cfg.model_chain[:5]}')
print(f'next_available: {rt.next_available_model()}')
print()

# Test 1: Ling fällt aus (3 Fehler)
for _ in range(3):
    rt.record_model_failure('opencode/ling-3.1-flash-free')

print('=== Nach 3 Fehlern auf Ling ===')
print(f'ling available: {rt.model_available("opencode/ling-3.1-flash-free")}')
print(f'next_available: {rt.next_available_model()}')
print()

# Test 2: Space Bunny fällt aus (2 Fehler)
rt.record_model_failure('opencode/space-bunny-free')
rt.record_model_failure('opencode/space-bunny-free')

print('=== Nach 2 weiteren Fehlern auf Space Bunny ===')
print(f'space_bunny available: {rt.model_available("opencode/space-bunny-free")}')
print(f'next_available: {rt.next_available_model()}')
print()

# Test 3: Reset
rt.reset_model_state()
print('=== Nach Reset ===')
print(f'next_available: {rt.next_available_model()}')
print(f'Total modelle in Kette: {len(cfg.model_chain)}')
