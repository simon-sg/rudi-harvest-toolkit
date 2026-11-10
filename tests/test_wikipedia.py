"""Tests de wikipedia.py — désambiguïsation Wikidata + extrait MediaWiki, cache. Zéro
réseau (session HTTP mockée)."""
import json
import os
import tempfile
import unittest
from unittest import mock

from rudi_harvest_toolkit.commune import CodeInseeInvalide
from rudi_harvest_toolkit.wikipedia import resumer_commune_wikipedia

_EXTRAIT_LONG = ("Gévezé est une commune française. " * 10).strip()  # > 250 caractères


def _sparql_reponse(bindings):
    r = mock.Mock()
    r.raise_for_status = mock.Mock()
    r.json.return_value = {"results": {"bindings": bindings}}
    return r


def _extraits_reponse(pages):
    r = mock.Mock()
    r.raise_for_status = mock.Mock()
    r.json.return_value = {"query": {"pages": pages}}
    return r


def _infos_reponse(superficie=None, gentile=None):
    binding = {}
    if superficie is not None:
        binding["superficie"] = {"type": "literal", "value": str(superficie)}
    if gentile is not None:
        binding["gentile"] = {"type": "literal", "value": gentile, "xml:lang": "fr"}
    r = mock.Mock()
    r.raise_for_status = mock.Mock()
    r.json.return_value = {"results": {"bindings": [binding] if binding else []}}
    return r


def _binding(qid, titre, type_qid=None):
    b = {
        "item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"},
        "article": {"type": "uri", "value": f"https://fr.wikipedia.org/wiki/{titre}"},
    }
    if type_qid:
        b["type"] = {"type": "uri", "value": f"http://www.wikidata.org/entity/{type_qid}"}
    return b


class TestResumerCommuneWikipedia(unittest.TestCase):
    def test_resout_et_retourne_extrait(self):
        session = mock.Mock()
        session.get.side_effect = [
            _sparql_reponse([_binding("Q12345", "Gévezé", "Q484170")]),
            _extraits_reponse({"1": {"title": "Gévezé", "extract": _EXTRAIT_LONG}}),
            _infos_reponse(superficie=29.55, gentile="Gévézéens"),
        ]
        resultat = resumer_commune_wikipedia("35120", session_http=session)
        self.assertIsNotNone(resultat)
        self.assertEqual(resultat["qid"], "Q12345")
        self.assertEqual(resultat["summary"], _EXTRAIT_LONG)
        self.assertEqual(resultat["url"], "https://fr.wikipedia.org/wiki/G%C3%A9vez%C3%A9")
        self.assertEqual(resultat["superficie_km2"], 29.55)
        self.assertEqual(resultat["gentile"], "Gévézéens")

    def test_infos_complementaires_absentes_omises_jamais_devinees(self):
        session = mock.Mock()
        session.get.side_effect = [
            _sparql_reponse([_binding("Q1", "Acigné", "Q484170")]),
            _extraits_reponse({"1": {"title": "Acigné", "extract": _EXTRAIT_LONG}}),
            _infos_reponse(),
        ]
        resultat = resumer_commune_wikipedia("35001", session_http=session)
        self.assertNotIn("superficie_km2", resultat)
        self.assertNotIn("gentile", resultat)

    def test_echec_infos_complementaires_ninvalide_pas_le_resume(self):
        session = mock.Mock()
        session.get.side_effect = [
            _sparql_reponse([_binding("Q1", "Acigné", "Q484170")]),
            _extraits_reponse({"1": {"title": "Acigné", "extract": _EXTRAIT_LONG}}),
            RuntimeError("DNS"),
        ]
        resultat = resumer_commune_wikipedia("35001", session_http=session)
        self.assertIsNotNone(resultat)
        self.assertEqual(resultat["summary"], _EXTRAIT_LONG)
        self.assertNotIn("superficie_km2", resultat)

    def test_aucune_entite_retourne_none(self):
        session = mock.Mock()
        session.get.return_value = _sparql_reponse([])
        self.assertIsNone(resumer_commune_wikipedia("35120", session_http=session))

    def test_entite_sans_sitelink_retourne_none(self):
        session = mock.Mock()
        binding_sans_article = {"item": {"value": "http://www.wikidata.org/entity/Q1"}}
        session.get.return_value = _sparql_reponse([binding_sans_article])
        self.assertIsNone(resumer_commune_wikipedia("35120", session_http=session))

    def test_extrait_trop_court_retourne_none(self):
        session = mock.Mock()
        session.get.side_effect = [
            _sparql_reponse([_binding("Q1", "Hameau")]),
            _extraits_reponse({"1": {"title": "Hameau", "extract": "Trop court."}}),
        ]
        resultat = resumer_commune_wikipedia("35120", session_http=session, longueur_min=250)
        self.assertIsNone(resultat)

    def test_desambiguise_plusieurs_entites_prefere_commune_de_france(self):
        session = mock.Mock()
        session.get.side_effect = [
            _sparql_reponse([
                _binding("Q999", "Autre-chose"),
                _binding("Q111", "Gévezé", "Q484170"),
            ]),
            _extraits_reponse({"1": {"title": "Gévezé", "extract": _EXTRAIT_LONG}}),
            _infos_reponse(),
        ]
        resultat = resumer_commune_wikipedia("35096", session_http=session)
        self.assertEqual(resultat["qid"], "Q111")

    def test_page_manquante_retourne_none(self):
        session = mock.Mock()
        session.get.side_effect = [
            _sparql_reponse([_binding("Q1", "Inconnu")]),
            _extraits_reponse({"-1": {"title": "Inconnu", "missing": ""}}),
        ]
        self.assertIsNone(resumer_commune_wikipedia("35120", session_http=session))

    def test_echec_reseau_retourne_none_jamais_bloquant(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("DNS")
        self.assertIsNone(resumer_commune_wikipedia("35120", session_http=session))

    def test_code_insee_invalide_leve_avant_tout_appel_reseau(self):
        session = mock.Mock()
        with self.assertRaises(CodeInseeInvalide):
            resumer_commune_wikipedia("ABC12", session_http=session)
        session.get.assert_not_called()

    def test_cache_evite_un_second_appel_reseau(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = mock.Mock()
            session.get.side_effect = [
                _sparql_reponse([_binding("Q1", "Gévezé", "Q484170")]),
                _extraits_reponse({"1": {"title": "Gévezé", "extract": _EXTRAIT_LONG}}),
                _infos_reponse(),
            ]
            premier = resumer_commune_wikipedia("35120", session_http=session, dossier_cache=tmp)
            self.assertIsNotNone(premier)

            session2 = mock.Mock()
            second = resumer_commune_wikipedia("35120", session_http=session2, dossier_cache=tmp)
            self.assertEqual(second, premier)
            session2.get.assert_not_called()

    def test_cache_negatif_evite_aussi_un_second_appel(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = mock.Mock()
            session.get.return_value = _sparql_reponse([])
            self.assertIsNone(resumer_commune_wikipedia("35120", session_http=session, dossier_cache=tmp))

            session2 = mock.Mock()
            self.assertIsNone(resumer_commune_wikipedia("35120", session_http=session2, dossier_cache=tmp))
            session2.get.assert_not_called()

    def test_cache_expire_relance_un_appel_reseau(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "wikipedia_commune_35120.json")
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump({}, f)
            vieux = os.path.getmtime(chemin) - 40 * 86400
            os.utime(chemin, (vieux, vieux))

            session = mock.Mock()
            session.get.side_effect = [
                _sparql_reponse([_binding("Q1", "Gévezé", "Q484170")]),
                _extraits_reponse({"1": {"title": "Gévezé", "extract": _EXTRAIT_LONG}}),
                _infos_reponse(),
            ]
            resultat = resumer_commune_wikipedia(
                "35120", session_http=session, dossier_cache=tmp, ttl_jours=30,
            )
            self.assertIsNotNone(resultat)
            self.assertEqual(session.get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
