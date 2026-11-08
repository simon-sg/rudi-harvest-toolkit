"""Client générique de l'API data.gouv.fr (datasets + ressources).

Généralise ``moissonneuse-batteuse/src/connectors/datagouv.py``. La différence
principale est la **sélection explicite** d'une ressource : l'ancienne API
``find_resource_by_format()`` renvoyait silencieusement le premier match par format,
ce qui devient faux dès qu'un dataset expose plusieurs ressources pertinentes (RNE,
IRVE, DVF…). Ici, l'appelant choisit par motif de nom, par date la plus récente ou
par index — et une ambiguïté lève une erreur au lieu de choisir arbitrairement.

Usage :
    from rudi_harvest_toolkit.datagouv import (
        get_dataset_metadata, lister_ressources, selectionner_ressource,
    )

    meta = get_dataset_metadata("elus-conseillers-municipaux")
    ressources = lister_ressources("elus-conseillers-municipaux")
    ressource = selectionner_ressource(meta, motif_nom=r"conseillers? municipaux")
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Mapping
from urllib.parse import quote

from .http import session

DATAGOUV_API = "https://www.data.gouv.fr/api/1"

_CHAMPS_DATE = ("last_modified", "metadata_modified_at", "created_at", "published")


class ErreurSelectionRessource(ValueError):
    """Erreur de sélection d'une ressource (mode absent, ambigu ou introuvable)."""


class RessourceIntrouvableError(ErreurSelectionRessource):
    """Aucune ressource ne correspond au critère demandé."""


class SelectionAmbigueError(ErreurSelectionRessource):
    """Plusieurs ressources correspondent : la sélection doit être affinée."""


def get_dataset_metadata(
    dataset_id: str,
    *,
    api_base: str = DATAGOUV_API,
    session_http=None,
    timeout: int = 30,
) -> dict:
    """Récupère les métadonnées d'un jeu de données par identifiant ou slug.

    Même contrat que l'ancienne fonction locale : retourne le JSON de l'API et
    propage les erreurs HTTP/réseau de ``requests``.
    """
    session_http = session_http or session
    url = f"{api_base.rstrip('/')}/datasets/{quote(str(dataset_id), safe='')}/"
    reponse = session_http.get(url, timeout=timeout)
    reponse.raise_for_status()
    return reponse.json()


def lister_ressources(dataset_id: str, **kwargs) -> list[dict]:
    """Liste les ressources d'un dataset (raccourci sur ``get_dataset_metadata``)."""
    return list(get_dataset_metadata(dataset_id, **kwargs).get("resources") or [])


def _extraire_ressources(ressources_ou_metadata) -> list[dict]:
    if isinstance(ressources_ou_metadata, Mapping):
        return list(ressources_ou_metadata.get("resources") or [])
    return list(ressources_ou_metadata or [])


def _parser_date(valeur) -> datetime:
    """Parse une date ISO data.gouv.fr en ``datetime`` UTC (naïf → supposé UTC)."""
    if isinstance(valeur, datetime):
        date = valeur
    else:
        texte = str(valeur).strip()
        if texte.endswith("Z"):
            texte = texte[:-1] + "+00:00"
        date = datetime.fromisoformat(texte)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc)


def _date_ressource(ressource: Mapping) -> datetime | None:
    for cle in _CHAMPS_DATE:
        valeur = ressource.get(cle)
        if not valeur:
            continue
        try:
            return _parser_date(valeur)
        except (TypeError, ValueError):
            continue
    return None


def _decrire(ressource: Mapping) -> str:
    titre = ressource.get("title") or ressource.get("url") or "(sans titre)"
    identifiant = ressource.get("id") or "?"
    return f"{titre!r} (id={identifiant})"


def selectionner_ressource(
    ressources_ou_metadata,
    *,
    motif_nom: str | None = None,
    index: int | None = None,
    la_plus_recente: bool = False,
    format: str | None = None,
) -> dict:
    """Sélectionne **explicitement** une ressource dans un dataset.

    Un seul mode de sélection doit être fourni :

    - ``motif_nom`` : expression régulière recherchée dans le titre (puis dans
      l'URL en repli). Une seule correspondance attendue, sinon
      :class:`SelectionAmbigueError` (jamais de « premier match » silencieux).
    - ``index`` : position dans la liste (éventuellement filtrée par ``format``).
    - ``la_plus_recente=True`` : ressource dont la date la plus récente
      (``last_modified``, puis ``metadata_modified_at``/``created_at``/``published``)
      est maximale.

    ``format`` restreint au préalable la liste au format demandé (``csv``, ``json``…).
    """
    modes = sum(
        [
            motif_nom is not None,
            index is not None,
            bool(la_plus_recente),
        ]
    )
    if modes != 1:
        raise ErreurSelectionRessource(
            "Choisir exactement un mode de sélection : motif_nom, index ou "
            "la_plus_recente=True (aucun mode implicite « premier match »)."
        )

    liste = _extraire_ressources(ressources_ou_metadata)
    if format is not None:
        format_cible = str(format).lower()
        liste = [r for r in liste if str(r.get("format") or "").lower() == format_cible]

    if not liste:
        raise RessourceIntrouvableError(
            f"Aucune ressource disponible{' au format ' + str(format) if format else ''}."
        )

    if index is not None:
        try:
            return liste[index]
        except IndexError as e:
            raise RessourceIntrouvableError(
                f"Index {index} hors bornes : {len(liste)} ressource(s) disponible(s)."
            ) from e

    if motif_nom is not None:
        motif = re.compile(motif_nom, re.IGNORECASE)
        correspondances = [
            r for r in liste if motif.search(str(r.get("title") or ""))
        ]
        if not correspondances:
            # Repli utile : certaines ressources n'ont pas de titre mais une URL parlante.
            correspondances = [
                r for r in liste if motif.search(str(r.get("url") or ""))
            ]
        if not correspondances:
            raise RessourceIntrouvableError(
                f"Aucune ressource ne correspond au motif {motif_nom!r}. "
                f"Candidates : {', '.join(_decrire(r) for r in liste[:20])}"
            )
        if len(correspondances) > 1:
            raise SelectionAmbigueError(
                f"Motif {motif_nom!r} ambigu : {len(correspondances)} ressources "
                f"correspondent ({', '.join(_decrire(r) for r in correspondances[:10])}). "
                "Affiner le motif ou sélectionner par index."
            )
        return correspondances[0]

    # la_plus_recente=True
    datees = []
    for position, ressource in enumerate(liste):
        date = _date_ressource(ressource)
        if date is not None:
            datees.append((date, position, ressource))
    if not datees:
        raise RessourceIntrouvableError(
            "Aucune ressource ne porte de date exploitable "
            f"({', '.join(_CHAMPS_DATE)})."
        )
    # En cas d'égalité de date, la première ressource de la liste gagne.
    return max(datees, key=lambda item: (item[0], -item[1]))[2]
