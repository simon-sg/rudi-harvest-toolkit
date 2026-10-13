"""Tests unitaires de rudi_client (config explicite, email de repli) — sans réseau."""
import json
import os
import tempfile
import unittest
from unittest import mock

from rudi_harvest_toolkit.rudi_client import (
    _media_file_deja_complet,
    charger_conf_rudi,
    demander_creation_organisation,
    demander_detachement_producteur,
    demander_mise_a_jour_organisation,
    demander_suppression_organisation,
    email_par_defaut,
    lister_organisations,
    marquer_organisations_traitees,
    organisations_nouvellement_validees,
    renvoyer_ressources_noeud,
    ressources_pour_organisations,
    supprimer_dataset_portail,
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


class TestOrganisationsNouvellementValidees(unittest.TestCase):
    def test_exclut_les_organisations_deja_traitees(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat_organisations_validees.json")
            with open(chemin_etat, "w", encoding="utf-8") as f:
                json.dump({"organisations_traitees": ["org-1"]}, f)
            with mock.patch("rudi_harvest_toolkit.rudi_client.lister_organisations",
                             return_value=[{"organization_id": "org-1"},
                                          {"organization_id": "org-2"}]):
                self.assertEqual(
                    organisations_nouvellement_validees({"url": "http://n:3032"}, chemin_etat),
                    ["org-2"],
                )

    def test_aucun_etat_prealable_retourne_toutes_les_validees(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat_organisations_validees.json")
            with mock.patch("rudi_harvest_toolkit.rudi_client.lister_organisations",
                             return_value=[{"organization_id": "org-9"}]):
                self.assertEqual(
                    organisations_nouvellement_validees({"url": "http://n:3032"}, chemin_etat),
                    ["org-9"],
                )

    def test_ne_modifie_pas_le_fichier_etat(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat_organisations_validees.json")
            with mock.patch("rudi_harvest_toolkit.rudi_client.lister_organisations",
                             return_value=[{"organization_id": "org-1"}]):
                organisations_nouvellement_validees({"url": "http://n:3032"}, chemin_etat)
            self.assertFalse(os.path.isfile(chemin_etat))


class TestMarquerOrganisationsTraitees(unittest.TestCase):
    def test_fusionne_avec_etat_existant(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat.json")
            marquer_organisations_traitees(chemin_etat, ["org-1"])
            marquer_organisations_traitees(chemin_etat, ["org-2"])
            with open(chemin_etat, encoding="utf-8") as f:
                self.assertEqual(sorted(json.load(f)["organisations_traitees"]),
                                 ["org-1", "org-2"])


class TestRessourcesPourOrganisations(unittest.TestCase):
    def test_filtre_sur_producer_organization_id(self):
        metas = [
            {"global_id": "g1", "producer": {"organization_id": "org-1"}},
            {"global_id": "g2", "producer": {"organization_id": "org-2"}},
            {"global_id": "g3"},  # pas de producer : jamais sélectionnée
        ]
        self.assertEqual(
            [m["global_id"] for m in ressources_pour_organisations(metas, ["org-1"])],
            ["g1"],
        )


class TestRenvoyerRessourcesNoeud(unittest.TestCase):
    def test_un_appel_par_global_id_avec_pause_entre_chaque(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}
        reponse = mock.Mock(status_code=200, text="")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep") as dodo:
            sess.post.return_value = reponse
            bilan = renvoyer_ressources_noeud(conf, ["g1", "g2", "g3"], pause_s=2.0)
        self.assertEqual(bilan, {"ok": 3, "echecs": []})
        self.assertEqual(sess.post.call_count, 3)
        for appel, gid in zip(sess.post.call_args_list, ["g1", "g2", "g3"]):
            self.assertEqual(appel.args[0], "http://n:3030/catalog/admin/portal/resources/send")
            self.assertEqual(appel.kwargs["json"], [gid])
        # pause entre chaque, pas après le dernier
        self.assertEqual(dodo.call_count, 2)

    def test_echec_sur_un_id_n_interrompt_pas_les_suivants(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}
        rep_ok = mock.Mock(status_code=200, text="")
        rep_ko = mock.Mock(status_code=500, text="Internal Server Error")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            sess.post.side_effect = [rep_ok, rep_ko]
            bilan = renvoyer_ressources_noeud(conf, ["g1", "g2"])
        self.assertEqual(bilan["ok"], 1)
        self.assertEqual(len(bilan["echecs"]), 1)
        self.assertEqual(bilan["echecs"][0][0], "g2")

    def test_exception_reseau_comptee_comme_echec(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            sess.post.side_effect = Exception("réseau indisponible")
            bilan = renvoyer_ressources_noeud(conf, ["g1"])
        self.assertEqual(bilan, {"ok": 0, "echecs": [("g1", "réseau indisponible")]})


class TestMediaFileDejaComplet(unittest.TestCase):
    def test_file_size_et_checksum_hash_presents(self):
        media = {"media_type": "FILE", "file_size": 42191,
                "checksum": {"algo": "SHA-256", "hash": "abc123"}}
        self.assertTrue(_media_file_deja_complet(media))

    def test_file_size_absent(self):
        media = {"media_type": "FILE", "checksum": {"algo": "SHA-256", "hash": "abc123"}}
        self.assertFalse(_media_file_deja_complet(media))

    def test_checksum_absent(self):
        media = {"media_type": "FILE", "file_size": 42191}
        self.assertFalse(_media_file_deja_complet(media))

    def test_checksum_sans_hash(self):
        media = {"media_type": "FILE", "file_size": 42191, "checksum": {"algo": "SHA-256"}}
        self.assertFalse(_media_file_deja_complet(media))

    def test_placeholder_mode_copie_non_complet(self):
        # Le FILE "placeholder" posé par mode.py avant upload (mode copie) n'a ni
        # file_size ni checksum tant que publier_dataset() ne l'a pas uploadé.
        media = {"media_type": "FILE", "connector": {"url": "À_RENSEIGNER_APRES_DEPOT_SUR_NOEUD"}}
        self.assertFalse(_media_file_deja_complet(media))


class TestDemanderCreationOrganisation(unittest.TestCase):
    ORG = {"organization_id": "org-1", "organization_name": "MyDataBall",
           "organization_summary": "Producteur de données ouvertes."}

    def test_sans_url_portail_no_op(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))
        sess.post.assert_not_called()

    def test_succes_retourne_luuid_du_portail_meme_different_de_celui_envoye(self):
        """Vérifié en conditions réelles contre le portail ROOB local : le portail
        assigne son propre UUID, différent de celui qu'on lui propose dans le corps."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_create = mock.Mock(status_code=200)
        rep_create.json.return_value = "uuid-assigne-par-le-portail"
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = [rep_token, rep_create]
            resultat = demander_creation_organisation(conf, self.ORG)
        self.assertEqual(resultat, "uuid-assigne-par-le-portail")
        self.assertEqual(sess.post.call_count, 2)  # jamais de 3e appel (linked-producers, inutile)
        args_create, kwargs_create = sess.post.call_args_list[1]
        self.assertEqual(args_create[0], "http://portail.test/strukture/v1/organizations/request")
        self.assertEqual(kwargs_create["json"]["organization_id"], "org-1")  # envoyé, mais ignoré côté portail
        self.assertEqual(kwargs_create["headers"]["Authorization"], "Bearer tok123")

    def test_auth_portail_echoue_retourne_none_sans_autre_appel(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))
        sess.post.assert_called_once()  # seule la tentative de token, rien après

    def test_creation_refusee_par_le_portail_retourne_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_create = mock.Mock(status_code=403, text="Forbidden")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = [rep_token, rep_create]
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))
        self.assertEqual(sess.post.call_count, 2)


class TestDemanderMiseAJourOrganisation(unittest.TestCase):
    ORG = {"organization_id": "uuid-portail", "organization_name": "MyDataBall",
           "organization_summary": "Producteur de données ouvertes."}

    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_mise_a_jour_organisation(conf, self.ORG))
        sess.put.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_put_vers_organizations_request(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_update = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.put.return_value = rep_update
            self.assertTrue(demander_mise_a_jour_organisation(conf, self.ORG))
        sess.post.assert_called_once()  # token uniquement
        args, kwargs = sess.put.call_args
        self.assertEqual(args[0], "http://portail.test/strukture/v1/organizations/request")
        self.assertEqual(kwargs["json"], self.ORG)  # id portail conservé (jamais réassigné)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_auth_portail_echoue_false_sans_put(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_mise_a_jour_organisation(conf, self.ORG))
        sess.put.assert_not_called()

    def test_mise_a_jour_refusee_par_le_portail_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_update = mock.Mock(status_code=400, text="description too long")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.put.return_value = rep_update
            self.assertFalse(demander_mise_a_jour_organisation(conf, self.ORG))


class TestDemanderDetachementProducteur(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_detachement_producteur(conf, "uuid-portail"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_delete_vers_linked_producers_request_uuid(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertTrue(demander_detachement_producteur(conf, "uuid-portail"))
        args, kwargs = sess.delete.call_args
        self.assertEqual(args[0], "http://portail.test/strukture/v1/linked-producers/request/uuid-portail")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_auth_portail_echoue_false_sans_delete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_detachement_producteur(conf, "uuid-portail"))
        sess.delete.assert_not_called()

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_401 = mock.Mock(status_code=401, text="Unauthorized")
        rep_ok = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.side_effect = [rep_401, rep_ok]
            self.assertTrue(demander_detachement_producteur(conf, "uuid-portail"))
        self.assertEqual(sess.post.call_count, 2)  # token initial + renouvellement
        self.assertEqual(sess.delete.call_count, 2)

    def test_echec_404_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(demander_detachement_producteur(conf, "uuid-portail"))


class TestDemanderSuppressionOrganisation(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_delete_vers_organizations_request_uuid(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=204)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertTrue(demander_suppression_organisation(conf, "uuid-portail"))
        args, kwargs = sess.delete.call_args
        self.assertEqual(args[0], "http://portail.test/strukture/v1/organizations/request/uuid-portail")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_auth_portail_echoue_false_sans_delete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_401 = mock.Mock(status_code=401, text="Unauthorized")
        rep_ok = mock.Mock(status_code=204)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.side_effect = [rep_401, rep_ok]
            self.assertTrue(demander_suppression_organisation(conf, "uuid-portail"))
        self.assertEqual(sess.post.call_count, 2)  # token initial + renouvellement
        self.assertEqual(sess.delete.call_count, 2)

    def test_echec_404_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(demander_suppression_organisation(conf, "uuid-portail"))


class TestSupprimerDatasetPortail(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(supprimer_dataset_portail(conf, "gid-1"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_delete_vers_kalim_resources(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertTrue(supprimer_dataset_portail(conf, "gid-1"))
        args, kwargs = sess.delete.call_args
        self.assertEqual(args[0], "http://portail.test/kalim/v1/resources/gid-1")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_401 = mock.Mock(status_code=401, text="Unauthorized")
        rep_ok = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.side_effect = [rep_401, rep_ok]
            self.assertTrue(supprimer_dataset_portail(conf, "gid-1"))
        self.assertEqual(sess.post.call_count, 2)  # token initial + renouvellement
        self.assertEqual(sess.delete.call_count, 2)

    def test_echec_404_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(supprimer_dataset_portail(conf, "gid-1"))


if __name__ == "__main__":
    unittest.main()
