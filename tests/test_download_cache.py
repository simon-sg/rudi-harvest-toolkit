"""Tests de download_cache.py — téléchargement en flux + cache disque MD5/TTL. Zéro réseau."""
import os
import tempfile
import time
import unittest
from unittest import mock

from rudi_harvest_toolkit.download_cache import (
    ErreurTelechargement,
    chemin_cache,
    dossier_cache_defaut,
    invalider,
    purger_cache,
    telecharger,
)


def _reponse_mock(morceaux):
    reponse = mock.Mock()
    reponse.raise_for_status = mock.Mock()
    reponse.iter_content = mock.Mock(return_value=iter(morceaux))
    reponse.close = mock.Mock()
    return reponse


class TestCheminCache(unittest.TestCase):
    def test_meme_url_meme_chemin(self):
        a = chemin_cache("https://exemple.fr/x.csv", dossier="/tmp/x")
        b = chemin_cache("https://exemple.fr/x.csv", dossier="/tmp/x")
        self.assertEqual(a, b)

    def test_urls_differentes_chemins_differents(self):
        a = chemin_cache("https://exemple.fr/a.csv", dossier="/tmp/x")
        b = chemin_cache("https://exemple.fr/b.csv", dossier="/tmp/x")
        self.assertNotEqual(a, b)

    def test_dossier_par_defaut_respecte_variable_environnement(self):
        with mock.patch.dict(os.environ, {"RUDI_HARVEST_CACHE": "/tmp/force-cache"}):
            self.assertEqual(dossier_cache_defaut(), "/tmp/force-cache")


class TestTelecharger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = self._tmp.name

    def test_telecharge_et_met_en_cache(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"abc", b"def"])

        chemin = telecharger(
            "https://exemple.fr/x.csv", dossier=self.dossier, session_http=session
        )

        self.assertTrue(os.path.exists(chemin))
        with open(chemin, "rb") as f:
            self.assertEqual(f.read(), b"abcdef")
        session.get.assert_called_once()

    def test_second_appel_dans_le_ttl_ne_refait_pas_de_requete(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"abc"])

        telecharger("https://exemple.fr/x.csv", dossier=self.dossier, session_http=session)
        telecharger("https://exemple.fr/x.csv", dossier=self.dossier, session_http=session)

        session.get.assert_called_once()

    def test_cache_expire_relance_une_requete(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"abc"])

        chemin = telecharger(
            "https://exemple.fr/x.csv", dossier=self.dossier, ttl_jours=0.0001,
            session_http=session,
        )
        # force l'expiration sans dépendre d'un vrai sommeil
        ancien = time.time() - 3600
        os.utime(chemin, (ancien, ancien))

        telecharger(
            "https://exemple.fr/x.csv", dossier=self.dossier, ttl_jours=0.0001,
            session_http=session,
        )

        self.assertEqual(session.get.call_count, 2)

    def test_ttl_none_est_immortel(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"abc"])
        chemin = telecharger(
            "https://exemple.fr/x.csv", dossier=self.dossier, ttl_jours=None,
            session_http=session,
        )
        ancien = time.time() - 365 * 86400
        os.utime(chemin, (ancien, ancien))

        telecharger(
            "https://exemple.fr/x.csv", dossier=self.dossier, ttl_jours=None,
            session_http=session,
        )
        session.get.assert_called_once()

    def test_plafond_mo_tronque_le_telechargement(self):
        session = mock.Mock()
        morceau = b"0" * 1024 * 1024  # 1 Mo
        session.get.return_value = _reponse_mock([morceau, morceau, morceau])

        chemin = telecharger(
            "https://exemple.fr/gros.csv", dossier=self.dossier,
            plafond_mo=1.5, session_http=session,
        )

        self.assertLessEqual(os.path.getsize(chemin), 2 * 1024 * 1024)
        self.assertGreaterEqual(os.path.getsize(chemin), 1024 * 1024)

    def test_echec_reseau_leve_erreur_explicite(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("DNS")
        with self.assertRaises(ErreurTelechargement):
            telecharger("https://exemple.fr/x.csv", dossier=self.dossier, session_http=session)

    def test_echec_http_leve_erreur_explicite(self):
        session = mock.Mock()
        reponse = mock.Mock()
        reponse.raise_for_status.side_effect = RuntimeError("500")
        session.get.return_value = reponse
        with self.assertRaises(ErreurTelechargement):
            telecharger("https://exemple.fr/x.csv", dossier=self.dossier, session_http=session)

    def test_echec_ecriture_nettoie_le_fichier_temporaire(self):
        session = mock.Mock()
        reponse = _reponse_mock([b"abc"])
        reponse.iter_content.side_effect = OSError("disque plein")
        session.get.return_value = reponse

        with self.assertRaises(ErreurTelechargement):
            telecharger("https://exemple.fr/x.csv", dossier=self.dossier, session_http=session)

        chemin = chemin_cache("https://exemple.fr/x.csv", self.dossier)
        self.assertFalse(os.path.exists(chemin + ".tmp"))
        self.assertFalse(os.path.exists(chemin))


class TestPurgerEtInvalider(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = self._tmp.name

    def test_purger_cache_dossier_absent(self):
        self.assertEqual(purger_cache(dossier="/tmp/inexistant-xyz"), 0)

    def test_purger_cache_supprime_les_vieux_fichiers(self):
        vieux = os.path.join(self.dossier, "vieux")
        recent = os.path.join(self.dossier, "recent")
        for chemin in (vieux, recent):
            with open(chemin, "w") as f:
                f.write("x")
        ancien = time.time() - 40 * 86400
        os.utime(vieux, (ancien, ancien))

        supprimes = purger_cache(dossier=self.dossier, jours=30)

        self.assertEqual(supprimes, 1)
        self.assertFalse(os.path.exists(vieux))
        self.assertTrue(os.path.exists(recent))

    def test_invalider_supprime_l_entree(self):
        session = mock.Mock()
        session.get.return_value = _reponse_mock([b"abc"])
        chemin = telecharger("https://exemple.fr/x.csv", dossier=self.dossier, session_http=session)
        self.assertTrue(os.path.exists(chemin))

        self.assertTrue(invalider("https://exemple.fr/x.csv", dossier=self.dossier))
        self.assertFalse(os.path.exists(chemin))

    def test_invalider_url_absente_retourne_faux(self):
        self.assertFalse(invalider("https://exemple.fr/absent.csv", dossier=self.dossier))


if __name__ == "__main__":
    unittest.main()
