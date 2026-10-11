"""Tests de publish.py — signature explicite (conf) et suivi des local_id du run.

Aucun réseau : conf=None court-circuite avant toute I/O, et les fonctions de suivi du run
ne touchent qu'un état en mémoire.
"""
import unittest

from rudi_harvest_toolkit import publish


class TestPublierSiConfigue(unittest.TestCase):
    def setUp(self):
        publish.demarrer_nouveau_run()

    def test_conf_none_publication_ignoree(self):
        self.assertFalse(publish.publier_si_configue(None, {"local_id": "x"}, []))
        self.assertEqual(publish.local_ids_publies_ce_run(), set())

    def test_conf_vide_publication_ignoree(self):
        self.assertFalse(publish.publier_si_configue({}, {"local_id": "x"}, []))


class TestSuiviLocalIds(unittest.TestCase):
    def setUp(self):
        publish.demarrer_nouveau_run()

    def test_demarrer_nouveau_run_vide_l_accumulateur(self):
        publish.enregistrer_local_id_publie("x")
        publish.demarrer_nouveau_run()
        self.assertEqual(publish.local_ids_publies_ce_run(), set())

    def test_enregistrer_et_lire(self):
        publish.enregistrer_local_id_publie("a")
        publish.enregistrer_local_id_publie("b")
        self.assertEqual(publish.local_ids_publies_ce_run(), {"a", "b"})

    def test_local_id_vide_ignore(self):
        publish.enregistrer_local_id_publie(None)
        publish.enregistrer_local_id_publie("")
        self.assertEqual(publish.local_ids_publies_ce_run(), set())

    def test_lecture_renvoie_une_copie(self):
        publish.enregistrer_local_id_publie("a")
        copie = publish.local_ids_publies_ce_run()
        copie.add("pollution")
        self.assertEqual(publish.local_ids_publies_ce_run(), {"a"})


if __name__ == "__main__":
    unittest.main()
