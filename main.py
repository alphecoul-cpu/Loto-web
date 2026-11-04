import csv
import io
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# ---------- Config ----------
BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
CI_FICHIER = DATA / "ci_tirages.csv"
GH_FICHIER = DATA / "gh_tirages.csv"

CI_COLONNES = ["date","win1","win2","win3","win4","win5","mac1","mac2","mac3","mac4","mac5"]
GH_COLONNES = ["date","jeu","win1","win2","win3","win4","win5","mac1","mac2","mac3","mac4","mac5"]
JEUX_GH = ["Monday Special","Lucky Tuesday","Midweek","Friday Bonanza","Saturday","VAG"]

app = FastAPI(title="Loto Analyse")
templates = Jinja2Templates(directory=str(BASE / "templates"))


# ---------- Utilitaires ----------
def init_fichier(path: Path, colonnes: list[str]):
    if not path.exists():
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(colonnes)


def charger_ci() -> pd.DataFrame:
    init_fichier(CI_FICHIER, CI_COLONNES)
    df = pd.read_csv(CI_FICHIER, parse_dates=["date"])
    return df.sort_values("date", ascending=False).reset_index(drop=True)


def charger_gh() -> pd.DataFrame:
    init_fichier(GH_FICHIER, GH_COLONNES)
    df = pd.read_csv(GH_FICHIER, parse_dates=["date"])
    return df.sort_values("date", ascending=False).reset_index(drop=True)


def freq_par_colonnes(df: pd.DataFrame, cols: list[str]) -> dict[int, int]:
    cnt = Counter(df[cols].values.flatten().tolist())
    return {n: cnt.get(n, 0) for n in range(1, 91)}


def chauds_froids(freq: dict[int, int], top: int = 10):
    tries = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    return tries[:top], tries[-top:][::-1]


# ---------- Pages ----------
@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def accueil(request: Request):
    ci = charger_ci()
    gh = charger_gh()
    return templates.TemplateResponse("accueil.html", {
        "request": request,
        "nb_ci": len(ci),
        "nb_gh": len(gh),
    })


@app.get("/ci", response_class=HTMLResponse)
def page_ci(request: Request, limit: int = 30):
    df = charger_ci().head(limit)
    tirages = [
        {"date": r["date"].strftime("%Y-%m-%d"),
         "win": [int(r[f"win{k}"]) for k in range(1,6)],
         "mac": [int(r[f"mac{k}"]) for k in range(1,6)]}
        for _, r in df.iterrows()
    ]
    return templates.TemplateResponse("resultats_ci.html", {
        "request": request, "tirages": tirages, "limit": limit,
    })


@app.get("/gh", response_class=HTMLResponse)
def page_gh(request: Request, jeu: str | None = None, limit: int = 30):
    df = charger_gh()
    if jeu:
        df = df[df["jeu"] == jeu]
    df = df.head(limit)
    tirages = [
        {"date": r["date"].strftime("%Y-%m-%d"), "jeu": r["jeu"],
         "win": [int(r[f"win{k}"]) for k in range(1,6)],
         "mac": [int(r[f"mac{k}"]) for k in range(1,6)]}
        for _, r in df.iterrows()
    ]
    return templates.TemplateResponse("resultats_gh.html", {
        "request": request, "tirages": tirages, "jeux": JEUX_GH,
        "jeu_selectionne": jeu, "limit": limit,
    })


@app.get("/stats", response_class=HTMLResponse)
def page_stats(request: Request, pays: str = "ci"):
    if pays == "ci":
        df = charger_ci()
        cols_win = ["win1","win2","win3","win4","win5"]
        cols_mac = ["mac1","mac2","mac3","mac4","mac5"]
        label = "Côte d'Ivoire - Loto Bonheur"
    else:
        df = charger_gh()
        cols_win = ["win1","win2","win3","win4","win5"]
        cols_mac = ["mac1","mac2","mac3","mac4","mac5"]
        label = "Ghana - NLA"

    fw = freq_par_colonnes(df, cols_win)
    fm = freq_par_colonnes(df, cols_mac)
    cw, frw = chauds_froids(fw)
    cm, frm = chauds_froids(fm)

    return templates.TemplateResponse("stats.html", {
        "request": request, "pays": pays, "label": label,
        "nb": len(df),
        "freq_win": fw, "freq_mac": fm,
        "chauds_win": cw, "froids_win": frw,
        "chauds_mac": cm, "froids_mac": frm,
    })


@app.get("/saisie", response_class=HTMLResponse)
def page_saisie(request: Request, message: str | None = None, erreur: str | None = None):
    return templates.TemplateResponse("saisie.html", {
        "request": request, "jeux": JEUX_GH,
        "message": message, "erreur": erreur,
    })


@app.post("/saisie", response_class=HTMLResponse)
def post_saisie(
    request: Request,
    pays: str = Form(...),
    date: str = Form(...),
    jeu: str = Form(""),
    win: str = Form(...),
    mac: str = Form(...),
):
    try:
        datetime.strptime(date, "%Y-%m-%d")
        win_nums = [int(x) for x in win.split()]
        mac_nums = [int(x) for x in mac.split()]
        if len(win_nums) != 5 or len(mac_nums) != 5:
            raise ValueError("Il faut 5 Win et 5 Machine")
        if len(set(win_nums + mac_nums)) != 10 or not all(1 <= n <= 90 for n in win_nums + mac_nums):
            raise ValueError("10 numéros distincts entre 1 et 90")
    except ValueError as e:
        return RedirectResponse(f"/saisie?erreur={str(e)}", status_code=303)

    if pays == "ci":
        df = charger_ci()
        if date in df["date"].dt.strftime("%Y-%m-%d").tolist():
            return RedirectResponse("/saisie?erreur=Ce+tirage+CI+existe+déjà", status_code=303)
        with open(CI_FICHIER, "a", newline="") as f:
            csv.writer(f).writerow([date] + win_nums + mac_nums)
    else:
        if jeu not in JEUX_GH:
            return RedirectResponse("/saisie?erreur=Jeu+invalide", status_code=303)
        df = charger_gh()
        existants = set(zip(df["date"].dt.strftime("%Y-%m-%d"), df["jeu"]))
        if (date, jeu) in existants:
            return RedirectResponse("/saisie?erreur=Ce+tirage+GH+existe+déjà", status_code=303)
        with open(GH_FICHIER, "a", newline="") as f:
            csv.writer(f).writerow([date, jeu] + win_nums + mac_nums)

    return RedirectResponse("/saisie?message=Tirage+ajouté+avec+succès", status_code=303)


@app.get("/schema", response_class=HTMLResponse)
def page_schema(request: Request):
    return templates.TemplateResponse("schema.html", {"request": request, "resultat": None})


@app.post("/schema", response_class=HTMLResponse)
def post_schema(request: Request, numeros: str = Form(...), seuil: int = Form(2)):
    try:
        schema = [int(x) for x in numeros.split()]
        if len(schema) != 5 or len(set(schema)) != 5 or not all(1 <= n <= 90 for n in schema):
            raise ValueError("5 numéros distincts entre 1 et 90")
    except ValueError as e:
        return templates.TemplateResponse("schema.html", {
            "request": request, "resultat": None, "erreur": str(e),
        })

    df = charger_ci()
    schema_set = set(schema)
    correspondances = []
    for i, row in df.iterrows():
        win = {int(row[f"win{k}"]) for k in range(1,6)}
        communs = len(schema_set & win)
        if communs >= seuil:
            suivant = None
            if i + 1 < len(df):
                s = df.iloc[i + 1]
                suivant = {
                    "date": s["date"].strftime("%Y-%m-%d"),
                    "win": [int(s[f"win{k}"]) for k in range(1,6)],
                    "mac": [int(s[f"mac{k}"]) for k in range(1,6)],
                }
            correspondances.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "win": [int(row[f"win{k}"]) for k in range(1,6)],
                "mac": [int(row[f"mac{k}"]) for k in range(1,6)],
                "communs": communs,
                "suivant": suivant,
            })

    return templates.TemplateResponse("schema.html", {
        "request": request,
        "resultat": {
            "schema": sorted(schema),
            "seuil": seuil,
            "nb": len(correspondances),
            "correspondances": correspondances[:30],
        },
    })
