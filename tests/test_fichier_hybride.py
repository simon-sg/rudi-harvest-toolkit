"""Tests de fichier_hybride.py — empreinte distante + média FILE hybride. Zéro réseau."""
import hashlib
import unittest
import uuid
from unittest import mock

from rudi_harvest_toolkit.fichier_hybride import (
    ErreurEmpreinteDistante,
    FichierTropVolumineux,
    construire_media_hybride,
    empreinte_distante,
    media_id_hybride,
    nom_depuis_url,
    type_fichier_accepte,
)
from rudi_harvest_toolkit.rudi_client import _media_file_deja_complet


def _reponse_mock(morceaux, content_length=None):
    reponse = mock.Mock()
    reponse.raise_for_status = mock.Mock()
    reponse.headers = {"Content-Length": str(content_length)} if content_length is not None else {}
    reponse.iter_content = mock.Mock(return_value=iter(morceaux))
    reponse.close = mock.Mock()
    return reponse


class TestEmpreinteDistante(unittest.TestCase):
    def test_calcule_sha256_et_taille(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"abc", b"def"])

        empreinte = empreinte_distante("https://exemple.fr/x.csv", session_http=session)

        attendu = hashlib.sha256(b"abcdef").hexdigest()
        self.assertEqual(empreinte["hash"], attendu)
        self.assertEqual(empreinte["taille"], 6)
        self.assertEqual(empreinte["algo"], "SHA-256")

    def test_echec_reseau_leve_erreur_explicite(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("DNS")
        with self.assertRaises(ErreurEmpreinteDistante):
            empreinte_distante("https://exemple.fr/x.csv", session_http=session)

    def test_content_length_trop_grand_leve_avant_lecture(self):
        session = mock.Mock()
        reponse = _reponse_mock([b"x" * 100], content_length=1000)
        session.get.return_value = reponse
        with self.assertRaises(FichierTropVolumineux):
            empreinte_distante("https://exemple.fr/x.csv", taille_max=10, session_http=session)

    def test_depassement_pendant_la_lecture_leve(self):
        session = mock.Mock()
        morceau = b"0" * 100
        session.get.return_value = _reponse_mock([morceau, morceau])
        with self.assertRaises(FichierTropVolumineux):
            empreinte_distante("https://exemple.fr/x.csv", taille_max=150, session_http=session)

    def test_taille_max_none_desactive_le_garde_fou(self):
        session = mock.Mock()
        morceau = b"0" * 1000
        session.get.return_value = _reponse_mock([morceau])
        empreinte = empreinte_distante(
            "https://exemple.fr/x.csv", taille_max=None, session_http=session
        )
        self.assertEqual(empreinte["taille"], 1000)


class TestMediaIdHybride(unittest.TestCase):
    def test_deterministe(self):
        a = media_id_hybride("mon-jdd", "https://exemple.fr/x.csv")
        b = media_id_hybride("mon-jdd", "https://exemple.fr/x.csv")
        self.assertEqual(a, b)

    def test_differe_selon_local_id_ou_url(self):
        a = media_id_hybride("jdd-a", "https://exemple.fr/x.csv")
        b = media_id_hybride("jdd-b", "https://exemple.fr/x.csv")
        c = media_id_hybride("jdd-a", "https://exemple.fr/y.csv")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_est_bien_un_uuid_version_4(self):
        identifiant = media_id_hybride("jdd", "https://exemple.fr/x.csv")
        u = uuid.UUID(identifiant)
        self.assertEqual(u.version, 4)


class TestNomDepuisUrl(unittest.TestCase):
    def test_extrait_le_nom_de_fichier(self):
        self.assertEqual(nom_depuis_url("https://exemple.fr/dossier/export.csv"), "export.csv")

    def test_decode_les_caracteres_encodes(self):
        self.assertEqual(
            nom_depuis_url("https://exemple.fr/export%20final.csv"), "export final.csv"
        )

    def test_ignore_la_chaine_de_requete(self):
        self.assertEqual(
            nom_depuis_url("https://exemple.fr/export.csv?where=code_commune=35120"),
            "export.csv",
        )

    def test_chemin_vide_retombe_sur_defaut(self):
        self.assertEqual(nom_depuis_url("https://exemple.fr/"), "donnees")


class TestTypeFichierAccepte(unittest.TestCase):
    def test_type_connu(self):
        self.assertTrue(type_fichier_accepte("text/csv"))

    def test_type_inconnu(self):
        self.assertFalse(type_fichier_accepte("application/x-inconnu"))

    def test_none(self):
        self.assertFalse(type_fichier_accepte(None))


class TestConstruireMediaHybride(unittest.TestCase):
    def test_construit_un_media_complet(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"a,b\n1,2\n"])

        media = construire_media_hybride(
            "mon-jdd",
            "https://exemple.fr/export.csv?where=code_commune=35120",
            media_caption="Export filtré",
            file_type="text/csv",
            session_http=session,
        )

        self.assertEqual(media["media_type"], "FILE")
        self.assertEqual(media["media_name"], "export.csv")
        self.assertEqual(media["connector"]["url"],
                          "https://exemple.fr/export.csv?where=code_commune=35120")
        self.assertEqual(media["connector"]["interface_contract"], "dwnl")
        self.assertEqual(media["file_type"], "text/csv")
        self.assertGreater(media["file_size"], 0)
        self.assertTrue(media["checksum"]["hash"])

    def test_satisfait_media_file_deja_complet(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"contenu"])
        media = construire_media_hybride(
            "mon-jdd", "https://exemple.fr/export.csv", session_http=session,
        )
        self.assertTrue(_media_file_deja_complet(media))

    def test_accepte_une_empreinte_deja_calculee(self):
        media = construire_media_hybride(
            "mon-jdd",
            "https://exemple.fr/export.csv",
            empreinte={"algo": "SHA-256", "hash": "deadbeef", "taille": 42},
        )
        self.assertEqual(media["file_size"], 42)
        self.assertEqual(media["checksum"]["hash"], "deadbeef")

    def test_local_id_manquant_leve(self):
        with self.assertRaises(ValueError):
            construire_media_hybride("", "https://exemple.fr/x.csv", empreinte={"hash": "x", "taille": 1})

    def test_url_manquante_leve(self):
        with self.assertRaises(ValueError):
            construire_media_hybride("jdd", "", empreinte={"hash": "x", "taille": 1})

    def test_empreinte_incomplete_leve(self):
        with self.assertRaises(ValueError):
            construire_media_hybride("jdd", "https://exemple.fr/x.csv", empreinte={"hash": "x"})


if __name__ == "__main__":
    unittest.main()
