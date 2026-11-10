"""Résumé Wikipédia d'une commune française, désambiguïsée par code INSEE via Wikidata
(jamais par nom — ambigu pour les communes homonymes, ex. plusieurs « Saint-Martin »).

Pipeline : code INSEE -> P374 (Wikidata) -> QID -> sitelink frwiki -> extrait complet
via l'API MediaWiki (``action=query&prop=extracts&exintro=1``, pas ``page/summary`` qui
ne retourne que 2-4 phrases — insuffisant face à la demande "1-2 paragraphes").
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import quote, unquote

from .commune import valider_code_insee
from .http import session

_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_WIKIPEDIA_API = "https://fr.wikipedia.org/w/api.php"
_TIMEOUT = 15
_TTL_JOURS_DEFAUT = 30
# Abaissé de 250 à 80 (v3, retour utilisateur sur Acigné) : un intro réel et
# substantiel peut faire moins de 250 caractères pour une petite commune (ex. Acigné,
# 192 caractères, 2 phrases factuelles) — 250 rejetait à tort ce cas, pas seulement les
# ébauches véritablement vides. Le second paragraphe (maire/gentilé/superficie,
# construit par description_commune.py côté starterkit) compense un intro court.
_LONGUEUR_MIN_DEFAUT = 80
# Q484170 = "commune de France" (Wikidata) — tie-break de désambiguïsation quand
# plusieurs entités Wikidata portent le même P374 (vérifié : le code 35096 en a 2).
_QID_COMMUNE_DE_FRANCE = "Q484170"

_SPARQL_TEMPLATE = """
SELECT ?item ?article ?type WHERE {{
  ?item wdt:P374 "{code_insee}".
  OPTIONAL {{ ?item wdt:P31 ?type. }}
  OPTIONAL {{ ?article schema:about ?item; schema:isPartOf <https://fr.wikipedia.org/>. }}
}}
"""

# P2046 = superficie (unité quasi toujours km² pour une commune française, jamais
# vérifiée par requête séparée — gain négligeable face au risque de 2e aller-retour).
# P1549 = gentilé (monolingue fr) — souvent absent, jamais deviné : omis si absent.
_SPARQL_INFOS_TEMPLATE = """
SELECT ?superficie ?gentile WHERE {{
  OPTIONAL {{ wd:{qid} wdt:P2046 ?superficie. }}
  OPTIONAL {{ wd:{qid} wdt:P1549 ?gentile. FILTER(LANG(?gentile) = "fr") }}
}}
"""


def _chemin_cache(dossier_cache: str, code_insee: str) -> str:
    return os.path.join(dossier_cache, f"wikipedia_commune_{code_insee}.json")


def _lire_cache(dossier_cache: str, code_insee: str, ttl_jours: float) -> dict | None:
    chemin = _chemin_cache(dossier_cache, code_insee)
    if not os.path.isfile(chemin):
        return None
    age_jours = (time.time() - os.path.getmtime(chemin)) / 86400
    if age_jours > ttl_jours:
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _ecrire_cache(dossier_cache: str, code_insee: str, data: dict) -> None:
    """Écriture atomique (tmp + os.replace) — plusieurs process peuvent moissonner des
    communes différentes en parallèle et partager ce même répertoire de cache."""
    os.makedirs(dossier_cache, exist_ok=True)
    chemin = _chemin_cache(dossier_cache, code_insee)
    tmp = f"{chemin}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, chemin)


def _titre_depuis_url_article(url_article: str) -> str | None:
    """Extrait le titre de page depuis l'URL frwiki renvoyée par le SPARQL
    (``https://fr.wikipedia.org/wiki/<titre>``, encodée) — jamais de concaténation
    brute, les titres de commune peuvent porter accents/apostrophes/``&``/``#``."""
    m = re.match(r"^https?://fr\.wikipedia\.org/wiki/(.+)$", url_article)
    if not m:
        return None
    return unquote(m.group(1)).replace("_", " ")


def _qid_depuis_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _choisir_entite(bindings: list[dict]) -> dict | None:
    """Désambiguïse une liste de résultats SPARQL (plusieurs entités Wikidata peuvent
    partager le même P374) : ne retient que celles ayant un sitelink frwiki, préfère
    ``P31 = Q484170`` (« commune de France »), puis la plus petite QID (stabilité du
    cache/hash entre deux runs)."""
    candidats = [b for b in bindings if b.get("article", {}).get("value")]
    if not candidats:
        return None

    def _est_commune(b: dict) -> bool:
        return _qid_depuis_uri(b.get("type", {}).get("value", "")) == _QID_COMMUNE_DE_FRANCE

    candidats.sort(key=lambda b: (not _est_commune(b), _qid_depuis_uri(b["item"]["value"])))
    return candidats[0]


def _resoudre_entite_wikidata(code_insee: str, *, session_http) -> dict | None:
    reponse = session_http.get(
        _WIKIDATA_SPARQL,
        params={"query": _SPARQL_TEMPLATE.format(code_insee=code_insee), "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=_TIMEOUT,
    )
    reponse.raise_for_status()
    bindings = reponse.json().get("results", {}).get("bindings", [])
    return _choisir_entite(bindings)


def _extrait_wikipedia(titre: str, *, session_http) -> dict | None:
    reponse = session_http.get(
        _WIKIPEDIA_API,
        params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
            "redirects": 1, "titles": titre, "format": "json",
        },
        timeout=_TIMEOUT,
    )
    reponse.raise_for_status()
    pages = reponse.json().get("query", {}).get("pages", {})
    for page in pages.values():
        if "missing" in page:
            continue
        extrait = (page.get("extract") or "").strip()
        if extrait:
            return {"titre": page.get("title") or titre, "extrait": extrait}
    return None


def _infos_complementaires_wikidata(qid: str, *, session_http) -> dict:
    """Superficie (km², P2046) et gentilé (P1549, fr) pour ce QID déjà résolu — absents
    si non renseignés sur Wikidata, jamais devinés. Best-effort : une erreur réseau ici
    ne doit pas invalider le résumé Wikipédia déjà obtenu."""
    try:
        reponse = session_http.get(
            _WIKIDATA_SPARQL,
            params={"query": _SPARQL_INFOS_TEMPLATE.format(qid=qid), "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=_TIMEOUT,
        )
        reponse.raise_for_status()
        bindings = reponse.json().get("results", {}).get("bindings", [])
    except Exception:
        return {}
    if not bindings:
        return {}
    b = bindings[0]
    infos: dict = {}
    if "superficie" in b:
        try:
            infos["superficie_km2"] = float(b["superficie"]["value"])
        except (KeyError, ValueError):
            pass
    if "gentile" in b:
        infos["gentile"] = b["gentile"]["value"]
    return infos


def resumer_commune_wikipedia(
    code_insee: str,
    *,
    session_http=None,
    dossier_cache: str | None = None,
    ttl_jours: float = _TTL_JOURS_DEFAUT,
    longueur_min: int = _LONGUEUR_MIN_DEFAUT,
) -> dict | None:
    """Résout le(s) QID Wikidata via P374 (code INSEE commune), désambiguïse si
    plusieurs résultats, récupère le sitelink frwiki, puis l'intro complète via
    ``action=query&prop=extracts&exintro=1&explaintext=1`` (pas ``page/summary``, qui
    ne retourne que 2-4 phrases — insuffisant face à la demande "1-2 paragraphes").

    Retourne ``{"caption", "summary", "url", "qid", "superficie_km2"?, "gentile"?}`` ou
    ``None`` si absent, trop court (< ``longueur_min`` caractères — garde-fou contre les
    ébauches réellement vides) ou en cas d'échec réseau/parsing (toujours silencieux,
    jamais bloquant pour l'appelant). ``superficie_km2``/``gentile`` (Wikidata P2046/
    P1549) sont omis s'ils ne sont pas renseignés sur Wikidata — jamais devinés ; un
    échec de cette requête complémentaire n'invalide pas le résumé déjà obtenu.
    Cache indexé par ``code_insee`` (clé stable, non ambiguë contrairement à un nom),
    écriture atomique (tmp + ``os.replace``, plusieurs process peuvent tourner) — omis
    si ``dossier_cache`` n'est pas fourni.
    """
    code_insee = valider_code_insee(code_insee)
    session_http = session_http or session

    if dossier_cache:
        cache = _lire_cache(dossier_cache, code_insee, ttl_jours)
        if cache is not None:
            return cache or None

    resultat: dict | None = None
    try:
        entite = _resoudre_entite_wikidata(code_insee, session_http=session_http)
        if entite:
            titre = _titre_depuis_url_article(entite["article"]["value"])
            if titre:
                extrait = _extrait_wikipedia(titre, session_http=session_http)
                if extrait and len(extrait["extrait"]) >= longueur_min:
                    qid = _qid_depuis_uri(entite["item"]["value"])
                    resultat = {
                        "caption": extrait["titre"],
                        "summary": extrait["extrait"],
                        "url": "https://fr.wikipedia.org/wiki/"
                        + quote(extrait["titre"].replace(" ", "_")),
                        "qid": qid,
                        **_infos_complementaires_wikidata(qid, session_http=session_http),
                    }
    except Exception:
        resultat = None

    if dossier_cache:
        _ecrire_cache(dossier_cache, code_insee, resultat or {})
    return resultat


__all__ = ["resumer_commune_wikipedia"]
