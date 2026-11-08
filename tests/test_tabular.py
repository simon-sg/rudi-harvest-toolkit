"""Tests de tabular.py — lecture CSV en flux, gzip, filtrage générique. Zéro réseau."""
import gzip
import os
import tempfile
import unittest
from unittest import mock

from rudi_harvest_toolkit.tabular import (
    ColonneIntrouvableError,
    detecter_delimiteur,
    detecter_encodage,
    filtrer_csv,
    iter_lignes_csv,
    lire_csv_filtre,
    normaliser_nom_colonne,
    resoudre_colonne,
)


def _reponse(contenu: bytes, morceau: int = 7):
    reponse = mock.Mock()
    reponse.iter_content.return_value = [
        contenu[i:i + morceau] for i in range(0, len(contenu), morceau)
    ]
    reponse.raise_for_status = mock.Mock()
    reponse.close = mock.Mock()
    return reponse


class TestNormalisationColonnes(unittest.TestCase):
    def test_accents_casse_underscores(self):
        self.assertEqual(
            normaliser_nom_colonne("Code_INSEE-Commune"),
            normaliser_nom_colonne("code insee commune"),
        )
        self.assertEqual(normaliser_nom_colonne("Libellé"), "libelle")
        self.assertEqual(normaliser_nom_colonne("  Code   INSEE  "), "code insee")

    def test_resolution_tolerante(self):
        entetes = ["Code INSEE Commune", "Libellé", "Code Postal"]
        self.assertEqual(resoudre_colonne(entetes, "code_insee_commune"),
                         "Code INSEE Commune")
        self.assertEqual(resoudre_colonne(entetes, "LIBELLE"), "Libellé")
        self.assertEqual(resoudre_colonne(entetes, "code-postal"), "Code Postal")

    def test_resolution_exacte_prioritaire(self):
        entetes = ["Code", "code"]
        self.assertEqual(resoudre_colonne(entetes, "code"), "code")

    def test_colonne_introuvable_message_clair(self):
        with self.assertRaises(ColonneIntrouvableError) as ctx:
            resoudre_colonne(["a", "b"], "insee")
        self.assertIn("insee", str(ctx.exception))
        self.assertIn("'a'", str(ctx.exception))


class TestDetection(unittest.TestCase):
    def test_delimiteurs(self):
        self.assertEqual(detecter_delimiteur("a;b;c\n1;2;3\n"), ";")
        self.assertEqual(detecter_delimiteur("a,b,c\n1,2,3\n"), ",")
        self.assertEqual(detecter_delimiteur("a|b|c\n1|2|3\n"), "|")
        self.assertEqual(detecter_delimiteur("a\tb\tc\n1\t2\t3\n"), "\t")

    def test_encodage_utf8_et_cp1252(self):
        self.assertEqual(detecter_encodage("Libellé;Code\n".encode("utf-8")), "utf-8-sig")
        self.assertEqual(detecter_encodage("Libellé;Code\n".encode("cp1252")), "cp1252")


class TestLectureFichierLocal(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self._dossier.cleanup)

    def _ecrire(self, contenu, nom="f.csv", encoding="utf-8"):
        chemin = os.path.join(self._dossier.name, nom)
        if isinstance(contenu, bytes):
            with open(chemin, "wb") as f:
                f.write(contenu)
        else:
            with open(chemin, "w", encoding=encoding, newline="") as f:
                f.write(contenu)
        return chemin

    def test_filtre_valeur_exacte_colonne_accentuee(self):
        chemin = self._ecrire(
            "Code INSEE Commune;Libellé;Code Postal\n"
            "35120;Gévezé;35510\n"
            "35000;Rennes;35000\n"
            "35120;Gévezé;35520\n"
        )
        lignes = list(filtrer_csv(chemin, "code_insee_commune", "35120"))
        self.assertEqual(len(lignes), 2)
        self.assertTrue(all(l["Code INSEE Commune"] == "35120" for l in lignes))
        self.assertEqual(lignes[0]["Libellé"], "Gévezé")

    def test_valeur_strippee_mais_pas_normalisee(self):
        chemin = self._ecrire("code;nom\n 35120 ;Gévezé\n3512;Rennes\n")
        lignes = list(filtrer_csv(chemin, "CODE", "35120"))
        self.assertEqual([l["nom"] for l in lignes], ["Gévezé"])
        self.assertEqual(list(filtrer_csv(chemin, "code", "GÉVEZÉ")), [])

    def test_lire_csv_filtre_retourne_entetes(self):
        chemin = self._ecrire("a;b\n1;x\n2;y\n")
        lignes, entetes = lire_csv_filtre(chemin, "b", "y")
        self.assertEqual(entetes, ["a", "b"])
        self.assertEqual(lignes, [{"a": "2", "b": "y"}])

    def test_champ_cite_avec_retour_ligne_et_delimiteur(self):
        chemin = self._ecrire(
            'id;commentaire\n1;"ligne\navec;delimiteur"\n2;simple\n'
        )
        lignes = list(iter_lignes_csv(chemin))
        self.assertEqual(len(lignes), 2)
        self.assertEqual(lignes[0]["commentaire"], "ligne\navec;delimiteur")

    def test_gzip_a_la_volee(self):
        contenu = "code;nom\n35120;Gévezé\n35000;Rennes\n".encode("utf-8")
        chemin = self._ecrire(gzip.compress(contenu), nom="ban.csv.gz")
        lignes = list(filtrer_csv(chemin, "code", "35120"))
        self.assertEqual(lignes, [{"code": "35120", "nom": "Gévezé"}])

    def test_encodage_cp1252_detecte(self):
        contenu = "Libellé;Code\nGévezé;35120\n".encode("cp1252")
        chemin = self._ecrire(contenu)
        lignes = list(filtrer_csv(chemin, "libelle", "Gévezé"))
        self.assertEqual(lignes[0]["Code"], "35120")

    def test_fichier_vide(self):
        chemin = self._ecrire(b"")
        self.assertEqual(list(iter_lignes_csv(chemin)), [])

    def test_colonne_absente_leve(self):
        chemin = self._ecrire("a;b\n1;2\n")
        with self.assertRaises(ColonneIntrouvableError):
            list(filtrer_csv(chemin, "code_insee", "35120"))


class TestLectureUrl(unittest.TestCase):
    def test_url_simple(self):
        contenu = b"code;nom\n35120;Geveze\n35000;Rennes\n"
        reponse = _reponse(contenu)
        session = mock.Mock()
        session.get.return_value = reponse

        lignes = list(filtrer_csv(
            "https://exemple.fr/ban.csv", "code", "35120", session_http=session
        ))
        self.assertEqual(lignes, [{"code": "35120", "nom": "Geveze"}])
        session.get.assert_called_once_with(
            "https://exemple.fr/ban.csv", stream=True, timeout=120
        )
        reponse.close.assert_called_once()

    def test_url_gz_decompressee(self):
        contenu = gzip.compress(b"code;nom\n35120;Geveze\n")
        session = mock.Mock()
        session.get.return_value = _reponse(contenu)

        lignes = list(filtrer_csv(
            "https://exemple.fr/dvf.csv.gz", "code", "35120", session_http=session
        ))
        self.assertEqual(lignes, [{"code": "35120", "nom": "Geveze"}])

    def test_url_utilise_la_session_du_module_par_defaut(self):
        session = mock.Mock()
        session.get.return_value = _reponse(b"a;b\n1;2\n")
        with mock.patch("rudi_harvest_toolkit.tabular.session", session):
            lignes = list(iter_lignes_csv("https://exemple.fr/x.csv"))
        self.assertEqual(lignes, [{"a": "1", "b": "2"}])
        session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
