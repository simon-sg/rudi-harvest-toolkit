"""Tests de http_dates.py — sonde best-effort, jamais bloquante (v4 de
rudi-commune-starterkit, Axe 2). Zéro réseau (session mockée)."""
import unittest
from unittest import mock

from rudi_harvest_toolkit.http_dates import entete_derniere_modification


def _reponse(status_code, headers=None):
    r = mock.Mock()
    r.status_code = status_code
    r.headers = headers or {}
    r.close = mock.Mock()
    return r


class TestEnteteDerniereModification(unittest.TestCase):
    def test_lit_last_modified_depuis_head(self):
        session = mock.Mock()
        session.head.return_value = _reponse(200, {"Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"})
        resultat = entete_derniere_modification("https://x", session_http=session)
        self.assertEqual(resultat, "2026-10-21T07:28:00Z")
        session.get.assert_not_called()

    def test_allow_redirects_passe_sur_head(self):
        session = mock.Mock()
        session.head.return_value = _reponse(200, {"Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"})
        entete_derniere_modification("https://x", session_http=session)
        _, kwargs = session.head.call_args
        self.assertTrue(kwargs.get("allow_redirects"))

    def test_absence_last_modified_retourne_none(self):
        session = mock.Mock()
        session.head.return_value = _reponse(200, {})
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))

    def test_date_non_parsable_retourne_none_jamais_devinee(self):
        session = mock.Mock()
        session.head.return_value = _reponse(200, {"Last-Modified": "pas-une-date"})
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))

    def test_exception_reseau_retourne_none(self):
        session = mock.Mock()
        session.head.side_effect = RuntimeError("DNS")
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))

    def test_404_retourne_none_sans_repli_get(self):
        session = mock.Mock()
        session.head.return_value = _reponse(404)
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))
        session.get.assert_not_called()

    def test_403_retourne_none_sans_repli_get(self):
        session = mock.Mock()
        session.head.return_value = _reponse(403)
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))
        session.get.assert_not_called()

    def test_500_retourne_none_sans_repli_get(self):
        session = mock.Mock()
        session.head.return_value = _reponse(500)
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))
        session.get.assert_not_called()

    def test_405_replie_sur_get(self):
        session = mock.Mock()
        session.head.return_value = _reponse(405)
        session.get.return_value = _reponse(200, {"Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"})
        resultat = entete_derniere_modification("https://x", session_http=session)
        self.assertEqual(resultat, "2026-10-21T07:28:00Z")
        session.get.assert_called_once()

    def test_501_replie_sur_get(self):
        session = mock.Mock()
        session.head.return_value = _reponse(501)
        session.get.return_value = _reponse(200, {"Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"})
        resultat = entete_derniere_modification("https://x", session_http=session)
        self.assertEqual(resultat, "2026-10-21T07:28:00Z")

    def test_exception_sur_le_repli_get_retourne_none(self):
        session = mock.Mock()
        session.head.return_value = _reponse(405)
        session.get.side_effect = RuntimeError("DNS")
        self.assertIsNone(entete_derniere_modification("https://x", session_http=session))

    def test_session_par_defaut_utilisee_si_absente(self):
        with mock.patch("rudi_harvest_toolkit.http_dates._session_defaut") as session_defaut:
            session_defaut.head.return_value = _reponse(200, {})
            resultat = entete_derniere_modification("https://x")
        self.assertIsNone(resultat)
        session_defaut.head.assert_called_once()


if __name__ == "__main__":
    unittest.main()
