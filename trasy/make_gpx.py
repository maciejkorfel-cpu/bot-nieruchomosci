"""Jednorazowy skrypt: pętla Nowy Targ – Velo Dunajec – Nowa Biała – Szlak wokół Tatr – Nowy Targ."""
import json, math, time, urllib.parse, requests

UA = {"User-Agent": "bot-nieruchomosci-gpx/1.0 (github.com/maciejkorfel-cpu)"}
BBOX = (49.40, 19.95, 49.52, 20.25)
out = {}

def geocode(q):
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params={"q": q, "format": "json", "limit": 1}, headers=UA, timeout=30)
    time.sleep(1.2)
    j = r.json()
    return (float(j[0]["lat"]), float(j[0]["lon"])) if j else None

# 1) relacje rowerowe w okolicy
q = f"""[out:json][timeout:90];
relation["route"="bicycle"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out geom;"""
rels = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=UA, timeout=120).json()["elements"]
out["relations"] = [{"id": r["id"], "name": r.get("tags", {}).get("name"), "ref": r.get("tags", {}).get("ref")} for r in rels]

def pts_of(pred):
    pts = []
    for r in rels:
        n = (r.get("tags", {}).get("name") or "") + " " + (r.get("tags", {}).get("ref") or "")
        if pred(n.lower()):
            for m in r.get("members", []):
                for g in m.get("geometry", []) or []:
                    pts.append((g["lat"], g["lon"]))
    return pts

dun = pts_of(lambda n: "dunajec" in n)
tatr = pts_of(lambda n: "tatr" in n)
out["n_points"] = {"dunajec": len(dun), "tatr": len(tatr)}

def dist(a, b):
    la = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * math.cos(la))

def snap(p, pts):
    return min(pts, key=lambda x: dist(p, x)) if pts else p

# 2) punkty pętli (przyciągnięte do właściwego szlaku)
plan = [
    ("Dworzec PKP Nowy Targ", "Dworzec PKP, Nowy Targ", None),
    ("Waksmund", "Waksmund, nowotarski", dun),
    ("Ostrowsko", "Ostrowsko, nowotarski", dun),
    ("Łopuszna", "Łopuszna, nowotarski", dun),
    ("Nowa Biała", "Nowa Biała, nowotarski", tatr),
    ("Gronków", "Gronków, nowotarski", tatr),
    ("Rezerwat Bór na Czerwonem", "Bór na Czerwonem", tatr),
    ("Dworzec PKP Nowy Targ", "Dworzec PKP, Nowy Targ", None),
]
wps = []
for name, query, pts in plan:
    g = geocode(query) or geocode(name)
    s = snap(g, pts) if (g and pts) else g
    wps.append({"name": name, "geocoded": g, "snapped": s, "snap_m": round(dist(g, s)) if g and s else None})
out["waypoints"] = wps

lonlats = "|".join(f"{w['snapped'][1]:.6f},{w['snapped'][0]:.6f}" for w in wps)
base = "https://brouter.de/brouter?lonlats=" + lonlats + "&profile=trekking&alternativeidx=0"
gj = requests.get(base + "&format=geojson", headers=UA, timeout=120).json()
gpx = requests.get(base + "&format=gpx&trackname=Petla_Nowy_Targ_Velo_Dunajec_Szlak_wokol_Tatr", headers=UA, timeout=120).text

props = gj["features"][0]["properties"]
coords = gj["features"][0]["geometry"]["coordinates"]
out["length_km"] = round(int(props["track-length"]) / 1000, 1)
out["ascend_m"] = props.get("filtered ascend")

# 3) nawierzchnia i typ drogi z tagów OSM
msgs = props.get("messages", [])
hdr = msgs[0]
i_dist, i_tags = hdr.index("Distance"), hdr.index("WayTags")
surf, hw = {}, {}
for m in msgs[1:]:
    d = int(m[i_dist]); tags = dict(t.split("=", 1) for t in m[i_tags].split() if "=" in t)
    s = tags.get("surface", "?"); h = tags.get("highway", "?")
    surf[s] = surf.get(s, 0) + d; hw[h] = hw.get(h, 0) + d
tot = sum(surf.values()) or 1
out["surface_pct"] = {k: round(v * 100 / tot, 1) for k, v in sorted(surf.items(), key=lambda x: -x[1])}
out["highway_pct"] = {k: round(v * 100 / tot, 1) for k, v in sorted(hw.items(), key=lambda x: -x[1])}

# 4) jaka część trasy leży na oznakowanych szlakach
allp = dun + tatr
near = sum(1 for c in coords[::5] if allp and min(dist((c[1], c[0]), p) for p in allp[::3]) < 40)
out["on_marked_trails_pct"] = round(near * 100 / max(1, len(coords[::5])), 1)

# 5) GPX z punktami (waypointy) dla nawigacji
wpt = "".join(f'<wpt lat="{w["snapped"][0]:.6f}" lon="{w["snapped"][1]:.6f}"><name>{w["name"]}</name></wpt>\n'
              for w in wps[:-1])
gpx = gpx.replace("<trk>", wpt + "<trk>", 1)
open("trasy/petla_nowy_targ.gpx", "w", encoding="utf-8").write(gpx)
json.dump(out, open("trasy/raport.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
