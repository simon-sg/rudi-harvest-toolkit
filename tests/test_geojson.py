"""Tests de geojson.py — assemblage FeatureCollection pur (v4 de
rudi-commune-starterkit, Axe 3). Zéro réseau."""
import unittest

from rudi_harvest_toolkit.geojson import (
    AucuneGeometrieValide, ColonneIntrouvableError, construire_feature_collection,
)

_LIGNES = [
    {"nom": "A", "lon": "-1.6778", "lat": "48.1173", "autre": "x"},
    {"nom": "B", "lon": "-1.7", "lat": "48.2", "autre": "y"},
]


class TestConstruireFeatureCollection(unittest.TestCase):
    def test_une_feature_par_ligne_valide(self):
        fc = construire_feature_collection(_LIGNES, champ_lon="lon", champ_lat="lat")
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertEqual(len(fc["features"]), 2)

    def test_ordre_coordinates_lon_lat_jamais_inverse(self):
        fc = construire_feature_collection(_LIGNES, champ_lon="lon", champ_lat="lat")
        self.assertEqual(fc["features"][0]["geometry"]["coordinates"], [-1.6778, 48.1173])

    def test_proprietes_restreintes(self):
        fc = construire_feature_collection(
            _LIGNES, champ_lon="lon", champ_lat="lat", proprietes=["nom"],
        )
        self.assertEqual(fc["features"][0]["properties"], {"nom": "A"})

    def test_proprietes_none_copie_tout_sauf_coordonnees(self):
        fc = construire_feature_collection(_LIGNES, champ_lon="lon", champ_lat="lat")
        self.assertEqual(set(fc["features"][0]["properties"]), {"nom", "autre"})

    def test_proprietes_liste_vide_aucune_propriete(self):
        fc = construire_feature_collection(
            _LIGNES, champ_lon="lon", champ_lat="lat", proprietes=[],
        )
        self.assertEqual(fc["features"][0]["properties"], {})

    def test_ligne_sans_coordonnee_omise_silencieusement(self):
        lignes = _LIGNES + [{"nom": "C", "lon": "", "lat": None, "autre": "z"}]
        fc = construire_feature_collection(lignes, champ_lon="lon", champ_lat="lat")
        self.assertEqual(len(fc["features"]), 2)

    def test_toutes_lignes_sans_coordonnee_leve_aucune_geometrie_valide(self):
        lignes = [{"nom": "C", "lon": "", "lat": None}]
        with self.assertRaises(AucuneGeometrieValide):
            construire_feature_collection(lignes, champ_lon="lon", champ_lat="lat")

    def test_lignes_vide_leve_aucune_geometrie_valide(self):
        with self.assertRaises(AucuneGeometrieValide):
            construire_feature_collection([], champ_lon="lon", champ_lat="lat")

    def test_champ_absent_leve_colonne_introuvable(self):
        with self.assertRaises(ColonneIntrouvableError):
            construire_feature_collection(_LIGNES, champ_lon="absent", champ_lat="lat")

    def test_champ_lon_egal_champ_lat_leve_value_error(self):
        with self.assertRaises(ValueError):
            construire_feature_collection(_LIGNES, champ_lon="lon", champ_lat="lon")

    def test_coordonnee_non_numerique_omise(self):
        lignes = _LIGNES + [{"nom": "C", "lon": "pas-un-nombre", "lat": "48", "autre": "z"}]
        fc = construire_feature_collection(lignes, champ_lon="lon", champ_lat="lat")
        self.assertEqual(len(fc["features"]), 2)

    def test_virgule_decimale_acceptee(self):
        lignes = [{"nom": "A", "lon": "-1,6778", "lat": "48,1173"}]
        fc = construire_feature_collection(lignes, champ_lon="lon", champ_lat="lat")
        self.assertEqual(fc["features"][0]["geometry"]["coordinates"], [-1.6778, 48.1173])


if __name__ == "__main__":
    unittest.main()
