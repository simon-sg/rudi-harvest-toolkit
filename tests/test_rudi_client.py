"""Tests unitaires de rudi_client (config explicite, email de repli) — sans réseau."""
import json
import os
import tempfile
import unittest

from rudi_harvest_toolkit.rudi_client import charger_conf_rudi, email_par_defaut


class TestChargerConfRudi(unittest.TestCase):
    def test_chemin_absent_retourne_none(self):
        self.assertIsNone(charger_conf_rudi("/chemin/inexistant/rudi_node.json"))

    def test_charge_depuis_chemin_explicite(self):
        conf = {"url": "http://localhost:3030/manager", "usr": "u", "pwd": "p"}
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "rudi_node.json")
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(conf, f)
            self.assertEqual(charger_conf_rudi(chemin), conf)


class TestEmailParDefaut(unittest.TestCase):
    def test_slug_et_domaine(self):
        self.assertEqual(email_par_defaut("Rennes Métropole"), "rennes-metropole@example.org")

    def test_accents_retires(self):
        self.assertEqual(email_par_defaut("Observatoire de l'Environnement"), "observatoire-de-l-environnement@example.org")

    def test_nom_vide_retombe_sur_contact(self):
        self.assertEqual(email_par_defaut(""), "contact@example.org")

    def test_unique_par_nom(self):
        self.assertNotEqual(email_par_defaut("Insee"), email_par_defaut("OEB"))


if __name__ == "__main__":
    unittest.main()
