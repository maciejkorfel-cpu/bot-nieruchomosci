"""Jednorazowy skrypt: pętla Nowy Targ – Velo Dunajec – Szlak wokół Tatr – Nowy Targ,
poprowadzona dokładnie po geometrii oznakowanych szlaków z OpenStreetMap."""
import heapq, json, math, time, requests

import traceback
UA = {"User-Agent": "bot-nieruchomosci-gpx/1.0 (github.com/maciejkorfel-cpu)"}
out = {}

def main():
    global out

    def dist(a, b):
        la = math.radians((a[0] + b[0]) / 2)
        return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * math.cos(la))

    def geocode(q):
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": q, "format": "json", "limit": 1}, headers=UA, timeout=30)
        time.sleep(1.2); j = r.json()
        return (float(j[0]["lat"]), float(j[0]["lon"])) if j else None

    def overpass(q):
        for i in range(6):
            r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=UA, timeout=180)
            if r.status_code == 200:
                return r.json()["elements"]
            time.sleep(20 * (i + 1))
        raise RuntimeError(f"Overpass {r.status_code}: {r.text[:300]}")

    RELS = {r["id"]: r for r in overpass("[out:json][timeout:120];relation(id:7343774,7547982);out geom;")}

    def rel_graph(rid):
        g = {}
        for m in RELS[rid].get("members", []):
            if m.get("type") != "way":
                continue
            pts = [(round(p["lat"], 7), round(p["lon"], 7)) for p in m.get("geometry", []) or []]
            for a, b in zip(pts, pts[1:]):
                d = dist(a, b)
                g.setdefault(a, []).append((b, d)); g.setdefault(b, []).append((a, d))
        return g

    def nearest(g, p):
        return min(g, key=lambda n: dist(n, p))

    def path(g, a, b):
        best = {a: 0}; prev = {}; pq = [(0, a)]
        while pq:
            d, n = heapq.heappop(pq)
            if n == b: break
            if d > best.get(n, 1e18): continue
            for m, w in g[n]:
                nd = d + w
                if nd < best.get(m, 1e18):
                    best[m] = nd; prev[m] = n; heapq.heappush(pq, (nd, m))
        if b not in best: return None
        seq = [b]
        while seq[-1] != a: seq.append(prev[seq[-1]])
        return seq[::-1]

    VD = rel_graph(7343774)      # Velo Dunajec
    SWT = rel_graph(7547982)     # Szlak wokół Tatr
    time.sleep(2)

    # punkty styku obu szlaków
    shared = [n for n in VD if n in SWT]
    clusters = []
    for n in shared:
        for c in clusters:
            if dist(c[0], n) < 300: c.append(n); break
        else: clusters.append([n])
    out["junctions"] = [{"lat": c[0][0], "lon": c[0][1], "nodes": len(c)} for c in clusters]

    P = {k: geocode(v) for k, v in {
        "stacja": "Dworzec PKP, Nowy Targ", "waksmund": "Waksmund, nowotarski", "ostrowsko": "Ostrowsko, nowotarski",
        "lopuszna": "Łopuszna, nowotarski", "nowa_biala": "Nowa Biała, nowotarski", "gronkow": "Gronków, nowotarski",
        "bor": "Bór na Czerwonem", "debno": "Dębno, nowotarski"}.items()}
    out["places"] = P

    # styk zachodni = najbliżej stacji, wschodni = najbliżej Nowej Białej / Dębna (na wschód od Łopusznej)
    west = min(clusters, key=lambda c: dist(c[0], P["stacja"]))[0]
    east_cands = [c[0] for c in clusters if c[0][1] > P["lopuszna"][1] - 0.01]
    east = min(east_cands, key=lambda n: dist(n, P["nowa_biala"])) if east_cands else None
    out["west_junction"], out["east_junction"] = west, east

    def chain(g, pts):
        seq = []
        for a, b in zip(pts, pts[1:]):
            s = path(g, a, b)
            if s is None: raise SystemExit(f"brak połączenia {a}->{b}")
            seq += s if not seq else s[1:]
        return seq

    vd_seq = chain(VD, [west, nearest(VD, P["waksmund"]), nearest(VD, P["ostrowsko"]), nearest(VD, P["lopuszna"]), east])
    swt_seq = chain(SWT, [east, nearest(SWT, P["nowa_biala"]), nearest(SWT, P["gronkow"]), nearest(SWT, P["bor"]), west])
    loop = vd_seq + swt_seq[1:]

    def length(s): return sum(dist(a, b) for a, b in zip(s, s[1:]))
    out["vd_km"] = round(length(vd_seq) / 1000, 1); out["swt_km"] = round(length(swt_seq) / 1000, 1)
    out["station_to_west_m"] = round(dist(P["stacja"], west))
    for k in ("nowa_biala", "gronkow", "bor", "waksmund", "lopuszna", "debno"):
        out[f"min_dist_{k}_m"] = round(min(dist(P[k], n) for n in loop))

    # dojazd ze stacji do pętli (BRouter) + statystyki nawierzchni dla całości (gęste punkty pośrednie)
    def sample(seq, step=600):
        res, acc = [seq[0]], 0
        for a, b in zip(seq, seq[1:]):
            acc += dist(a, b)
            if acc >= step: res.append(b); acc = 0
        if res[-1] != seq[-1]: res.append(seq[-1])
        return res
    via = [P["stacja"]] + sample(loop) + [P["stacja"]]
    ll = "|".join(f"{p[1]:.6f},{p[0]:.6f}" for p in via)
    gj = requests.get("https://brouter.de/brouter", params={"lonlats": ll, "profile": "trekking",
                      "alternativeidx": 0, "format": "geojson"}, headers=UA, timeout=180).json()
    props = gj["features"][0]["properties"]; coords = gj["features"][0]["geometry"]["coordinates"]
    out["brouter_km"] = round(int(props["track-length"]) / 1000, 1); out["ascend_m"] = props.get("filtered ascend")
    msgs = props["messages"]; h = msgs[0]; iD, iT = h.index("Distance"), h.index("WayTags")
    surf, hw = {}, {}
    for m in msgs[1:]:
        d = int(m[iD]); t = dict(x.split("=", 1) for x in m[iT].split() if "=" in x)
        surf[t.get("surface", "?")] = surf.get(t.get("surface", "?"), 0) + d
        hw[t.get("highway", "?")] = hw.get(t.get("highway", "?"), 0) + d
    tot = sum(surf.values()) or 1
    out["surface_pct"] = {k: round(v * 100 / tot, 1) for k, v in sorted(surf.items(), key=lambda x: -x[1])}
    out["highway_pct"] = {k: round(v * 100 / tot, 1) for k, v in sorted(hw.items(), key=lambda x: -x[1])}
    trail = set(VD) | set(SWT)
    out["on_trails_pct"] = round(100 * sum(1 for c in coords[::4] if min(dist((c[1], c[0]), n) for n in loop[::3]) < 30)
                                / max(1, len(coords[::4])), 1)

    # GPX: ślad z BRoutera (gęste punkty na szlaku, z wysokościami) + punkty orientacyjne
    trk = "".join(f'<trkpt lat="{c[1]:.6f}" lon="{c[0]:.6f}">' + (f"<ele>{c[2]}</ele>" if len(c) > 2 else "") + "</trkpt>\n" for c in coords)
    names = [("Start/meta: dworzec PKP Nowy Targ", P["stacja"]), ("Waksmund", P["waksmund"]), ("Ostrowsko", P["ostrowsko"]),
             ("Łopuszna – dwór Tetmajerów", P["lopuszna"]), ("Przejście na Szlak wokół Tatr", east),
             ("Nowa Biała", P["nowa_biala"]), ("Gronków – Cisowa Skała", P["gronkow"]),
             ("Rezerwat Bór na Czerwonem (szuter)", nearest(SWT, P["bor"]))]
    wpt = "".join(f'<wpt lat="{p[0]:.6f}" lon="{p[1]:.6f}"><name>{n}</name></wpt>\n' for n, p in names)
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Claude" xmlns="http://www.topografix.com/GPX/1/1">\n'
           '<metadata><name>Pętla Nowy Targ – Velo Dunajec – Szlak wokół Tatr</name></metadata>\n' + wpt +
           '<trk><name>Pętla Nowy Targ – Velo Dunajec – Szlak wokół Tatr</name><trkseg>\n' + trk + '</trkseg></trk>\n</gpx>\n')
    open("trasy/petla_nowy_targ.gpx", "w", encoding="utf-8").write(gpx)
    json.dump(out, open("trasy/raport.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))

try:
    main()
except BaseException:
    out["ERROR"] = traceback.format_exc()
    json.dump(out, open("trasy/raport.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(out["ERROR"])
