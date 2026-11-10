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
) -> str:
    """Assemble une description Markdown structurée : quoi / comment construit / liste
    à puces des variables publiées / fréquence de mise à jour / source en bas (lien
    Markdown).

    Lève ``ValueError`` si ``structure_variables`` est vide — un bloc « Variables
    publiées : » sans puce serait un Markdown cassé silencieux (liste vide), pas une
    description simplement plus courte.
    """
    if not structure_variables:
        raise ValueError(
            "structure_variables ne doit jamais être vide — un bloc sans puce serait un "
            "Markdown cassé silencieux."
        )

    puces = "\n".join(f"- {variable}" for variable in structure_variables)

    return (
        f"{quoi}\n\n"
        f"{comment_construit}\n\n"
        f"Variables publiées :\n"
        f"{puces}\n\n"
        f"Mise à jour : {frequence_maj}.\n\n"
        f"Source : [{source_label}]({url_source})"
    )


__all__ = ["construire_description_structuree"]
