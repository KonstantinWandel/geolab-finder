#!/usr/bin/env python3
"""Query latency of both finders at two thread counts, in the order A, B, A. Runs on the geolab VM.

    python3 scripts/bench_threads.py            # 4, 8, 4 (the comparison of 2026-09-26)
    python3 scripts/bench_threads.py 8 12 8     # any A B A

Stdlib only, so it runs with the system python on the VM. The queries are the ones of the two
retrieval tests (eval_geodb_search.py, eval_soep_search.py), read from those files, each asked
once after a restart (the query-vector cache is empty, so this is a new search) and once more
(a repeat). The thread count is switched with its own drop-in, zz-threads-test.conf, never by
editing threads.conf, and the run ends by removing that file and restarting, so the services are
back at whatever threads.conf says. The services are down for about half a minute per restart.
Result: ~/bench_threads/result.json, progress in the terminal.

Result of 2026-09-26 on 8 vCPU: 8 threads make a new query about 40 % faster than 4 on both
finders (paired difference -0.63 s, 95 % interval -0.64 to -0.61, for GeoDB), same top hits."""
import ast, json, os, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/bench_threads")
os.makedirs(OUT, exist_ok=True)
def cases(name):
    tree = ast.parse(open(os.path.join(HERE, name), encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CASES" for t in node.targets):
            return list(dict.fromkeys(v[0] for v in ast.literal_eval(node.value)))
    raise SystemExit(f"no CASES in {name}")
Q = {"geodb": cases("eval_geodb_search.py"), "soep": cases("eval_soep_search.py")}
ORDER = [int(a) for a in sys.argv[1:]] or [4, 8, 4]
PORTS = {"geodb": 18002, "soep": 18001}
UNITS = {"geodb": "geolab-inkar", "soep": "geolab-soep"}
WARM = {"geodb": ["Einwohnerdichte Kreise", "Wahlbeteiligung Bundestagswahl", "Pendler Arbeitsort"],
        "soep": ["Zufriedenheit mit der Wohnung", "Geburtsjahr der Person", "Rauchen Zigaretten pro Tag"]}
DROPIN = "/etc/systemd/system/{}.service.d/zz-threads-test.conf"
def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)
def sh(cmd):
    return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout
def post(port, q):
    body = json.dumps({"question": q, "top_k": 12}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/soep/advice", data=body,
                                 headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    dt = time.perf_counter() - t
    top = (d.get("recommended_variables") or [{}])[0].get("variable_name", "")
    return dt, top
def set_threads(n):
    for unit in UNITS.values():
        path = DROPIN.format(unit)
        if n is None:
            sh(f"sudo rm -f {path}")
        else:
            conf = f"[Service]\nEnvironment=OMP_NUM_THREADS={n}\nEnvironment=MKL_NUM_THREADS={n}\nEnvironment=OPENBLAS_NUM_THREADS={n}\n"
            sh(f"printf '%s' '{conf}' | sudo tee {path} >/dev/null")
    sh("sudo systemctl daemon-reload")
    sh("sudo systemctl restart " + " ".join(UNITS.values()))
    for name, port in PORTS.items():
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                    if r.status == 200: break
            except Exception:
                pass
            time.sleep(3)
        else:
            raise SystemExit(f"{name} did not come up")
    seen = {}
    for name, unit in UNITS.items():
        pid = sh(f"systemctl show {unit} -p MainPID --value").strip()
        env = sh(f"sudo cat /proc/{pid}/environ").split("\0")
        seen[name] = [e for e in env if e.startswith("OMP_NUM_THREADS=")]
    return seen
res = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "nproc": os.cpu_count(), "runs": []}
for i, n in enumerate(ORDER):
    seen = set_threads(n)
    log(f"run {i}: threads={n}, services report {seen}")
    run = {"threads": n, "seen": seen, "services": {}}
    for name, port in PORTS.items():
        for q in WARM[name]:
            post(port, q)
        passes = []
        for p in (1, 2):
            rows = []
            for q in Q[name]:
                dt, top = post(port, q)
                rows.append({"q": q, "s": round(dt, 4), "top": top})
            passes.append(rows)
            log(f"  {name} pass {p}: median {sorted(r['s'] for r in rows)[len(rows)//2]:.3f}s")
        run["services"][name] = passes
    res["runs"].append(run)
    json.dump(res, open(f"{OUT}/result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
set_threads(None)
leftover = [u for u in UNITS.values() if os.path.exists(DROPIN.format(u))]
res["finished"] = time.strftime("%Y-%m-%d %H:%M:%S"); res["dropin_left"] = leftover
json.dump(res, open(f"{OUT}/result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
log("done; drop-in left:", leftover or "none")
