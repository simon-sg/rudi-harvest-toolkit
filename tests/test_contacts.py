"""Tests de contacts.py — extraction/résolution de contacts, migré de
moissonneuse-batteuse (v3 de rudi-commune-starterkit, Axe 2). Zéro réseau."""
import unittest

from rudi_harvest_toolkit.contacts import (
    _desobfusquer_email,
    _email_valide,
    contacter_pardefaut,
    extraire_contacts_datagouv,
    resoudre_contacts,
)


class TestDesobfusquerEmail(unittest.TestCase):
    def test_crochets_at(self):
        self.assertEqual(_desobfusquer_email("nom[@]domaine.fr"), "nom@domaine.fr")

    def test_at_entre_crochets_texte(self):
        self.assertEqual(_desobfusquer_email("nom[at]domaine.fr"), "nom@domaine.fr")

    def test_parentheses_at(self):
        self.assertEqual(_desobfusquer_email("nom(at)domaine.fr"), "nom@domaine.fr")

    def test_email_deja_valide_inchange(self):
        self.assertEqual(_desobfusquer_email("nom@domaine.fr"), "nom@domaine.fr")

    def test_vide(self):
        self.assertEqual(_desobfusquer_email(""), "")


class TestEmailValide(unittest.TestCase):
    def test_valide(self):
        self.assertTrue(_email_valide("nom@domaine.fr"))

    def test_invalide_sans_arobase(self):
        self.assertFalse(_email_valide("nom-domaine.fr"))

    def test_invalide_obfusque_non_nettoye(self):
        self.assertFalse(_email_valide("nom[@]domaine.fr"))

    def test_vide_ou_none(self):
        self.assertFalse(_email_valide(""))
        self.assertFalse(_email_valide(None))


class TestExtraireContactsDatagouv(unittest.TestCase):
    def test_contact_valide_extrait(self):
        metadata = {"contact_points": [
            {"name": "Colin Maudry", "email": "colin@colmo.tech", "role": "creator"},
        ]}
        self.assertEqual(extraire_contacts_datagouv(metadata), [
            {"contact_name": "Colin Maudry", "email": "colin@colmo.tech", "role": "creator"},
        ])

    def test_email_obfusque_desobfusque(self):
        metadata = {"contact_points": [{"name": "INSEE", "email": "support[@]insee.fr"}]}
        self.assertEqual(extraire_contacts_datagouv(metadata)[0]["email"], "support@insee.fr")

    def test_sans_name_direct_utilise_organization(self):
        metadata = {"contact_points": [
            {"email": "contact@colmo.tech", "organization": {"name": "Colmo"}},
        ]}
        self.assertEqual(extraire_contacts_datagouv(metadata)[0]["contact_name"], "Colmo")

    def test_email_invalide_exclu(self):
        metadata = {"contact_points": [{"name": "Sans email valide", "email": "pas-un-email"}]}
        self.assertEqual(extraire_contacts_datagouv(metadata), [])

    def test_role_absent_devient_contact(self):
        metadata = {"contact_points": [{"name": "X", "email": "x@y.fr"}]}
        self.assertEqual(extraire_contacts_datagouv(metadata)[0]["role"], "contact")

    def test_aucun_contact_point(self):
        self.assertEqual(extraire_contacts_datagouv({}), [])


class TestContacterPardefaut(unittest.TestCase):
    def test_email_derive_du_nom(self):
        contact = contacter_pardefaut("INSEE")
        self.assertEqual(contact, {"contact_name": "INSEE", "email": "insee@example.org"})

    def test_email_defaut_surchargeable(self):
        contact = contacter_pardefaut("INSEE", email_defaut="autre@example.org")
        self.assertEqual(contact["email"], "autre@example.org")

    def test_nom_vide_repli_contact(self):
        self.assertEqual(contacter_pardefaut("")["contact_name"], "Contact")


class TestResoudreContacts(unittest.TestCase):
    def test_premier_contact_source_valide_retourne(self):
        contacts = resoudre_contacts(
            [{"contact_name": "Colin Maudry", "email": "colin@colmo.tech"}], "Colmo",
        )
        self.assertEqual(contacts, [{"contact_name": "Colin Maudry", "email": "colin@colmo.tech"}])

    def test_contact_source_email_obfusque_desobfusque(self):
        contacts = resoudre_contacts(
            [{"contact_name": "INSEE", "email": "support[@]insee.fr"}], "INSEE",
        )
        self.assertEqual(contacts[0]["email"], "support@insee.fr")

    def test_contact_source_email_invalide_repli_generique(self):
        contacts = resoudre_contacts([{"contact_name": "X", "email": "pas-un-email"}], "INSEE")
        self.assertEqual(contacts, [{"contact_name": "INSEE", "email": "insee@example.org"}])

    def test_sans_contacts_source_repli_generique(self):
        contacts = resoudre_contacts([], "INSEE")
        self.assertEqual(contacts, [{"contact_name": "INSEE", "email": "insee@example.org"}])

    def test_email_defaut_surchargeable_sur_repli(self):
        contacts = resoudre_contacts([], "INSEE", email_defaut="autre@example.org")
        self.assertEqual(contacts[0]["email"], "autre@example.org")


if __name__ == "__main__":
    unittest.main()
