"""Maire actuel d'une commune, via le Répertoire National des Élus (RNE, Ministère
de l'Intérieur) — source officielle et à jour, préférée à Wikidata (propriété P6, qui
reste affichée indéfiniment sans aucun signal d'obsolescence après une élection non
répercutée sur Wikidata)."""

from __future__ import annotations

from .datagouv import get_dataset_metadata, selectionner_ressource
from .download_cache import telecharger
from .http import session
from .tabular import filtrer_csv

_DATASET_ID = "repertoire-national-des-elus-1"
_MOTIF_RESSOURCE = r"conseiller[s]?-municipa"
_COLONNE_COMMUNE = "Code de la commune"
_LIBELLE_MAIRE = "Maire"


def maire_actuel(
    code_insee: str, *, session_http=None, dossier_cache: str | None = None,
) -> dict | None:
    """``{"nom", "prenom", "date_debut_fonction"}`` pour le maire en exercice de la
    commune, ou ``None`` si absent/échec réseau (toujours silencieux, jamais bloquant
    pour l'appelant). ``dossier_cache`` partagé avec un éventuel module élus du même
    run évite un second téléchargement du fichier national (~65 Mo)."""
    session_http = session_http or session
    try:
        metadata = get_dataset_metadata(_DATASET_ID, session_http=session_http)
        ressource = selectionner_ressource(metadata, motif_nom=_MOTIF_RESSOURCE)
        chemin_cache = telecharger(
            ressource["url"], dossier=dossier_cache or ".cache_rne", session_http=session_http,
        )
        for ligne in filtrer_csv(chemin_cache, _COLONNE_COMMUNE, code_insee):
            if ligne.get("Libellé de la fonction") == _LIBELLE_MAIRE:
                return {
                    "nom": ligne.get("Nom de l'élu"),
                    "prenom": ligne.get("Prénom de l'élu"),
                    "date_debut_fonction": ligne.get("Date de début de la fonction"),
                }
    except Exception:
        pass
    return None


__all__ = ["maire_actuel"]
