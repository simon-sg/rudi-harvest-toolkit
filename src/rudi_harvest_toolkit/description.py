"""Assembleur de description structurée — mise en page pure, sans connaissance du
domaine (v3 de rudi-commune-starterkit, Axe 3).

Respecte strictement le sous-ensemble Markdown de :func:`markdown.markdown_vers_html`
(paragraphes séparés par une ligne vide, liste à puces ``- item``, lien
``[texte](url)``) — jamais de tableau, cette fonction n'en génère pas. Le contenu
métier (quoi/comment construit/variables publiées) reste écrit à la main par
l'appelant, pour chaque jeu de données ; cette fonction ne fait qu'assembler et
mettre en page ce contenu, pas l'inventer.
"""

from __future__ import annotations


def construire_description_structuree(
    *,
    quoi: str,
    comment_construit: str,
    structure_variables: list[str],
    frequence_maj: str,
    source_label: str,
    url_source: str,
    glossaire: dict[str, str] | None = None,
    limites: list[str] | None = None,
) -> str:
    """Assemble une description Markdown structurée : quoi / comment construit / liste
    à puces des variables publiées / glossaire optionnel / limites de couverture
    optionnelles / fréquence de mise à jour / source en bas (lien Markdown).

    Lève ``ValueError`` si ``structure_variables`` est vide — un bloc « Variables
    publiées : » sans puce serait un Markdown cassé silencieux (liste vide), pas une
    description simplement plus courte.

    ``glossaire`` (``{code: libellé}``) et ``limites`` (liste de phrases) sont
    optionnels — ``None`` (défaut) ne change rien à la sortie actuelle. Ajoutés pour
    rendre visibles, directement dans la fiche catalogue (pas seulement dans
    BACKLOG.md, jamais consulté par un lecteur du nœud RUDI), les nomenclatures
    opaques (budget, DVF, DECP, nuances électorales) et les dégradations attendues
    (carte partielle, jointure non appariée, date absente) — voir le plan v4, Axes 4/5.
    """
    if not structure_variables:
        raise ValueError(
            "structure_variables ne doit jamais être vide — un bloc sans puce serait un "
            "Markdown cassé silencieux."
        )

    puces = "\n".join(f"- {variable}" for variable in structure_variables)

    bloc_glossaire = ""
    if glossaire:
        puces_glossaire = "\n".join(f"- {code} : {libelle}" for code, libelle in glossaire.items())
        bloc_glossaire = f"Codes et variables :\n{puces_glossaire}\n\n"

    bloc_limites = ""
    if limites:
        puces_limites = "\n".join(f"- {limite}" for limite in limites)
        bloc_limites = f"Limites de couverture :\n{puces_limites}\n\n"

    return (
        f"{quoi}\n\n"
        f"{comment_construit}\n\n"
        f"Variables publiées :\n"
        f"{puces}\n\n"
        f"{bloc_glossaire}"
        f"{bloc_limites}"
        f"Mise à jour : {frequence_maj}.\n\n"
        f"Source : [{source_label}]({url_source})"
    )


__all__ = ["construire_description_structuree"]
