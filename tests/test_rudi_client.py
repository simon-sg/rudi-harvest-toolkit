"""Tests unitaires de rudi_client (config explicite, email de repli) — sans réseau."""
import json
import os
import tempfile
import unittest
from unittest import mock

from rudi_harvest_toolkit.rudi_client import (
    charger_conf_rudi,
    email_par_defaut,
    lister_organisations,
)


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


class TestListerOrganisations(unittest.TestCase):
    def test_expose_organization_list_sans_writer_public(self):
        orgs = [{"organization_id": "org-1", "organization_name": "Rennes Métropole"}]
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.organization_list = orgs
            self.assertEqual(lister_organisations(conf), orgs)
        creer.assert_called_once_with(conf)

    def test_statut_filtre_via_requete_http_directe(self):
        orgs = [{"organization_id": "org-1", "organization_status": "VALIDATED"}]
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = orgs
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            self.assertEqual(lister_organisations(conf, statut="VALIDATED"), orgs)
        sess.get.assert_called_once_with(
            "http://n:3030/catalog/v1/organizations",
            params={"organization_status": "VALIDATED"}, timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
