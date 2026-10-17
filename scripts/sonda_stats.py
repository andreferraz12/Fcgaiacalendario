#!/usr/bin/env python3
"""Sonda temporária: ver como o Centro de Resultados liga aos FIBA LiveStats e o formato dos dados."""
import json, re, pathlib, requests
from bs4 import BeautifulSoup
OUT = pathlib.Path("debug"); OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (FC Gaia calendario)"}
log = []
def L(*a): log.append(" ".join(str(x) for x in a)); print(*a)
B = "https://resultados.tugabasket.com"
s = requests.Session()
d = s.get(f"{B}/getCompetitionDetails?competitionId=11442", headers=UA, timeout=30).text
(OUT / "comp-11442.html").write_text(d, encoding="utf-8")
phases = sorted(set(re.findall(r"getSchedule\?competitionId=11442&(?:amp;)?phaseId=(\d+)", d)))
L("fases", phases)
for pid in phases:
    h = requests.get(f"{B}/getSchedule?competitionId=11442&phaseId={pid}", headers=UA, timeout=30).text
    (OUT / f"sched-11442-{pid}.html").write_text(h, encoding="utf-8")
    soup = BeautifulSoup(h, "html.parser")
    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    L("fase", pid, "links:", len(links))
    for x in sorted(set(links)):
        if re.search(r"(?i)genius|fibalive|livestats|stats|game|match|jogo", x):
            L("   ", x)
    for tag in soup.find_all(attrs={"onclick": True})[:5]:
        L("   onclick:", tag.get("onclick")[:200])
    for tag in soup.find_all(attrs=lambda a: a and any(k.startswith("data-") for k in a))[:5]:
        L("   data-attrs:", {k: v for k, v in tag.attrs.items() if k.startswith("data-")})
for u in ["https://fibalivestats.dcd.shared.geniussports.com/data/2937951/data.json"]:
    try:
        r = requests.get(u, headers=UA, timeout=30)
        L("GET", u, r.status_code, len(r.text))
        (OUT / "livestats-2937951.json").write_text(r.text, encoding="utf-8")
        j = r.json()
        L("keys", list(j.keys())[:40])
        for k in ("1", "2"):
            t = j.get("tm", {}).get(k, {})
            L("tm", k, t.get("name"), t.get("score"), "pl:", len(t.get("pl", {})))
            pl = next(iter(t.get("pl", {}).values()), {})
            L("  player keys", list(pl.keys()))
    except Exception as e:
        L("ERRO", u, e)
(OUT / "sonda.log").write_text("\n".join(log), encoding="utf-8")
