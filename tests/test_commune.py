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


if __name__ == "__main__":
    unittest.main()
