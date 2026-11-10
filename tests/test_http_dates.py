"""Tests de http_dates.py — sonde best-effort, jamais bloquante (v4 de
rudi-commune-starterkit, Axe 2). Zéro réseau (session mockée)."""
import unittest
from unittest import mock

from rudi_harvest_toolkit.http_dates import (
    date_dataset_ods, entete_derniere_modification, parser_date_iso_stricte,
)


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


class TestParserDateIsoStricte(unittest.TestCase):
    def test_parse_iso_avec_microsecondes_et_offset(self):
        self.assertEqual(
            parser_date_iso_stricte("2026-11-10T06:01:21.851000+00:00"),
            "2026-11-10T06:01:21Z",
        )

    def test_none_sur_entree_vide(self):
        self.assertIsNone(parser_date_iso_stricte(None))
        self.assertIsNone(parser_date_iso_stricte(""))

    def test_none_sur_format_http_jamais_devine(self):
        # Un format HTTP (RFC 2822) n'est pas de l'ISO — jamais inventé en repli.
        self.assertIsNone(parser_date_iso_stricte("Wed, 21 Oct 2026 07:28:00 GMT"))

    def test_none_sur_texte_non_parsable(self):
        self.assertIsNone(parser_date_iso_stricte("pas-une-date"))


class TestDateDatasetOds(unittest.TestCase):
    def _reponse(self, modified):
        r = mock.Mock()
        r.raise_for_status = mock.Mock()
        r.json.return_value = {"metas": {"default": {"modified": modified}}}
        return r

    def test_lit_metas_default_modified(self):
        session = mock.Mock()
        session.get.return_value = self._reponse("2026-11-10T06:01:21.851000+00:00")
        resultat = date_dataset_ods("https://x/datasets/d", session_http=session)
        self.assertEqual(resultat, "2026-11-10T06:01:21Z")

    def test_champ_absent_retourne_none(self):
        session = mock.Mock()
        r = mock.Mock()
        r.raise_for_status = mock.Mock()
        r.json.return_value = {"metas": {"default": {}}}
        session.get.return_value = r
        self.assertIsNone(date_dataset_ods("https://x/datasets/d", session_http=session))

    def test_exception_reseau_retourne_none(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("DNS")
        self.assertIsNone(date_dataset_ods("https://x/datasets/d", session_http=session))

    def test_erreur_http_retourne_none(self):
        session = mock.Mock()
        r = mock.Mock()
        r.raise_for_status = mock.Mock(side_effect=Exception("HTTP 500"))
        session.get.return_value = r
        self.assertIsNone(date_dataset_ods("https://x/datasets/d", session_http=session))


if __name__ == "__main__":
    unittest.main()
