"""Média RUDI ``FILE`` hybride : empreinte distante + URL distante conservée.

Généralise le pattern déjà en production dans
``moissonneur-ods/src/moissonneur_ods/mode.py``
(``_empreinte_distante()`` / ``_media_file_distant()`` / ``_media_id``) :

- l'URL est lue **une fois en flux** pour calculer SHA-256 et taille, sans jamais
  écrire le fichier sur disque ni le stocker sur notre nœud ;
- ``connector.url`` reste l'URL distante (un ``FILE`` est requis pour que le portail
  RUDI affiche un bouton télécharger) ;
- ``media_id`` est un UUIDv5 déterministe (même ``local_id`` + même URL → même id)
  dont les nibbles version/variant sont forcés en v4, exactement comme
  ``moissonneur-ods::_media_id`` — condition de la stabilité incrémentale ;
- ``file_size`` et ``checksum.hash`` sont renseignés, de sorte que
  ``rudi_client._media_file_deja_complet()`` reconnaisse le média comme complet et
  ne tente jamais de l'uploader.

Usage :
    from rudi_harvest_toolkit.fichier_hybride import construire_media_hybride

    media = construire_media_hybride(
        local_id="mon-dataset",
        url="https://exemple.fr/export.csv?where=code_commune%3D35120",
        media_name="export.csv",
        media_caption="Export filtré sur la commune",
        file_type="text/csv",
    )
"""

from __future__ import annotations

import hashlib
import os
import uuid
from urllib.parse import unquote, urlparse

from .http import session

_ALGO_EMPREINTE = "SHA-256"
_TAILLE_MORCEAU = 65536
_PREFIXE_MEDIA = "ods-media"

# 500 Mo — même limite que le nœud RUDI (et que moissonneur-ods).
TAILLE_MAX_DEFAUT = 500 * 1024 * 1024

# Miroir de l'énumération fermée du nœud (rudi-catalog, FileTypes.js). Exposé pour
# que l'appelant puisse vérifier un type MIME avant de construire le média ; le
# constructeur ne l'impose pas (un média hybride peut être bâti avec un type absent).
TYPES_FICHIER_ACCEPTES = frozenset({
    "application/epub+zip", "application/geo+json", "application/geopackage+sqlite3",
    "application/graphql", "application/gzip", "application/javascript", "application/json",
    "application/ld+json", "application/msword", "application/netcdf", "application/octet-stream",
    "application/pdf", "application/sql", "application/vnd.api+json", "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint", "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet", "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/x-7z-compressed", "application/x-bzip", "application/x-bzip2",
    "application/x-executable", "application/x-tar", "application/x-www-form-urlencoded",
    "application/xml", "application/zip", "application/zstd",
    "audio/aac", "audio/m4a", "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm",
    "font/otf", "font/ttf",
    "image/apng", "image/bmp", "image/flif", "image/gif", "image/jpeg", "image/png",
    "image/tiff", "image/vnd.microsoft.icon", "image/webp", "image/x-mng",
    "multipart/form-data",
    "text/css", "text/csv", "text/html", "text/markdown", "text/php", "text/plain",
    "text/x-yaml", "text/xml",
    "video/3gpp", "video/mp4", "video/mpeg", "video/ogg", "video/quicktime", "video/webm",
    "video/x-matroska", "video/x-ms-wmv", "video/x-msvideo",
})


class ErreurEmpreinteDistante(RuntimeError):
    """Échec de lecture de l'URL distante pendant le calcul d'empreinte."""


class FichierTropVolumineux(ErreurEmpreinteDistante):
    """Le fichier distant dépasse ``taille_max`` (aucun contenu stocké)."""


def type_fichier_accepte(mimetype: str | None) -> bool:
    """Vrai si ``mimetype`` appartient à l'énumération acceptée par le nœud RUDI."""
    return mimetype in TYPES_FICHIER_ACCEPTES


def nom_depuis_url(url: str) -> str:
    """Nom de fichier lisible déduit du chemin de l'URL (décodé, sans requête)."""
    chemin = urlparse(url).path
    return unquote(os.path.basename(chemin)) or "donnees"


def media_id_hybride(local_id: str, cle: str) -> str:
    """UUID déterministe forcé au format v4 (schéma exact de ``moissonneur-ods``).

    ``uuid5`` seul ne satisfait jamais ``UUID.version == 4``, exigé par
    ``rudi_node_write.check_is_uuid4``. On force donc les nibbles version/variant
    tout en conservant la stabilité « même entrée → même id ».
    """
    brut = uuid.uuid5(uuid.NAMESPACE_URL, f"{local_id}/{_PREFIXE_MEDIA}/{cle}")
    octets = bytearray(brut.bytes)
    octets[6] = (octets[6] & 0x0F) | 0x40  # version = 4
    octets[8] = (octets[8] & 0x3F) | 0x80  # variant = 10xx
    return str(uuid.UUID(bytes=bytes(octets)))


def empreinte_distante(
    url: str,
    *,
    taille_max: int | None = TAILLE_MAX_DEFAUT,
    session_http=None,
    timeout: int = 120,
) -> dict:
    """Calcule ``SHA-256`` et taille d'une URL en flux, sans écriture disque.

    Retourne ``{"algo": "SHA-256", "hash": <hex>, "taille": <octets>}``.

    - ``taille_max=None`` désactive le garde-fou de taille ;
    - lève :class:`FichierTropVolumineux` si la taille annoncée ou lue dépasse ;
    - lève :class:`ErreurEmpreinteDistante` sur échec réseau/HTTP.
    """
    session_http = session_http or session
    try:
        reponse = session_http.get(url, stream=True, timeout=timeout, allow_redirects=True)
        reponse.raise_for_status()
    except Exception as e:  # noqa: BLE001 — message explicite, jamais silencieux
        raise ErreurEmpreinteDistante(
            f"Échec de lecture distante de {url} : {e}"
        ) from e

    try:
        longueur = reponse.headers.get("Content-Length")
        if (
            longueur is not None
            and str(longueur).isdigit()
            and taille_max is not None
            and int(longueur) > taille_max
        ):
            raise FichierTropVolumineux(
                f"Fichier distant {url} trop volumineux : {longueur} octets "
                f"(plafond {taille_max})."
            )

        empreinte = hashlib.sha256()
        total = 0
        try:
            for morceau in reponse.iter_content(chunk_size=_TAILLE_MORCEAU):
                if not morceau:
                    continue
                total += len(morceau)
                if taille_max is not None and total > taille_max:
                    raise FichierTropVolumineux(
                        f"Fichier distant {url} trop volumineux : plus de "
                        f"{taille_max} octets lus (plafond {taille_max})."
                    )
                empreinte.update(morceau)
        except FichierTropVolumineux:
            raise
        except Exception as e:  # noqa: BLE001
            raise ErreurEmpreinteDistante(
                f"Lecture interrompue de {url} : {e}"
            ) from e
    finally:
        fermer = getattr(reponse, "close", None)
        if callable(fermer):
            fermer()

    return {"algo": _ALGO_EMPREINTE, "hash": empreinte.hexdigest(), "taille": total}


def construire_media_hybride(
    local_id: str,
    url: str,
    *,
    media_name: str | None = None,
    media_caption: str | None = None,
    file_type: str | None = None,
    empreinte: dict | None = None,
    taille_max: int | None = TAILLE_MAX_DEFAUT,
    session_http=None,
    timeout: int = 120,
) -> dict:
    """Construit un média RUDI ``FILE`` hybride complet.

    ``connector.url`` reste l'URL distante. Si ``empreinte`` n'est pas fournie, elle
    est calculée via :func:`empreinte_distante` (une seule lecture en flux, zéro
    écriture disque). Le résultat satisfait
    ``rudi_client._media_file_deja_complet()`` (``file_size`` + ``checksum.hash``).
    """
    if not local_id:
        raise ValueError("local_id est obligatoire pour construire un média hybride.")
    if not url:
        raise ValueError("url est obligatoire pour construire un média hybride.")

    if empreinte is None:
        empreinte = empreinte_distante(
            url, taille_max=taille_max, session_http=session_http, timeout=timeout
        )
    if "hash" not in empreinte or "taille" not in empreinte:
        raise ValueError("empreinte doit contenir au moins 'hash' et 'taille'.")

    nom = media_name or nom_depuis_url(url)
    media = {
        "media_id": media_id_hybride(local_id, url),
        "media_type": "FILE",
        "media_name": nom,
        "media_caption": media_caption or nom,
        "connector": {"url": url, "interface_contract": "dwnl"},
        "file_size": int(empreinte["taille"]),
        "checksum": {
            "algo": empreinte.get("algo", _ALGO_EMPREINTE),
            "hash": empreinte["hash"],
        },
        "file_storage_status": "available",
    }
    if file_type:
        media["file_type"] = file_type
    return media


__all__ = [
    "TAILLE_MAX_DEFAUT",
    "TYPES_FICHIER_ACCEPTES",
    "ErreurEmpreinteDistante",
    "FichierTropVolumineux",
    "construire_media_hybride",
    "empreinte_distante",
    "media_id_hybride",
    "nom_depuis_url",
    "type_fichier_accepte",
]
