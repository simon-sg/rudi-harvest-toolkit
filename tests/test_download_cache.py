"""Tests de download_cache.py — téléchargement en flux + cache disque MD5/TTL. Zéro réseau."""
import os
import tempfile
import time
import unittest
from unittest import mock

import requests

from rudi_harvest_toolkit.download_cache import (
    ErreurTelechargement,
    chemin_cache,
    date_fichier_cache,
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
        session.get.assert_called_once()  # pas de retry sur une erreur d'écriture locale

    def test_connexion_coupee_en_cours_de_flux_relance_la_tentative(self):
        """Backlog rudi-commune-starterkit, fragilité #3 (2026-11-13) : une coupure
        réseau EN COURS de flux (pas seulement un statut HTTP avant réception de la
        réponse) doit relancer le téléchargement depuis le début plutôt que
        d'abandonner directement."""
        session = mock.Mock()
        reponse = mock.Mock()
        reponse.raise_for_status = mock.Mock()
        reponse.close = mock.Mock()

        def _flux_casse():
            yield b"abc"
            raise requests.exceptions.ConnectionError("Connection broken")

        reponse.iter_content.side_effect = [_flux_casse(), iter([b"def"])]
        session.get.return_value = reponse

        with mock.patch("rudi_harvest_toolkit.download_cache.time.sleep"):
            chemin = telecharger(
                "https://exemple.fr/gros.csv", dossier=self.dossier, session_http=session,
            )

        with open(chemin, "rb") as f:
            # Pas de reprise partielle (pas de Range) : la tentative ratée ("abc")
            # est entièrement jetée, seule la tentative réussie compte.
            self.assertEqual(f.read(), b"def")
        self.assertEqual(session.get.call_count, 2)

    def test_connexion_coupee_a_chaque_tentative_leve_apres_le_maximum(self):
        session = mock.Mock()
        reponse = mock.Mock()
        reponse.raise_for_status = mock.Mock()
        reponse.close = mock.Mock()

        def _toujours_casse(**_kwargs):
            def generateur():
                yield b"abc"
                raise requests.exceptions.ChunkedEncodingError("Connection broken")
            return generateur()

        reponse.iter_content.side_effect = _toujours_casse
        session.get.return_value = reponse

        with mock.patch("rudi_harvest_toolkit.download_cache.time.sleep"):
            with self.assertRaises(ErreurTelechargement):
                telecharger(
                    "https://exemple.fr/gros.csv", dossier=self.dossier, session_http=session,
                )

        self.assertEqual(session.get.call_count, 3)  # _MAX_TENTATIVES_FLUX
        chemin = chemin_cache("https://exemple.fr/gros.csv", self.dossier)
        self.assertFalse(os.path.exists(chemin + ".tmp"))
        self.assertFalse(os.path.exists(chemin))

    def test_coupure_puis_reprise_partielle_honoree_par_le_serveur(self):
        """2026-11-14 : quand le serveur honore la reprise (206 + Range/If-Range),
        la tentative suivante ne retélécharge que les octets manquants — pas tout
        depuis le début."""
        reponse_1 = mock.Mock()
        reponse_1.status_code = 200
        reponse_1.headers = {"ETag": '"abc123"'}
        reponse_1.raise_for_status = mock.Mock()
        reponse_1.close = mock.Mock()

        def _flux_casse():
            yield b"part1"
            raise requests.exceptions.ConnectionError("Connection broken")

        reponse_1.iter_content = mock.Mock(return_value=_flux_casse())

        reponse_2 = mock.Mock()
        reponse_2.status_code = 206
        reponse_2.headers = {}
        reponse_2.raise_for_status = mock.Mock()
        reponse_2.close = mock.Mock()
        reponse_2.iter_content = mock.Mock(return_value=iter([b"part2"]))

        session = mock.Mock()
        session.get.side_effect = [reponse_1, reponse_2]

        with mock.patch("rudi_harvest_toolkit.download_cache.time.sleep"):
            chemin = telecharger(
                "https://exemple.fr/gros.csv", dossier=self.dossier, session_http=session,
            )

        with open(chemin, "rb") as f:
            self.assertEqual(f.read(), b"part1part2")
        self.assertEqual(session.get.call_count, 2)
        _, kwargs_2e_appel = session.get.call_args_list[1]
        self.assertEqual(
            kwargs_2e_appel["headers"], {"Range": "bytes=5-", "If-Range": '"abc123"'},
        )

    def test_reprise_refusee_par_le_serveur_retelecharge_depuis_le_debut(self):
        """Serveur qui ignore Range/If-Range (toujours 200, pas de support partiel) :
        repli automatique sur un téléchargement complet, jamais un fichier corrompu
        (ancien contenu + nouveau mélangés)."""
        reponse_1 = mock.Mock()
        reponse_1.status_code = 200
        reponse_1.headers = {"ETag": '"abc123"'}
        reponse_1.raise_for_status = mock.Mock()
        reponse_1.close = mock.Mock()

        def _flux_casse():
            yield b"part1"
            raise requests.exceptions.ConnectionError("Connection broken")

        reponse_1.iter_content = mock.Mock(return_value=_flux_casse())

        reponse_2 = mock.Mock()
        reponse_2.status_code = 200  # pas 206 : le serveur ignore la reprise demandée
        reponse_2.headers = {}
        reponse_2.raise_for_status = mock.Mock()
        reponse_2.close = mock.Mock()
        reponse_2.iter_content = mock.Mock(return_value=iter([b"integral"]))

        session = mock.Mock()
        session.get.side_effect = [reponse_1, reponse_2]

        with mock.patch("rudi_harvest_toolkit.download_cache.time.sleep"):
            chemin = telecharger(
                "https://exemple.fr/gros.csv", dossier=self.dossier, session_http=session,
            )

        with open(chemin, "rb") as f:
            self.assertEqual(f.read(), b"integral")


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


class TestDateFichierCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = self._tmp.name

    def test_retourne_la_mtime_en_iso(self):
        import datetime
        chemin = os.path.join(self.dossier, "f.csv")
        with open(chemin, "w") as f:
            f.write("x")
        horodatage = datetime.datetime(
            2026, 10, 21, 7, 28, 0, tzinfo=datetime.timezone.utc,
        ).timestamp()
        os.utime(chemin, (horodatage, horodatage))
        resultat = date_fichier_cache(chemin)
        self.assertEqual(resultat, "2026-10-21T07:28:00Z")

    def test_fichier_absent_retourne_none(self):
        self.assertIsNone(date_fichier_cache(os.path.join(self.dossier, "absent.csv")))


if __name__ == "__main__":
    unittest.main()
