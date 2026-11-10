"""Assembleur GeoJSON par ligne — mise en page pure, sans connaissance du domaine
(v4 de rudi-commune-starterkit, Axe 3).

Même esprit que :mod:`description` : cette fonction ne fait qu'assembler un
``FeatureCollection`` à partir de lignes déjà filtrées par l'appelant, jamais ne
devine ni n'invente une géométrie absente — une ligne sans coordonnée exploitable est
silencieusement omise (jamais une géométrie ``null``/``[0, 0]``), et l'appelant est
responsable de rendre cette omission visible au lecteur du catalogue (compter les
lignes omises et les reporter dans ``limites``).
"""

from __future__ import annotations

from .tabular import ColonneIntrouvableError, resoudre_colonne


class AucuneGeometrieValide(ValueError):
    """``lignes`` ne produit aucune Feature valide — un JDD sans aucun point
    géolocalisé ne doit jamais publier un GeoJSON vide."""


def construire_feature_collection(
    lignes: list[dict],
    *,
    champ_lon: str,
    champ_lat: str,
    proprietes: list[str] | None = None,
) -> dict:
    """Construit un ``FeatureCollection`` GeoJSON, un ``Point`` par ligne ayant des
    coordonnées exploitables.

    - Une ligne sans valeur numérique valide sur ``champ_lon``/``champ_lat`` est
      silencieusement omise (jamais une géométrie inventée) — c'est à l'appelant de
      rendre cette omission visible (compter ``len(lignes) - len(features)``).
    - ``coordinates`` est toujours ``[longitude, latitude]`` (ordre GeoJSON standard,
      jamais inversé — un piège confirmé sur l'export natif de certaines sources).
    - ``proprietes`` restreint les champs copiés dans ``Feature.properties``
      (``None`` = toutes les colonnes sauf ``champ_lon``/``champ_lat`` ; ``[]`` =
      aucune).

    Lève :class:`ColonneIntrouvableError` si ``champ_lon``/``champ_lat`` n'existe dans
    aucune ligne. Lève :class:`AucuneGeometrieValide` si aucune ligne ne produit de
    Feature valide (pas de ``FeatureCollection`` vide publiée).
    """
    if champ_lon == champ_lat:
        raise ValueError("champ_lon et champ_lat ne peuvent pas être le même champ.")

    if not lignes:
        raise AucuneGeometrieValide(
            "Aucune ligne fournie — impossible de construire une géométrie."
        )

    entetes = list(lignes[0].keys())
    lon_reelle = resoudre_colonne(entetes, champ_lon)
    lat_reelle = resoudre_colonne(entetes, champ_lat)

    if proprietes is None:
        champs_proprietes = [c for c in entetes if c not in (lon_reelle, lat_reelle)]
    else:
        champs_proprietes = list(proprietes)

    features = []
    for ligne in lignes:
        lon = _vers_float(ligne.get(lon_reelle))
        lat = _vers_float(ligne.get(lat_reelle))
        if lon is None or lat is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {champ: ligne.get(champ) for champ in champs_proprietes},
        })

    if not features:
        raise AucuneGeometrieValide(
            f"Aucune ligne n'a de coordonnées exploitables sur "
            f"{lon_reelle!r}/{lat_reelle!r} ({len(lignes)} ligne(s) examinée(s))."
        )

    return {"type": "FeatureCollection", "features": features}


def _vers_float(valeur: object) -> float | None:
    if valeur is None:
        return None
    texte = str(valeur).strip()
    if not texte:
        return None
    try:
        return float(texte.replace(",", "."))
    except ValueError:
        return None


__all__ = ["AucuneGeometrieValide", "ColonneIntrouvableError", "construire_feature_collection"]
