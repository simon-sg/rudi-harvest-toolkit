"""Tests de rne.py — maire actuel via le Répertoire National des Élus. Zéro réseau ni
disque réel (get_dataset_metadata/selectionner_ressource/telecharger/filtrer_csv mockés)."""
import unittest
from unittest import mock

from rudi_harvest_toolkit.rne import maire_actuel


def _ligne(nom, prenom, fonction, date_debut):
    return {
        "Nom de l'élu": nom, "Prénom de l'élu": prenom,
        "Libellé de la fonction": fonction, "Date de début de la fonction": date_debut,
    }


class TestMaireActuel(unittest.TestCase):
    def setUp(self):
        self._patches = [
            mock.patch("rudi_harvest_toolkit.rne.get_dataset_metadata", return_value={}),
            mock.patch(
                "rudi_harvest_toolkit.rne.selectionner_ressource",
                return_value={"url": "https://static.data.gouv.fr/rne.csv"},
            ),
            mock.patch("rudi_harvest_toolkit.rne.telecharger", return_value="/tmp/rne.csv"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _patch_filtrer_csv(self, lignes):
        p = mock.patch("rudi_harvest_toolkit.rne.filtrer_csv", return_value=iter(lignes))
        p.start()
        self.addCleanup(p.stop)

    def test_trouve_le_maire_en_exercice(self):
        self._patch_filtrer_csv([
            _ligne("DEHAESE", "Olivier", "Maire", "2026-03-20"),
            _ligne("MARTIN", "Julie", "Adjoint au maire", "2026-03-20"),
        ])
        resultat = maire_actuel("35001")
        self.assertEqual(resultat, {
            "nom": "DEHAESE", "prenom": "Olivier", "date_debut_fonction": "2026-03-20",
        })

    def test_ignore_les_autres_fonctions(self):
        self._patch_filtrer_csv([_ligne("MARTIN", "Julie", "Adjoint au maire", "2026-03-20")])
        self.assertIsNone(maire_actuel("35001"))

    def test_aucune_ligne_retourne_none(self):
        self._patch_filtrer_csv([])
        self.assertIsNone(maire_actuel("35001"))

    def test_echec_reseau_retourne_none_jamais_bloquant(self):
        with mock.patch(
            "rudi_harvest_toolkit.rne.get_dataset_metadata", side_effect=RuntimeError("DNS"),
        ):
            self.assertIsNone(maire_actuel("35001"))

    def test_ressource_introuvable_retourne_none(self):
        with mock.patch(
            "rudi_harvest_toolkit.rne.selectionner_ressource", side_effect=ValueError("absente"),
        ):
            self.assertIsNone(maire_actuel("35001"))

    def test_filtre_sur_la_bonne_colonne_et_le_bon_code_insee(self):
        self._patch_filtrer_csv([_ligne("DEHAESE", "Olivier", "Maire", "2026-03-20")])
        from rudi_harvest_toolkit import rne
        maire_actuel("35001")
        rne.filtrer_csv.assert_called_once_with(
            "/tmp/rne.csv", "Code de la commune", "35001",
        )


if __name__ == "__main__":
    unittest.main()
