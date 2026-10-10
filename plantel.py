#!/usr/bin/env python3
"""Atualiza planteis, fotos e carreiras dos treinadores do FC Gaia em data/jogos.json.

Fontes (fpb.pt):
  - /equipas/clube_119/ e /treinadores/clube_119/  -> listas (carregadas por JavaScript; lidas com Playwright)
  - /equipa/equipa_ID/   -> atletas de cada equipa
  - /atletas/ID/         -> número, posição, altura, foto (a data de nascimento NUNCA é guardada)
  - /treinadores/ID/     -> grau, foto e carreira

Regras:
  - Se uma equipa ou treinador falhar, mantém o que já estava guardado.
  - IDs fixos em config.json ("equipas_fpb", "treinadores_fpb") têm prioridade sobre a descoberta automática.
  - Equipa técnica e coordenação vêm de config.json ("equipa_tecnica", "coordenacao").
"""
import json, re, sys, time, unicodedata, datetime, pathlib
import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "jogos.json"
DEBUG = ROOT / "debug"
CONFIG = json.loads((ROOT / "scripts" / "config.json").read_text(encoding="utf-8"))
FPB = "https://www.fpb.pt"
CLUBE = CONFIG.get("clube_fpb", 119)
UA = {"User-Agent": "Mozilla/5.0 (FC Gaia site; atualizacao mensal do plantel)"}
TEAMS = [t["id"] for t in CONFIG["equipas"]]


def log(msg):
    print(msg, flush=True)


def norm(s):
    s = unicodedata.normalize("NFC", s or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def plain(s):
    s = unicodedata.normalize("NFD", norm(s)).encode("ascii", "ignore").decode()
    return s.lower()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", plain(s)).strip("-")


def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 + 3 * i)


# ---------- descoberta (páginas com JavaScript) ----------

def rendered_links(url, pattern, name):
    """Abre a página num browser, espera pela lista e devolve {id: texto do link}."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("AVISO: Playwright não instalado; uso só os IDs de config.json.")
        return {}
    out = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(user_agent=UA["User-Agent"])
            xhr = []
            pg.on("response", lambda r: xhr.append(r.url) if r.request.resource_type in ("xhr", "fetch") else None)
            pg.goto(url, wait_until="networkidle", timeout=90000)
            try:
                pg.wait_for_selector(f"a[href*='{pattern}']", timeout=30000)
            except Exception:  # noqa: BLE001
                log(f"AVISO: a lista em {url} não apareceu em 30 s.")
            pg.wait_for_timeout(1500)
            links = pg.eval_on_selector_all(
                "a[href]", "els=>els.map(e=>[e.href,(e.innerText||'').trim(),(e.closest('li,tr,article,div')||e).innerText||''])")
            DEBUG.mkdir(exist_ok=True)
            (DEBUG / f"{name}.html").write_text(pg.content(), encoding="utf-8")
            (DEBUG / f"{name}-xhr.txt").write_text("\n".join(xhr), encoding="utf-8")
            b.close()
        for href, txt, ctx in links:
            m = re.search(pattern + r"(\d+)", href)
            if m:
                out.setdefault(int(m.group(1)), norm(txt) or norm(ctx)[:200])
    except Exception as e:  # noqa: BLE001
        log(f"AVISO: falhou a leitura de {url} com o browser: {e}")
    log(f"{url}: {len(out)} links encontrados")
    for k, v in out.items():
        log(f"   {k}: {v[:120]}")
    return out


def team_from_text(t):
    """'FC Gaia B · Sub 18 Masculino' -> 'Sub-18 Masc B'. Devolve None se não for equipa configurada."""
    t = plain(t)
    if "femin" in t:
        return None
    if "esperanc" in t:
        return "Esperanças"
    for n in ("18", "16", "14"):
        if re.search(rf"sub[\s\-_]*{n}\b", t):
            b = re.search(r"gaia\s*\"?b\"?\b|\"b\"|\bequipa\s*b\b|\sb\s*$|\bb\s*[\|,·-]", t)
            tid = f"Sub-{n} Masc {'B' if b else 'A'}"
            return tid if tid in TEAMS else None
    if "senior" in t and "sub" not in t:
        return "Seniores Masc"
    return None


def discover_teams():
    ids = {k: int(v) for k, v in CONFIG.get("equipas_fpb", {}).items() if v}
    found = rendered_links(f"{FPB}/equipas/clube_{CLUBE}/", "/equipa/equipa_", "equipas")
    for eid, txt in found.items():
        if eid in ids.values():
            continue
        tid = team_from_text(txt)
        if not tid:
            # o texto do link pode não dizer o escalão; vê o título da página da equipa
            try:
                s = get(f"{FPB}/equipa/equipa_{eid}/")
                head = " ".join(norm(h.get_text(" ")) for h in s.select("title,h1,h2,h3")[:6])
                tid = team_from_text(head)
                txt = head
            except Exception as e:  # noqa: BLE001
                log(f"AVISO: equipa {eid}: {e}")
        if tid and tid in ids and tid.endswith(" A") and tid[:-1] + "B" not in ids:
            log(f"   {tid} já atribuída; equipa_{eid} fica como {tid[:-1]}B (confirma no site)")
            tid = tid[:-1] + "B"
        if tid and tid not in ids:
            ids[tid] = eid
            log(f"Equipa {tid} -> equipa_{eid}  ({txt[:80]})")
        elif not tid:
            log(f"   ignorada equipa_{eid}: {txt[:80]}")
    for t in TEAMS:
        if t not in ids:
            log(f"AVISO: não encontrei a página FPB da equipa {t}. Junta o ID em config.json -> equipas_fpb.")
    return ids


def discover_coaches(names):
    ids = {k: int(v) for k, v in CONFIG.get("treinadores_fpb", {}).items() if v}
    found = rendered_links(f"{FPB}/treinadores/clube_{CLUBE}/", "/treinadores/", "treinadores")
    for n in names:
        if n in ids:
            continue
        want = set(plain(n).split())
        for cid, txt in found.items():
            if want <= set(re.split(r"[^a-z]+", plain(txt))):
                ids[n] = cid
                log(f"Treinador {n} -> {cid}  ({txt[:60]})")
                break
        else:
            log(f"AVISO: não encontrei a ficha FPB de {n}. Junta o ID em config.json -> treinadores_fpb.")
    return ids


# ---------- páginas de equipa, atleta e treinador (HTML normal) ----------

def short(name):
    p = [w for w in norm(name).split() if w.lower() not in ("da", "de", "do", "das", "dos", "e")]
    return f"{p[0]} {p[-1]}" if len(p) > 1 else norm(name)


def team_athletes(eid):
    s = get(f"{FPB}/equipa/equipa_{eid}/")
    out = {}
    for a in s.select("a[href*='/atletas/']"):
        m = re.search(r"/atletas/(\d+)", a["href"])
        if m:
            txt = norm(a.get_text(" "))
            out.setdefault(int(m.group(1)), norm(txt.split("•")[-1]))
    return out


def label_value(lines, label):
    for i, l in enumerate(lines):
        if plain(l).rstrip(":") == plain(label) and i + 1 < len(lines):
            return lines[i + 1]
    return ""


def athlete(aid, fallback):
    s = get(f"{FPB}/atletas/{aid}/")
    lines = [norm(x) for x in s.get_text("\n").split("\n") if norm(x)]
    img = s.find("img", alt=re.compile("perfil", re.I))
    photo = img.get("src", "") if img else ""
    if "uploads/utilizadores" not in photo:
        photo = ""
    num, name = None, fallback
    if img:
        h = img.find_next(["h1", "h2", "h3"])
        if h and norm(h.get_text()):
            name = norm(h.get_text(" "))
        for st in img.find_all_next(string=True, limit=40):
            t = norm(st)
            if re.fullmatch(r"\d{1,3}", t):
                num = int(t)
                break
            if plain(t) in ("pontos", "nr. licenca") or (h and t == name):
                break
    pos = label_value(lines, "Posição").title()
    alt = re.sub(r"\D", "", label_value(lines, "Altura"))
    return {"name": short(name), "num": num, "pos": pos, "h": int(alt) if alt and 140 <= int(alt) <= 240 else None,
            "photo": photo, "id": aid}


ROLE = re.compile(r"^\(?(principal|adjunto|treinador.*|estagi.*)\)?$", re.I)


def coach(cid, name):
    s = get(f"{FPB}/treinadores/{cid}/")
    lines = [norm(x) for x in s.get_text("\n").split("\n") if norm(x)]
    img = s.find("img", alt=re.compile("perfil", re.I))
    photo = img.get("src", "") if img else ""
    if "uploads/utilizadores" not in photo:
        photo = ""
    grau = label_value(lines, "Nível Formação") or label_value(lines, "Nivel Formacao")
    car = []
    for tb in s.find_all("table"):
        hd = plain(tb.get_text(" ")[:200])
        if "epoca" not in hd or "fun" not in hd:
            continue
        for tr in tb.find_all("tr"):
            td = tr.find_all("td")
            if len(td) < 3:
                continue
            parts = []
            for l in td[2].get_text("\n").split("\n"):
                l = norm(l).strip(";,")
                if not l:
                    continue
                if parts and ROLE.match(l):
                    parts[-1] += " - " + l.strip("()").capitalize()
                else:
                    parts.append(l)
            funcs = "; ".join(parts)
            funcs = re.sub(r"\s*\((Principal|Adjunto)\)", r" - \1", funcs)
            car.append([norm(td[0].get_text()), norm(td[1].get_text(" ")), funcs])
        break
    return {"name": name, "id": cid, "grau": grau, "photo": photo, "carreira": car}


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    staff = CONFIG.get("equipa_tecnica", data.get("staff", {}))
    coord = CONFIG.get("coordenacao", data.get("coord", []))
    plantel = data.get("plantel", {})
    coaches = data.get("coaches", {})
    before = json.dumps([plantel, coaches, staff, coord], ensure_ascii=False, sort_keys=True)

    for tid, eid in discover_teams().items():
        try:
            ath = team_athletes(eid)
            rows = []
            for aid, nm in ath.items():
                try:
                    rows.append(athlete(aid, nm))
                except Exception as e:  # noqa: BLE001
                    log(f"AVISO: atleta {aid} ({nm}): {e}")
                time.sleep(0.4)
            if rows:
                plantel[tid] = rows
                log(f"{tid}: {len(rows)} atletas ({sum(1 for r in rows if r['photo'])} com foto)")
            else:
                log(f"AVISO: {tid}: nenhum atleta lido; mantenho o anterior.")
        except Exception as e:  # noqa: BLE001
            log(f"AVISO: equipa {tid} ({eid}): {e}")

    names = []
    for lst in staff.values():
        names += [n for n in lst if n not in names]
    names += [c["name"] for c in coord if c["name"] not in names]
    for n, cid in discover_coaches(names).items():
        try:
            c = coach(cid, n)
            old = coaches.get(slug(n), {})
            if not c["carreira"] and old.get("carreira"):
                c["carreira"] = old["carreira"]
            c["grau"] = c["grau"] or old.get("grau", "")
            c["photo"] = c["photo"] or old.get("photo", "")
            coaches[slug(n)] = c
            log(f"Treinador {n}: {c['grau'] or 'sem grau'}, {len(c['carreira'])} épocas, foto {'sim' if c['photo'] else 'não'}")
        except Exception as e:  # noqa: BLE001
            log(f"AVISO: treinador {n} ({cid}): {e}")
        time.sleep(0.4)

    data.update(plantel=plantel, coaches=coaches, staff=staff, coord=coord)
    if json.dumps([plantel, coaches, staff, coord], ensure_ascii=False, sort_keys=True) != before:
        data["updated"] = datetime.date.today().isoformat()
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        log("Plantel e treinadores atualizados.")
    else:
        log("Plantel e treinadores sem alterações.")
    if not plantel:
        sys.exit("ERRO: nenhum plantel lido.")


if __name__ == "__main__":
    main()
