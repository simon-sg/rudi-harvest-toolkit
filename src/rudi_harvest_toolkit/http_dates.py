"""Sonde best-effort de la date de dernière modification d'une ressource HTTP (v4
de rudi-commune-starterkit, Axe 2).

Indépendant de :func:`download_cache.telecharger` et de son cache — un simple
sondage d'en-tête, jamais bloquant, jamais deviné. **Ne réutilise jamais**
:func:`pivot.parser_date_http` : cette dernière retourne ``datetime.now(UTC)`` sur une
date non parsable (repli pensé pour ne jamais planter l'assemblage d'un dataset),
ce qui publierait ici une date inventée — l'inverse de ce que ce module garantit.
"""

from __future__ import annotations

import datetime
from email.utils import parsedate_to_datetime

from .http import session as _session_defaut

_CODES_REPLI_GET = (405, 501)


def entete_derniere_modification(
    url: str,
    *,
    session_http=None,
    timeout: int = 15,
) -> str | None:
    """Sonde l'en-tête ``Last-Modified`` de ``url`` (HEAD, repli GET si HEAD est
    refusé) et retourne une date ISO 8601 UTC, ou ``None`` sur tout échec.

    Jamais bloquant : une exception réseau, un statut HTTP d'erreur (403/404/5xx…),
    une absence d'en-tête ou une valeur non parsable retournent tous ``None`` —
    jamais levé. Le repli GET n'est tenté que si HEAD renvoie 405/501 (méthode
    refusée), jamais sur un simple statut d'erreur.
    """
    session_http = session_http or _session_defaut
    try:
        reponse = session_http.head(url, allow_redirects=True, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None

    if reponse.status_code in _CODES_REPLI_GET:
        try:
            reponse = session_http.get(
                url, allow_redirects=True, timeout=timeout, stream=True,
            )
            reponse.close()
        except Exception:  # noqa: BLE001
            return None

    if reponse.status_code >= 400:
        return None

    return _parser_date_http_stricte(reponse.headers.get("Last-Modified"))


def _parser_date_http_stricte(date_str: str | None) -> str | None:
    """Parseur strict, local à ce module : ``None`` sur toute entrée absente ou non
    parsable — jamais une date inventée (contrairement à ``pivot.parser_date_http``)."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["entete_derniere_modification"]
