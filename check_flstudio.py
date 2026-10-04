import psutil
procs = [p for p in psutil.process_iter(['pid','name','exe']) if p.info['exe'] and 'fl' in p.info['exe'].lower()]
for p in procs:
    print(f'PID={p.info["pid"]} Name={p.info["name"]} Exe={p.info["exe"]}')
print('Kein FL Studio' if not procs else f'{len(procs)} gefunden')