"""Tests de commune.py — résolution INSEE + SIREN, garde-fous. Zéro réseau."""
import unittest
from unittest import mock

from rudi_harvest_toolkit.commune import (
    GEO_API,
    NATURE_JURIDIQUE_COMMUNE,
    RECHERCHE_ENTREPRISES_API,
    ArrondissementMunicipalError,
    CodeInseeInvalide,
    CommuneIntrouvableError,
    ErreurReseauCommune,
    PlusieursCommunesError,
    bbox_depuis_contour,
    resoudre_commune,
    resoudre_siren_commune,
    valider_code_insee,
)

_GEVEZE = {
    "nom": "Gévezé",
    "code": "35120",
    "codeDepartement": "35",
    "departement": {"nom": "Ille-et-Vilaine"},
    "codeRegion": "53",
    "region": {"nom": "Bretagne"},
    "codesPostaux": ["35850"],
    "population": 4200,
    "centre": {"type": "Point", "coordinates": [-1.78, 48.22]},
    "contour": {"type": "Polygon", "coordinates": [[]]},
}


def _reponse(json_value, statut_ok=True):
    reponse = mock.Mock()
    reponse.json.return_value = json_value
    if statut_ok:
        reponse.raise_for_status = mock.Mock()
    return reponse


class TestValiderCodeInsee(unittest.TestCase):
    def test_code_valide(self):
        self.assertEqual(valider_code_insee("35120"), "35120")

    def test_code_corse_non_converti_en_int(self):
        self.assertEqual(valider_code_insee("2A004"), "2A004")
        self.assertEqual(valider_code_insee("2b033"), "2B033")

    def test_code_vide(self):
        with self.assertRaises(CodeInseeInvalide):
            valider_code_insee("")

    def test_code_none(self):
        with self.assertRaises(CodeInseeInvalide):
            valider_code_insee(None)

    def test_code_mal_forme(self):
        with self.assertRaises(CodeInseeInvalide):
            valider_code_insee("ABC12")
        with self.assertRaises(CodeInseeInvalide):
            valider_code_insee("3512")

    def test_arrondissement_paris_refuse(self):
        with self.assertRaises(ArrondissementMunicipalError):
            valider_code_insee("75101")
        with self.assertRaises(ArrondissementMunicipalError):
            valider_code_insee("75120")

    def test_arrondissement_lyon_refuse(self):
        with self.assertRaises(ArrondissementMunicipalError):
            valider_code_insee("69381")

    def test_arrondissement_marseille_refuse(self):
        with self.assertRaises(ArrondissementMunicipalError):
            valider_code_insee("13205")

    def test_paris_commune_entiere_acceptee(self):
        # 75056 (Paris en tant que commune) n'est pas un code d'arrondissement.
        self.assertEqual(valider_code_insee("75056"), "75056")

    def test_borne_juste_hors_arrondissement_acceptee(self):
        self.assertEqual(valider_code_insee("75121"), "75121")
        self.assertEqual(valider_code_insee("69390"), "69390")


class TestResoudreCommune(unittest.TestCase):
    def test_resout_geveze(self):
        session = mock.Mock()
        session.get.return_value = _reponse(_GEVEZE)

        resultat = resoudre_commune("35120", session_http=session)

        self.assertEqual(resultat["nom"], "Gévezé")
        self.assertEqual(resultat["code_insee"], "35120")
        self.assertEqual(resultat["departement"], "Ille-et-Vilaine")
        self.assertEqual(resultat["region"], "Bretagne")
        self.assertEqual(resultat["codes_postaux"], ["35850"])
        self.assertIn("contour", resultat)
        session.get.assert_called_once()
        url_appelee = session.get.call_args.args[0]
        self.assertEqual(url_appelee, f"{GEO_API}/communes/35120")

    def test_sans_contour_si_non_demande(self):
        session = mock.Mock()
        session.get.return_value = _reponse(_GEVEZE)
        resultat = resoudre_commune("35120", session_http=session, inclure_contour=False)
        self.assertNotIn("contour", resultat)

    def test_404_leve_commune_introuvable(self):
        session = mock.Mock()
        reponse = mock.Mock()
        reponse.status_code = 404
        erreur = RuntimeError("404")
        erreur.response = reponse
        reponse.raise_for_status.side_effect = erreur
        session.get.return_value = reponse

        with self.assertRaises(CommuneIntrouvableError):
            resoudre_commune("99999", session_http=session)

    def test_autre_erreur_http_leve_erreur_reseau(self):
        session = mock.Mock()
        reponse = mock.Mock()
        reponse.status_code = 500
        erreur = RuntimeError("500")
        erreur.response = reponse
        reponse.raise_for_status.side_effect = erreur
        session.get.return_value = reponse

        with self.assertRaises(ErreurReseauCommune):
            resoudre_commune("35120", session_http=session)

    def test_echec_reseau_leve_erreur_reseau(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("DNS")
        with self.assertRaises(ErreurReseauCommune):
            resoudre_commune("35120", session_http=session)

    def test_reponse_vide_leve_commune_introuvable(self):
        session = mock.Mock()
        session.get.return_value = _reponse({})
        with self.assertRaises(CommuneIntrouvableError):
            resoudre_commune("35120", session_http=session)

    def test_code_invalide_ne_declenche_aucun_appel_reseau(self):
        session = mock.Mock()
        with self.assertRaises(CodeInseeInvalide):
            resoudre_commune("75101", session_http=session)
        session.get.assert_not_called()


class TestResoudreSirenCommune(unittest.TestCase):
    def test_resout_le_siren(self):
        session = mock.Mock()
        session.get.return_value = _reponse(
            {"results": [{"siren": "213501208"}], "total_results": 1}
        )

        siren = resoudre_siren_commune("35120", session_http=session)

        self.assertEqual(siren, "213501208")
        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["nature_juridique"], NATURE_JURIDIQUE_COMMUNE)
        self.assertEqual(kwargs["params"]["code_commune"], "35120")
        self.assertIn(RECHERCHE_ENTREPRISES_API, session.get.call_args.args[0])

    def test_aucun_resultat_leve_commune_introuvable(self):
        session = mock.Mock()
        session.get.return_value = _reponse({"results": [], "total_results": 0})
        with self.assertRaises(CommuneIntrouvableError):
            resoudre_siren_commune("35120", session_http=session)

    def test_plusieurs_resultats_leve_erreur_explicite(self):
        session = mock.Mock()
        session.get.return_value = _reponse(
            {
                "results": [{"siren": "111111111"}, {"siren": "222222222"}],
                "total_results": 2,
            }
        )
        with self.assertRaises(PlusieursCommunesError):
            resoudre_siren_commune("35120", session_http=session)

    def test_resultat_sans_siren_leve_erreur(self):
        session = mock.Mock()
        session.get.return_value = _reponse({"results": [{}], "total_results": 1})
        with self.assertRaises(CommuneIntrouvableError):
            resoudre_siren_commune("35120", session_http=session)

    def test_echec_reseau_leve_erreur_reseau(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("timeout")
        with self.assertRaises(ErreurReseauCommune):
            resoudre_siren_commune("35120", session_http=session)


class TestBboxDepuisContour(unittest.TestCase):
    def test_contour_none(self):
        self.assertIsNone(bbox_depuis_contour(None))

    def test_contour_vide(self):
        self.assertIsNone(bbox_depuis_contour({}))
        self.assertIsNone(bbox_depuis_contour({"type": "Polygon", "coordinates": [[]]}))

    def test_type_non_reconnu(self):
        self.assertIsNone(bbox_depuis_contour({"type": "Point", "coordinates": [-1.78, 48.22]}))

    def test_polygon_simple(self):
        contour = {
            "type": "Polygon",
            "coordinates": [[[-1.80, 48.20], [-1.75, 48.20], [-1.75, 48.25], [-1.80, 48.25], [-1.80, 48.20]]],
        }
        bbox = bbox_depuis_contour(contour)
        self.assertEqual(bbox, {
            "west_longitude": -1.80, "east_longitude": -1.75,
            "south_latitude": 48.20, "north_latitude": 48.25,
        })

    def test_polygon_avec_anneau_interieur(self):
        exterieur = [[-2.0, 48.0], [2.0, 48.0], [2.0, 50.0], [-2.0, 50.0], [-2.0, 48.0]]
        trou = [[-0.5, 48.5], [0.5, 48.5], [0.5, 49.5], [-0.5, 49.5], [-0.5, 48.5]]
        bbox = bbox_depuis_contour({"type": "Polygon", "coordinates": [exterieur, trou]})
        self.assertEqual(bbox["west_longitude"], -2.0)
        self.assertEqual(bbox["east_longitude"], 2.0)

    def test_multipolygon(self):
        contour = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-5.0, 46.0], [-4.0, 46.0], [-4.0, 47.0], [-5.0, 47.0], [-5.0, 46.0]]],
                [[[1.0, 41.0], [2.0, 41.0], [2.0, 42.0], [1.0, 42.0], [1.0, 41.0]]],
            ],
        }
        bbox = bbox_depuis_contour(contour)
        self.assertEqual(bbox, {
            "west_longitude": -5.0, "east_longitude": 2.0,
            "south_latitude": 41.0, "north_latitude": 47.0,
        })

    def test_axes_non_melanges(self):
        # Latitude et longitude ne doivent jamais être confondues entre elles —
        # ce test échouerait avec un bug de min/max calculé sur les coordonnées
        # aplaties sans distinguer les deux axes (toutes les latitudes > toutes
        # les longitudes ici, contrairement au cas métropolitain).
        contour = {
            "type": "Polygon",
            "coordinates": [[[10.0, 60.0], [20.0, 60.0], [20.0, 70.0], [10.0, 70.0], [10.0, 60.0]]],
        }
        bbox = bbox_depuis_contour(contour)
        self.assertEqual(bbox["west_longitude"], 10.0)
        self.assertEqual(bbox["east_longitude"], 20.0)
        self.assertEqual(bbox["south_latitude"], 60.0)
        self.assertEqual(bbox["north_latitude"], 70.0)


if __name__ == "__main__":
    unittest.main()
