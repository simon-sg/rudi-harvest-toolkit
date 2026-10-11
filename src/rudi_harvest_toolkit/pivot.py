"""
Constructeur de métadonnées RUDI — fonction pivot *pure* du toolkit.

Découplée de toute logique locale (bbox Rennes Métropole en dur, enrichissement
implicite des contacts ou de l'organisation productrice) : l'appelant fournit
explicitement la géographie, le producteur **entièrement pré-formé** et les contacts
à publier. Le toolkit ne résout jamais ni contacts ni organisation à la place de
l'appelant.

Usage :
    from rudi_harvest_toolkit.pivot import (
        LICENCE_ETALAB, construire_licence, construire_rudi_metadata,
        media_filtre, media_source, media_metadata_page, media_dict, media_pdf,
        parser_date_http,
    )
"""

import datetime
import re
import uuid

from .markdown import markdown_vers_html

# Licence Etalab 2.0, partagée par tous les scripts de moisson
LICENCE_ETALAB = {
    "licence_type": "STANDARD",
    "licence_label": "etalab-2.0",
    "licence_uri": "https://www.etalab.gouv.fr/licence-ouverte-open-licence",
}


# ---------------------------------------------------------------------------
# Helpers pour les entrées media
# ---------------------------------------------------------------------------

def media_filtre(prefixe_id: str, nom_fichier: str, zone: str,
                 caption: str | None = None) -> dict:
    """Construit une entrée media FILE pour un fichier filtré."""
    return {
        "media_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefixe_id}/filtered/{nom_fichier}")),
        "media_type": "FILE",
        "media_name": nom_fichier,
        "media_caption": caption or f"{nom_fichier} — données filtrées sur {zone} (CSV)",
        "connector": {
            "url": "À_RENSEIGNER_APRES_DEPOT_SUR_NOEUD",
            "interface_contract": "dwnl",
        },
    }


def media_source(prefixe_id: str, url_source: str, caption: str) -> dict:
    """Construit une entrée media SERVICE pour la source complète."""
    return {
        "media_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefixe_id}/source")),
        "media_type": "SERVICE",
        "media_name": "source-data",
        "media_caption": caption,
        "connector": {
            "url": url_source,
            "interface_contract": "dwnl",
        },
    }


def media_metadata_page(prefixe_id: str, url_fiche: str, caption: str) -> dict:
    """Construit une entrée media SERVICE pour la fiche de métadonnées d'origine."""
    return {
        "media_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefixe_id}/metadata-page")),
        "media_type": "SERVICE",
        "media_name": "source-metadata",
        "media_caption": caption,
        "connector": {
            "url": url_fiche,
            "interface_contract": "dwnl",
        },
    }


def media_dict(prefixe_id: str, nom_fichier: str) -> dict:
    """Construit une entrée media FILE pour un dictionnaire de variables."""
    return {
        "media_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefixe_id}/dict/{nom_fichier}")),
        "media_type": "FILE",
        "media_name": nom_fichier,
        "media_caption": f"Dictionnaire des variables — {nom_fichier} (CSV)",
        "connector": {
            "url": "À_RENSEIGNER_APRES_DEPOT_SUR_NOEUD",
            "interface_contract": "dwnl",
        },
    }


def media_pdf(prefixe_id: str, nom_fichier: str, titre: str) -> dict:
    """Construit une entrée media FILE pour un document PDF."""
    return {
        "media_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefixe_id}/pdf/{nom_fichier}")),
        "media_type": "FILE",
        "media_name": nom_fichier,
        "media_caption": f"Documentation — {titre} (PDF)",
        "connector": {
            "url": "À_RENSEIGNER_APRES_DEPOT_SUR_NOEUD",
            "interface_contract": "dwnl",
        },
    }


# ---------------------------------------------------------------------------
# Licences
# ---------------------------------------------------------------------------

def _normaliser_label_licence(label: str) -> str:
    """Clé de correspondance insensible à la casse et aux espaces de bord."""
    return (label or "").strip().lower()


def construire_licence(label: str | None, url: str | None,
                       table_correspondance: dict[str, dict]) -> dict | None:
    """Construit un bloc licence RUDI depuis un libellé et une URL source.

    `table_correspondance` associe un libellé connu (ex. « ODbL », « lov2 ») à un bloc
    licence RUDI complet (typiquement ``licence_type`` STANDARD). La recherche est
    insensible à la casse.

    - libellé connu → copie du bloc de la table ;
    - libellé inconnu → bloc CUSTOM en passthrough (libellé + URL conservés) ;
    - libellé vide/absent → ``None`` (l'appelant décide de son repli).

    Le repli d'un libellé absent (repli configurable, signalé en dry-run) est une
    responsabilité de l'appelant, jamais inventé ici silencieusement.
    """
    if not label:
        return None
    table_normalisee = {_normaliser_label_licence(k): v for k, v in table_correspondance.items()}
    bloc = table_normalisee.get(_normaliser_label_licence(label))
    if bloc is not None:
        return dict(bloc)
    custom = {
        "licence_type": "CUSTOM",
        "custom_licence_label": [{"lang": "fr", "text": label}],
    }
    if url:
        custom["custom_licence_uri"] = url
    return custom


# ---------------------------------------------------------------------------
# Construction de la date
# ---------------------------------------------------------------------------

def parser_date_http(date_str: str | None) -> str | None:
    """Convertit une date HTTP (Last-Modified, updatedAt) en ISO 8601."""
    if not date_str:
        return None
    # Format ISO direct (OEB updatedAt : "2025-01-15T10:30:00.000Z").
    # Motif complet obligatoire : un simple `"T" in date_str` matchait aussi
    # le "T" de "GMT" des dates HTTP et produisait "Wed, 12 FeT00:00:00Z".
    if re.match(r"\d{4}-\d{2}-\d{2}T", date_str):
        # Conserver l'heure réelle, normalisée en UTC (suffixe `Z` ou offset
        # explicite type "+00:00"/"+02:00" converti vers UTC).
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Format HTTP (INSEE/BDNB Last-Modified : "Wed, 12 Feb 2025 09:41:37 GMT")
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Assemblage final
# ---------------------------------------------------------------------------

def construire_rudi_metadata(
    *,
    local_id: str,
    titre: str,
    synopsis: str,
    description: str,
    theme: str,
    keywords: list[str],
    producer: dict,
    url_source: str,
    url_fiche: str,
    medias: list[dict],
    contacts_source: list[dict],
    date_source: str | None = None,
    metadata_source_label: str = "source",
    licence: dict | None = None,
    dates: dict | None = None,
    metadata_dates: dict | None = None,
    ajouter_medias_source: bool = True,
    geography: dict | None = None,
) -> dict:
    """Assemble le dict complet rudi_metadata.json — point de convergence des voies
    de génération (data.gouv tabulaire, service géo, INSEE, OEB, BDNB, ODS…).

    Fonction pivot *pure* : elle ne résout ni contacts ni organisation productrice,
    et n'injecte aucune géographie implicite. Les trois responsabilités correspondantes
    sont explicites :

        producer        : dict **entièrement pré-formé** par l'appelant (au minimum
                          ``{"organization_name": ...}``, enrichissement organisation
                          optionnel déjà appliqué) ;
        contacts_source : liste de contacts obligatoire (au moins un contact valide
                          attendu par le nœud — repli à la charge de l'appelant) ;
        geography       : emprise géographique explicite ou ``None`` (clé omise de la
                          sortie si None).

    Tous les arguments sont nommés (keyword-only) pour forcer la lisibilité
    des sites d'appel.

    Paramètres :
        local_id          : ID déterministe (UUIDv5) — stable d'un run à l'autre
        titre             : titre lisible avec zone (ex: "Titre — Rennes Métropole")
        synopsis          : résumé court (≤150 car.)
        description       : description complète (preamble + complément)
        theme             : thème RUDI (economy, society, environment, …)
        keywords          : liste de mots-clés
        producer          : producteur pré-formé (organization_name + enrichissements)
        url_source        : URL du jeu de données source (data.gouv.fr, insee.fr, etc.)
        url_fiche         : URL de la fiche de métadonnées d'origine
        medias            : liste d'entrées available_formats (filtres + dicts + source + metadata_page).
                            NB : les media_id sont des UUIDv5 dérivés de gabarits propres à
                            chaque voie — ne pas les « harmoniser », les IDs sur le nœud RUDI
                            doivent rester stables d'un run à l'autre
        contacts_source   : contacts du producteur (obligatoire — aucun repli implicite)
        date_source       : Last-Modified HTTP ou updatedAt (converti en ISO 8601)
        metadata_source_label : nom du media SERVICE source (défaut "source")
        licence           : bloc licence RUDI (défaut LICENCE_ETALAB ; les datasets data.gouv
                            peuvent porter une licence CUSTOM issue de leur fiche)
        dates             : dataset_dates complet ({"created": ..., "updated": ...}) — prime
                            sur la dérivation depuis date_source
        metadata_dates    : ajouté à metadata_info si fourni (voies data.gouv/géo)
        ajouter_medias_source : ajoute source-data/source-metadata s'ils manquent (défaut) ;
                            False pour les voies qui construisent ces entrées elles-mêmes
                            sous d'autres noms (ex: "source-data-gouv")
        geography         : emprise géographique RUDI explicite (bbox/geojson) ou None
    """
    if dates is None:
        dates = {}
        iso = parser_date_http(date_source)
        if iso:
            dates["updated"] = iso

    if ajouter_medias_source:
        # S'assurer qu'il y a au moins media_source + media_metadata_page
        noms_media = {m.get("media_name") for m in medias}
        if "source-data" not in noms_media:
            medias.append(media_source(local_id, url_source,
                                       f"Jeu de données complet sur {metadata_source_label}"))
        if "source-metadata" not in noms_media:
            medias.append(media_metadata_page(local_id, url_fiche,
                                              f"Fiche de métadonnées du jeu de données source sur {metadata_source_label}"))

    metadata_info = {"metadata_source": url_fiche}
    if metadata_dates is not None:
        metadata_info = {"metadata_dates": metadata_dates, "metadata_source": url_fiche}

    # Le nœud RUDI rejette resource_title > 150 caractères. Contrairement au synopsis
    # (toujours construit avec un [:150] par les appelants), le titre n'était tronqué
    # nulle part — un titre source déjà long + le suffixe zone ("… — Rennes Métropole")
    # dépasse la limite pour quelques JDD (ex: intitulés d'arrêtés préfectoraux).
    if len(titre) > 150:
        titre = titre[:149] + "…"

    # `html` : version formatée du summary, rendue telle quelle (innerHTML) par le portail
    # depuis sa v3.3.2 — sans elle, le portail retombe sur `text` mais l'injecte quand même
    # en HTML, donc le Markdown source (listes, gras, liens de data.gouv.fr notamment)
    # s'affichait tel quel et les retours à la ligne disparaissaient. Clé omise si vide :
    # `html ?? text` côté portail ne retombe sur `text` que si `html` est absent (une
    # chaîne vide ne déclencherait pas ce repli).
    _summary_fr = {"lang": "fr", "text": description}
    _summary_html = markdown_vers_html(description)
    if _summary_html:
        _summary_fr["html"] = _summary_html

    resultat = {
        "local_id": local_id,
        "resource_title": titre,
        "synopsis": [{"lang": "fr", "text": synopsis}],
        "summary": [_summary_fr],
        "theme": theme,
        "keywords": list(dict.fromkeys(keywords)),
        "producer": dict(producer),
        "contacts": contacts_source,
        "available_formats": medias,
        "dataset_dates": dates,
        "storage_status": "online",
        "access_condition": {
            "licence": licence if licence is not None else LICENCE_ETALAB,
            "confidentiality": {"restricted_access": False, "gdpr_sensitive": False},
        },
        "metadata_info": metadata_info,
    }
    if geography is not None:
        resultat["geography"] = geography
    return resultat
