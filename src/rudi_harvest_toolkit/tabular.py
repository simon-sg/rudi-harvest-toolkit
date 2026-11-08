"""Lecture CSV en flux et filtrage générique « valeur de colonne == cible ».

Généralise le moteur de ``moissonneuse-batteuse/src/harvest_batch.py`` (parsing,
détection d'encodage/délimiteur, décompression gzip à la volée) **sans** la cascade
Rennes Métropole à 8 niveaux : ici, un seul critère exact, résolu sur un nom de
colonne tolérant aux accents/casse/underscores.

Le fichier n'est jamais chargé entièrement en mémoire : les lignes sont lues au fil
de l'eau depuis un fichier local, une URL HTTP(S) ou un objet binaire déjà ouvert.
Un fichier ``.gz`` est décompressé à la volée (détection par extension **ou** par
les octets magiques ``1f 8b``).

Usage :
    from rudi_harvest_toolkit.tabular import filtrer_csv, lire_csv_filtre

    for ligne in filtrer_csv("https://exemple.fr/ban.csv.gz",
                             "code_insee_commune", "35120"):
        ...

    lignes, entetes = lire_csv_filtre("dvf.csv.gz", "Code commune", "35120")
"""

from __future__ import annotations

import csv
import gzip as _gzip
import io
import itertools
import os
import unicodedata
from contextlib import ExitStack, contextmanager
from typing import BinaryIO, Iterable, Iterator

from .http import session

# Certains CSV réels (BAN, DVF, RNE) contiennent des champs de plusieurs Mo
# (géométries, listes d'élus…) : sans relèvement, csv lève « field larger than
# field limit ». Même valeur que moissonneuse-batteuse.
csv.field_size_limit(10_000_000)

_TAILLE_MORCEAU = 65536
_TAILLE_ECHANTILLON = 262144
_DELIMITEURS = (";", "\t", "|", ",")


class ColonneIntrouvableError(ValueError):
    """La colonne demandée n'existe pas dans l'en-tête du CSV."""


def normaliser_nom_colonne(nom: object) -> str:
    """Clé de comparaison d'un nom de colonne : casse, accents et séparateurs ignorés."""
    if nom is None:
        return ""
    texte = str(nom).strip().lower()
    texte = texte.replace("_", " ").replace("-", " ")
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(texte.split())


def detecter_encodage(echantillon: bytes) -> str:
    """Détecte l'encodage d'un échantillon (``utf-8-sig`` si strictement décodable,
    ``cp1252`` sinon — cas quasi systématique des CSV Windows hors UTF-8).

    Un seul octet invalide suffit à trancher : tolérer quelques caractères de
    remplacement graverait des « � » dans le fichier filtré final.
    """
    try:
        echantillon.decode("utf-8-sig", errors="strict")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


def detecter_delimiteur(echantillon: str) -> str:
    """Détecte le délimiteur CSV en comptant les occurrences sur la première ligne.

    Repli sur ``csv.Sniffer`` puis sur la virgule si aucun candidat n'est présent.
    """
    premiere_ligne = echantillon.split("\n", 1)[0]
    comptes = {delim: premiere_ligne.count(delim) for delim in _DELIMITEURS}
    meilleur = max(comptes, key=comptes.get)
    if comptes[meilleur] >= 1:
        return meilleur
    try:
        return csv.Sniffer().sniff(echantillon, delimiters="".join(_DELIMITEURS)).delimiter
    except csv.Error:
        return ","


def resoudre_colonne(entetes: Iterable[str], colonne: str) -> str:
    """Retourne le nom réel de la colonne correspondant à ``colonne``.

    Correspondance exacte d'abord, puis normalisée (accents/casse/underscores).
    Lève :class:`ColonneIntrouvableError` avec la liste des colonnes disponibles.
    """
    entetes = list(entetes)
    if colonne in entetes:
        return colonne
    cible = normaliser_nom_colonne(colonne)
    for entete in entetes:
        if normaliser_nom_colonne(entete) == cible:
            return entete
    apercu = ", ".join(repr(e) for e in entetes[:20])
    if len(entetes) > 20:
        apercu += ", …"
    raise ColonneIntrouvableError(
        f"Colonne {colonne!r} introuvable. Colonnes disponibles : {apercu or '(aucune)'}"
    )


def _normaliser_valeur(valeur: object) -> str:
    """Comparaison exacte après suppression des espaces de bord (jamais d'accents)."""
    if valeur is None:
        return ""
    return str(valeur).strip()


class _LecteurBrut(io.RawIOBase):
    """Adaptateur ``RawIOBase`` au-dessus d'un itérateur de morceaux binaires.

    Permet d'envelopper aussi bien un fichier local qu'un ``iter_content()`` de
    ``requests`` dans un ``io.BufferedReader`` sans jamais matérialiser le flux.
    """

    def __init__(self, morceaux: Iterable[bytes]):
        self._morceaux = iter(morceaux)
        self._tampon = b""

    def readable(self) -> bool:  # pragma: no cover - contrat io
        return True

    def readinto(self, tampon) -> int:
        while not self._tampon:
            try:
                self._tampon = next(self._morceaux)
            except StopIteration:
                return 0
        n = min(len(tampon), len(self._tampon))
        tampon[:n] = self._tampon[:n]
        self._tampon = self._tampon[n:]
        return n


def _morceaux_fichier(fichier: BinaryIO, taille: int = _TAILLE_MORCEAU) -> Iterator[bytes]:
    while True:
        morceau = fichier.read(taille)
        if not morceau:
            break
        yield morceau


def _morceaux_reponse(reponse, taille: int = _TAILLE_MORCEAU) -> Iterator[bytes]:
    for morceau in reponse.iter_content(chunk_size=taille):
        if morceau:
            yield morceau


def _est_url(source: object) -> bool:
    return isinstance(source, str) and source.lower().startswith(("http://", "https://"))


def _extension(source: object) -> str:
    if _est_url(source):
        # On ne garde que le chemin : un « ?format=csv » ne doit pas gêner.
        return str(source).split("?", 1)[0]
    if isinstance(source, (str, os.PathLike)):
        return os.fspath(source)
    return ""


@contextmanager
def _lecteur_csv(
    source,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    gzip: bool | None = None,
    session_http=None,
    timeout: int = 120,
):
    """Ouvre ``source`` et retourne ``(DictReader, entetes, delimiteur, encodage)``.

    ``source`` : chemin local, URL HTTP(S), ou objet binaire (``.read()``).
    ``gzip`` : ``None`` = auto (extension ``.gz`` ou octets magiques), ``True``/``False``
    force le comportement.
    """
    pile = ExitStack()
    try:
        if _est_url(source):
            session_http = session_http or session
            reponse = session_http.get(source, stream=True, timeout=timeout)
            reponse.raise_for_status()
            pile.callback(reponse.close)
            brut = io.BufferedReader(_LecteurBrut(_morceaux_reponse(reponse)))
            pile.callback(brut.close)
            extension = _extension(source)
        elif hasattr(source, "read"):
            brut = source
            extension = ""
        else:
            fichier = open(os.fspath(source), "rb")
            pile.callback(fichier.close)
            brut = io.BufferedReader(fichier)
            pile.callback(brut.close)
            extension = _extension(source)

        # Aperçu non destructif des 2 premiers octets (magic gzip).
        magic = b""
        if hasattr(brut, "peek"):
            magic = brut.peek(2)[:2]

        utiliser_gzip = gzip if gzip is not None else (
            magic == b"\x1f\x8b" or str(extension).lower().endswith(".gz")
        )
        if utiliser_gzip:
            flux = _gzip.GzipFile(fileobj=brut, mode="rb")
            pile.callback(flux.close)
        else:
            flux = brut

        # Échantillon lu une fois : il sert à détecter encodage/délimiteur, puis est
        # réinjecté en tête du flux texte (le flux n'est donc pas rembobiné).
        echantillon = flux.read(_TAILLE_ECHANTILLON)
        encodage = encoding or detecter_encodage(echantillon)
        delimiteur = delimiter or detecter_delimiteur(
            echantillon.decode(encodage, errors="replace")
        )

        reste = _morceaux_fichier(flux)
        brut_final = io.BufferedReader(_LecteurBrut(itertools.chain([echantillon], reste)))
        pile.callback(brut_final.close)
        texte = io.TextIOWrapper(brut_final, encoding=encodage, errors="replace", newline="")
        pile.callback(texte.close)

        lecteur = csv.reader(texte, delimiter=delimiteur)
        try:
            entetes = next(lecteur)
        except StopIteration:
            entetes = []
        # L'en-tête a déjà été consommé : on fournit fieldnames pour que DictReader
        # ne saute pas la première ligne de données.
        lecteur_dict = csv.DictReader(texte, fieldnames=entetes, delimiter=delimiteur)
        yield lecteur_dict, entetes, delimiteur, encodage
    finally:
        pile.close()


def iter_lignes_csv(
    source,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    gzip: bool | None = None,
    session_http=None,
    timeout: int = 120,
) -> Iterator[dict]:
    """Itère sur toutes les lignes d'un CSV (dicts ``{en-tête: valeur}``), en flux."""
    with _lecteur_csv(
        source,
        encoding=encoding,
        delimiter=delimiter,
        gzip=gzip,
        session_http=session_http,
        timeout=timeout,
    ) as (lecteur, _entetes, _delimiteur, _encodage):
        for ligne in lecteur:
            yield ligne


def filtrer_csv(
    source,
    colonne: str,
    valeur: object,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    gzip: bool | None = None,
    session_http=None,
    timeout: int = 120,
) -> Iterator[dict]:
    """Itère sur les lignes où ``colonne`` vaut exactement ``valeur`` (en flux).

    Le nom de colonne est résolu de façon tolérante (accents/casse/underscores).
    La valeur est comparée après ``strip()``, sans normalisation d'accents.
    """
    with _lecteur_csv(
        source,
        encoding=encoding,
        delimiter=delimiter,
        gzip=gzip,
        session_http=session_http,
        timeout=timeout,
    ) as (lecteur, entetes, _delimiteur, _encodage):
        colonne_reelle = resoudre_colonne(entetes, colonne)
        cible = _normaliser_valeur(valeur)
        for ligne in lecteur:
            if _normaliser_valeur(ligne.get(colonne_reelle)) == cible:
                yield ligne


def lire_csv_filtre(
    source,
    colonne: str,
    valeur: object,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    gzip: bool | None = None,
    session_http=None,
    timeout: int = 120,
) -> tuple[list[dict], list[str]]:
    """Variante matérialisée de :func:`filtrer_csv` : ``(lignes, entetes)``.

    Même contrat de retour que ``filtrer_csv()``/``filtrer_gz()`` de
    ``moissonneuse-batteuse`` — pratique pour les connecteurs qui doivent ensuite
    réécrire un fichier filtré.
    """
    with _lecteur_csv(
        source,
        encoding=encoding,
        delimiter=delimiter,
        gzip=gzip,
        session_http=session_http,
        timeout=timeout,
    ) as (lecteur, entetes, _delimiteur, _encodage):
        colonne_reelle = resoudre_colonne(entetes, colonne)
        cible = _normaliser_valeur(valeur)
        lignes = [
            ligne for ligne in lecteur
            if _normaliser_valeur(ligne.get(colonne_reelle)) == cible
        ]
    return lignes, entetes
