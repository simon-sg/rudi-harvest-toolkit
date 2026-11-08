"""Résolution d'une commune française par son code INSEE.

Deux sources officielles, sans repli hors-ligne :

- ``geo.api.gouv.fr`` pour l'identité, la géographie et le contour GeoJSON ;
- ``recherche-entreprises.api.gouv.fr`` pour le SIREN de la commune, avec le filtre
  **obligatoire** ``nature_juridique=7210`` (sans lui, plusieurs entités — syndicats,
  CCAS, etc. — remontent pour un même code commune).

Garde-fous explicites :

- les codes d'arrondissement municipal (Paris 75101-75120, Lyon 69381-69389,
  Marseille 13201-13216) sont refusés : ce ne sont pas des communes ;
- le code INSEE n'est **jamais** converti en ``int`` (Corse ``2A``/``2B``) ;
- une panne réseau ou une réponse HTTP en erreur lève une exception claire, jamais
  un résultat vide silencieux.

Usage :
    from rudi_harvest_toolkit.commune import resoudre_commune, resoudre_siren_commune

    commune = resoudre_commune("35120")
    siren = resoudre_siren_commune("35120")  # "213501208"
"""

from __future__ import annotations

import re

from .http import session

GEO_API = "https://geo.api.gouv.fr"
RECHERCHE_ENTREPRISES_API = "https://recherche-entreprises.api.gouv.fr"
NATURE_JURIDIQUE_COMMUNE = "7210"

# 2 chiffres (ou 2A/2B pour la Corse) + 3 chiffres. Pas d'int() : 2A/2B.
_RE_CODE_INSEE = re.compile(r"^(?:\d{2}|2[AB])\d{3}$")

_CHAMPS_GEO = (
    "nom",
    "code",
    "codeDepartement",
    "departement",
    "codeRegion",
    "region",
    "codesPostaux",
    "population",
    "centre",
)


class CodeInseeInvalide(ValueError):
    """Code INSEE mal formé."""


class ArrondissementMunicipalError(CodeInseeInvalide):
    """Le code désigne un arrondissement municipal, pas une commune."""


class CommuneIntrouvableError(LookupError):
    """Aucune commune (ou aucune entité de nature 7210) pour ce code."""


class PlusieursCommunesError(LookupError):
    """Le filtre ``nature_juridique=7210`` n'a pas isolé une entité unique."""


class ErreurReseauCommune(RuntimeError):
    """Échec réseau ou HTTP lors de l'interrogation d'une API de résolution."""


def _arrondissement_municipal(code: str) -> str | None:
    """Retourne le nom de la ville si ``code`` est un arrondissement municipal.

    Comparaison lexicographique sur des suffixes de 3 chiffres à largeur fixe :
    aucun ``int()`` sur le code (donc compatible Corse ``2A``/``2B``).
    """
    prefixe, suffixe = code[:2], code[2:]
    if prefixe == "75" and "101" <= suffixe <= "120":
        return "Paris"
    if prefixe == "69" and "381" <= suffixe <= "389":
        return "Lyon"
    if prefixe == "13" and "201" <= suffixe <= "216":
        return "Marseille"
    return None


def valider_code_insee(code_insee: object) -> str:
    """Valide et normalise un code INSEE (majuscules, sans espaces).

    Lève :class:`CodeInseeInvalide` (ou :class:`ArrondissementMunicipalError`) avant
    tout appel réseau.
    """
    if code_insee is None:
        raise CodeInseeInvalide("Code INSEE manquant.")
    code = str(code_insee).strip().upper()
    if not code:
        raise CodeInseeInvalide("Code INSEE vide.")
    if not _RE_CODE_INSEE.match(code):
        raise CodeInseeInvalide(
            f"Code INSEE {code_insee!r} invalide : attendu 5 caractères "
            "(2 chiffres ou 2A/2B, puis 3 chiffres — ex. 35120, 2A004)."
        )
    ville = _arrondissement_municipal(code)
    if ville:
        raise ArrondissementMunicipalError(
            f"Le code {code} est un arrondissement municipal de {ville}, pas une "
            "commune. Utilisez le code de la commune entière : Paris 75056, "
            "Lyon 69123, Marseille 13055."
        )
    return code


def _statut_http(exception: Exception, reponse=None) -> int | None:
    statut = getattr(getattr(exception, "response", None), "status_code", None)
    if statut is None:
        statut = getattr(reponse, "status_code", None)
    return statut


def resoudre_commune(
    code_insee: object,
    *,
    session_http=None,
    timeout: int = 30,
    inclure_contour: bool = True,
) -> dict:
    """Résout une commune via ``geo.api.gouv.fr``.

    Retourne un dict avec ``code_insee``, ``nom``, ``code_departement``,
    ``departement``, ``code_region``, ``region``, ``codes_postaux``, ``population``,
    ``centre`` et ``contour`` (géométrie GeoJSON, si ``inclure_contour``).

    Lève :class:`CommuneIntrouvableError` (404 / réponse vide),
    :class:`ErreurReseauCommune` (réseau ou autre statut HTTP).
    """
    code = valider_code_insee(code_insee)
    session_http = session_http or session
    champs = list(_CHAMPS_GEO)
    if inclure_contour:
        champs.append("contour")
    url = f"{GEO_API}/communes/{code}"

    try:
        reponse = session_http.get(url, params={"fields": ",".join(champs)}, timeout=timeout)
    except Exception as e:  # noqa: BLE001 — on veut un message explicite, pas un traceback opaque
        raise ErreurReseauCommune(
            f"Impossible d'interroger {GEO_API} pour la commune {code} : {e}"
        ) from e

    try:
        reponse.raise_for_status()
    except Exception as e:  # noqa: BLE001
        statut = _statut_http(e, reponse)
        if statut == 404:
            raise CommuneIntrouvableError(
                f"Aucune commune trouvée pour le code INSEE {code}."
            ) from e
        raise ErreurReseauCommune(
            f"Réponse HTTP {statut or '?'} de {GEO_API} pour la commune {code} : {e}"
        ) from e

    donnees = reponse.json()
    if not isinstance(donnees, dict) or not donnees.get("code"):
        raise CommuneIntrouvableError(
            f"Aucune commune trouvée pour le code INSEE {code} (réponse vide)."
        )

    departement = donnees.get("departement")
    region = donnees.get("region")
    resultat = {
        "code_insee": donnees.get("code") or code,
        "nom": donnees.get("nom"),
        "code_departement": donnees.get("codeDepartement"),
        "departement": departement.get("nom") if isinstance(departement, dict) else None,
        "code_region": donnees.get("codeRegion"),
        "region": region.get("nom") if isinstance(region, dict) else None,
        "codes_postaux": list(donnees.get("codesPostaux") or []),
        "population": donnees.get("population"),
        "centre": donnees.get("centre"),
    }
    if inclure_contour:
        resultat["contour"] = donnees.get("contour")
    return resultat


def resoudre_siren_commune(
    code_insee: object,
    *,
    session_http=None,
    timeout: int = 30,
) -> str:
    """Retourne le SIREN de la commune (entité ``nature_juridique=7210``).

    Le filtre ``nature_juridique=7210`` est **toujours** envoyé : sans lui, l'API
    renvoie plusieurs entités pour un même code commune. Si malgré le filtre
    plusieurs résultats reviennent, une erreur explicite est levée plutôt que d'en
    choisir un arbitrairement.
    """
    code = valider_code_insee(code_insee)
    session_http = session_http or session
    params = {
        "code_commune": code,
        "nature_juridique": NATURE_JURIDIQUE_COMMUNE,
        "page": 1,
        "per_page": 10,
    }
    url = f"{RECHERCHE_ENTREPRISES_API}/search"

    try:
        reponse = session_http.get(url, params=params, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise ErreurReseauCommune(
            f"Impossible d'interroger {RECHERCHE_ENTREPRISES_API} pour la commune "
            f"{code} : {e}"
        ) from e

    try:
        reponse.raise_for_status()
    except Exception as e:  # noqa: BLE001
        statut = _statut_http(e, reponse)
        raise ErreurReseauCommune(
            f"Réponse HTTP {statut or '?'} de {RECHERCHE_ENTREPRISES_API} pour la "
            f"commune {code} : {e}"
        ) from e

    donnees = reponse.json()
    resultats = list((donnees or {}).get("results") or [])
    total = donnees.get("total_results", len(resultats)) if isinstance(donnees, dict) else len(resultats)

    if not resultats:
        raise CommuneIntrouvableError(
            f"Aucune entité de nature juridique {NATURE_JURIDIQUE_COMMUNE} "
            f"(commune) trouvée pour le code INSEE {code}."
        )
    if len(resultats) > 1 or (isinstance(total, int) and total > 1):
        sirens = ", ".join(str(r.get("siren") or "?") for r in resultats[:10])
        raise PlusieursCommunesError(
            f"Le filtre nature_juridique={NATURE_JURIDIQUE_COMMUNE} n'a pas isolé "
            f"une entité unique pour {code} ({total} résultat(s) : {sirens})."
        )

    siren = resultats[0].get("siren")
    if not siren:
        raise CommuneIntrouvableError(
            f"Résultat sans SIREN pour la commune {code}."
        )
    return str(siren)
