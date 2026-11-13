"""Téléchargement HTTP en flux avec cache disque (clé = MD5 de l'URL, TTL).

Généralise ``moissonneuse-batteuse/src/connectors/download.py``. Ce module reste
volontairement **simple** : il n'émet **aucune** requête conditionnelle
``If-None-Match``/``If-Modified-Since`` (l'original n'en avait pas non plus) ; la
fraîcheur est assurée uniquement par un TTL sur la date de modification du fichier
en cache.

Usage :
    from rudi_harvest_toolkit.download_cache import telecharger

    chemin = telecharger("https://exemple.fr/ban.csv.gz", dossier="/tmp/cache")
    # deuxième appel dans le TTL : retourne le même chemin sans requête réseau.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import time

import requests

from .http import session

TTL_JOURS_DEFAUT = 30
_TAILLE_MORCEAU = 1024 * 1024
_ENV_CACHE = "RUDI_HARVEST_CACHE"
# Backlog rudi-commune-starterkit (fragilité #3, 2026-11-13) : une coupure réseau
# EN COURS de flux (ConnectionError/ChunkedEncodingError, « Connection broken »,
# observée en conditions réelles sur le téléchargement national DVF de 609 Mo) ne
# déclenchait aucune reprise — seules les erreurs avant réception de la réponse HTTP
# (429/5xx) étaient retentées ailleurs. Reprend depuis le début (pas de Range/resume :
# demanderait de vérifier le support serveur + un ETag pour éviter de reprendre sur un
# fichier changé entre-temps — hors scope ici, fonction partagée par ~10 modules).
_MAX_TENTATIVES_FLUX = 3
_PAUSE_ENTRE_TENTATIVES_S = 2


class ErreurTelechargement(RuntimeError):
    """Échec réseau/HTTP pendant le téléchargement (jamais silencieux)."""


def dossier_cache_defaut() -> str:
    """Répertoire de cache par défaut (``$RUDI_HARVEST_CACHE`` ou XDG cache)."""
    force = os.environ.get(_ENV_CACHE)
    if force:
        return force
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "rudi-harvest-toolkit")


def chemin_cache(url: str, dossier: str | os.PathLike | None = None) -> str:
    """Chemin du fichier de cache pour ``url`` (nom = MD5 de l'URL, sans extension)."""
    dossier = os.fspath(dossier) if dossier is not None else dossier_cache_defaut()
    cle = hashlib.md5(str(url).encode("utf-8")).hexdigest()
    return os.path.join(dossier, cle)


def _est_expire(chemin: str, ttl_jours: float | None) -> bool:
    if ttl_jours is None:
        return False
    age = time.time() - os.path.getmtime(chemin)
    return age > ttl_jours * 86400


def telecharger(
    url: str,
    *,
    dossier: str | os.PathLike | None = None,
    ttl_jours: float | None = TTL_JOURS_DEFAUT,
    session_http=None,
    timeout: int = 60,
    plafond_mo: float | None = None,
    verbose: bool = False,
) -> str:
    """Télécharge ``url`` en flux vers le cache disque et retourne le chemin.

    - cache valide (âge ≤ ``ttl_jours``) : aucune requête réseau ;
    - ``ttl_jours=None`` : cache immortel ;
    - ``plafond_mo`` : tronque le téléchargement au-delà (utile pour échantillonner
      un gros fichier). Le fichier partiel est alors mis en cache **tel quel** —
      ne pas utiliser ce mode pour un fichier destiné à être publié.

    Lève :class:`ErreurTelechargement` sur échec réseau/HTTP, après nettoyage du
    fichier temporaire. Aucune requête conditionnelle n'est envoyée.

    Une coupure réseau **en cours de flux** (``ConnectionError``/
    ``ChunkedEncodingError``, pas seulement un statut HTTP 429/5xx avant réception
    de la réponse) déclenche jusqu'à :data:`_MAX_TENTATIVES_FLUX` tentatives — chacune
    reprend le téléchargement depuis le début (pas de ``Range``/reprise partielle).
    """
    chemin = chemin_cache(url, dossier)
    if os.path.exists(chemin):
        if not _est_expire(chemin, ttl_jours):
            if verbose:
                taille_mo = os.path.getsize(chemin) / 1024 / 1024
                print(f"  Cache ({taille_mo:.1f} Mo) : {url}")
            return chemin
        if verbose:
            print(f"  Cache expiré, re-téléchargement : {url}")
        os.remove(chemin)

    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    session_http = session_http or session
    chemin_tmp = chemin + ".tmp"

    for tentative in range(1, _MAX_TENTATIVES_FLUX + 1):
        try:
            reponse = session_http.get(url, stream=True, timeout=timeout)
            reponse.raise_for_status()
        except Exception as e:
            raise ErreurTelechargement(f"Échec du téléchargement de {url} : {e}") from e

        total = 0
        try:
            with open(chemin_tmp, "wb") as fichier:
                for morceau in reponse.iter_content(chunk_size=_TAILLE_MORCEAU):
                    if not morceau:
                        continue
                    fichier.write(morceau)
                    total += len(morceau)
                    if verbose:
                        print(f"  {total / 1024 / 1024:.1f} Mo…", end="\r")
                    if plafond_mo is not None and total >= plafond_mo * 1024 * 1024:
                        if verbose:
                            print(f"\n  Plafond {plafond_mo} Mo atteint — fichier partiel.")
                        break
            os.replace(chemin_tmp, chemin)
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
            try:
                os.remove(chemin_tmp)
            except OSError:
                pass
            if tentative < _MAX_TENTATIVES_FLUX:
                if verbose:
                    print(f"\n  Connexion coupée en cours de flux ({e}) — nouvelle "
                          f"tentative ({tentative + 1}/{_MAX_TENTATIVES_FLUX})…")
                time.sleep(_PAUSE_ENTRE_TENTATIVES_S)
                continue
            raise ErreurTelechargement(
                f"Échec du téléchargement de {url} après {_MAX_TENTATIVES_FLUX} "
                f"tentatives (connexion coupée en cours de flux à chaque fois) : {e}"
            ) from e
        except Exception as e:
            try:
                os.remove(chemin_tmp)
            except OSError:
                pass
            raise ErreurTelechargement(f"Échec de l'écriture du cache pour {url} : {e}") from e
        finally:
            fermer = getattr(reponse, "close", None)
            if callable(fermer):
                fermer()
        break  # succès — pas besoin d'une autre tentative

    if verbose:
        print(f"\n  Téléchargé : {chemin} ({total / 1024 / 1024:.1f} Mo)")
    return chemin


def purger_cache(
    *,
    dossier: str | os.PathLike | None = None,
    jours: float = TTL_JOURS_DEFAUT,
) -> int:
    """Supprime les fichiers du cache plus vieux que ``jours`` ; retourne le nombre."""
    dossier = os.fspath(dossier) if dossier is not None else dossier_cache_defaut()
    if not os.path.isdir(dossier):
        return 0
    limite = time.time() - jours * 86400
    supprimes = 0
    for nom in os.listdir(dossier):
        chemin = os.path.join(dossier, nom)
        if os.path.isfile(chemin) and os.path.getmtime(chemin) < limite:
            try:
                os.remove(chemin)
            except OSError:
                continue
            supprimes += 1
    return supprimes


def invalider(url: str, *, dossier: str | os.PathLike | None = None) -> bool:
    """Supprime l'entrée de cache de ``url`` ; ``True`` si un fichier a été retiré."""
    chemin = chemin_cache(url, dossier)
    if os.path.exists(chemin):
        os.remove(chemin)
        return True
    return False


def date_fichier_cache(chemin: str) -> str | None:
    """Date de dernière modification (mtime) de ``chemin``, en ISO 8601 UTC, ou
    ``None`` si le fichier n'existe pas (v4 de rudi-commune-starterkit, Axe 2).

    Mécanisme retenu pour les sources sans date fiable côté serveur (BAN, DVF) :
    la mtime du fichier **en cache** (pas une sonde HEAD à chaque run) garantit par
    construction que la date affichée ne dépasse jamais l'âge réel du contenu
    effectivement publié — un fichier servi depuis le cache ne peut jamais afficher
    une date plus récente que son contenu.
    """
    try:
        horodatage = os.path.getmtime(chemin)
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(
        horodatage, tz=datetime.timezone.utc,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "TTL_JOURS_DEFAUT",
    "ErreurTelechargement",
    "chemin_cache",
    "date_fichier_cache",
    "dossier_cache_defaut",
    "invalider",
    "purger_cache",
    "telecharger",
]
