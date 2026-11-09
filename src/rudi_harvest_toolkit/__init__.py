"""rudi-harvest-toolkit — briques partagées extraites de moissonneuse-batteuse.

Modules :

- ``pivot`` : assemblage des métadonnées RUDI (fonction pivot pure, sans couplage
  géographie/producteur/contacts) ;
- ``markdown`` : conversion d'un sous-ensemble de Markdown en HTML (summary[].html) ;
- ``state`` : chargement/sauvegarde d'état et détection de changement ;
- ``http`` : session ``requests`` mutualisée (pool + retry/backoff) ;
- ``rudi_client`` : publication sur un nœud RUDI (métadonnées + médias) ;
- ``publish`` : garde-fou de publication (verrou + suivi des local_id du run) ;
- ``commune`` : résolution d'une commune par code INSEE (identité, géographie, SIREN) ;
- ``wikipedia`` : résumé Wikipédia d'une commune, désambiguïsé par code INSEE.
"""

from .commune import bbox_depuis_contour
from .markdown import markdown_vers_html
from .pivot import (
    LICENCE_ETALAB,
    construire_licence,
    construire_rudi_metadata,
    media_dict,
    media_filtre,
    media_metadata_page,
    media_pdf,
    media_source,
    parser_date_http,
)
from .state import (
    charger_etat,
    construire_index_dossier,
    dataset_a_change,
    sauvegarder_etat,
)
from .wikipedia import resumer_commune_wikipedia

__all__ = [
    "LICENCE_ETALAB",
    "bbox_depuis_contour",
    "construire_licence",
    "construire_rudi_metadata",
    "charger_etat",
    "construire_index_dossier",
    "dataset_a_change",
    "markdown_vers_html",
    "media_dict",
    "media_filtre",
    "media_metadata_page",
    "media_pdf",
    "media_source",
    "parser_date_http",
    "resumer_commune_wikipedia",
    "sauvegarder_etat",
]
