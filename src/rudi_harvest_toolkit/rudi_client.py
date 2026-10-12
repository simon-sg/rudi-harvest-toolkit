"""Publication pure vers un nœud RUDI (métadonnées + médias).

Extrait de ``connectors/rudi_node.py`` de moissonneuse-batteuse, en ne conservant que
la partie publication : rien du cycle de vie du nœud (conteneur Podman, process natifs,
état Git) n'est repris ici — ces fonctions dépendent de chemins absolus propres à une
machine donnée et restent hors du périmètre du toolkit.

La configuration du nœud est désormais chargée depuis un **chemin explicite**
(``charger_conf_rudi(chemin)``) et non plus depuis un répertoire dérivé de ``__file__``.
"""
import json
import os
import re
import time
import unicodedata
import uuid
from urllib.parse import urlparse

from rudi_node_write.rudi_node_writer import RudiNodeWriter
from rudi_node_write.connectors.rudi_node_auth import RudiNodeAuth
from rudi_node_write.rudi_types.rudi_media import RudiMediaFile
from rudi_node_write.rudi_types.rudi_meta import RudiMetadata

from .http import session


# ---------------------------------------------------------------------------
# Contacts : email de repli générique (migré de connectors/contacts.py)
# ---------------------------------------------------------------------------

# Domaine fallback quand aucune source ne fournit d'email valide.
# RFC 2606 : domaine réservé, ne recevra jamais de courrier.
_DOMAINE_DEFAUT = "example.org"


def _slug_email(nom: str) -> str:
    """Slug ASCII minuscule utilisable comme local-part d'email (sans accents/espaces)."""
    n = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n[:64] or "contact"


def email_par_defaut(nom: str) -> str:
    """Email de repli **unique par nom** sous le domaine réservé example.org (RFC 2606).

    À utiliser partout où un email fallback est nécessaire, pour ne pas faire collapser
    les contacts dédupliqués par email côté nœud (le nœud RUDI déduplique les contacts
    par email : un email partagé ferait collapser tous les replis sur un seul contact)."""
    return f"{_slug_email(nom)}@{_DOMAINE_DEFAUT}"


# ---------------------------------------------------------------------------
# Configuration du nœud
# ---------------------------------------------------------------------------

def charger_conf_rudi(chemin: str) -> dict | None:
    """Charge la config du nœud RUDI depuis un chemin explicite, ou None si absente.

    La config est un dict ``url``/``url_catalog``/``usr``/``pwd``. ``url_catalog`` est
    facultatif : voir ``url_catalog()`` pour le repli.
    """
    if not os.path.isfile(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def noeud_pret(conf: dict) -> bool:
    """Vérifie que le nœud est vraiment exploitable, pas seulement qu'il écoute.

    On sonde `/manager/conf` — l'endpoint que la lib de publication interroge en premier
    (catalogPubUrl, storagePubUrl, backPath). Un simple GET sur la racine ne suffit pas :
    juste après un `podman start`, la racine répond déjà 200 alors que `/manager/conf`
    renvoie encore 500 pendant ~20 s, et toute publication lancée dans cet intervalle
    échoue sur « This node version is not compatible with this object »."""
    try:
        r = session.get(conf["url"].rstrip("/") + "/manager/conf", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def url_catalog(conf: dict) -> str:
    """URL de l'API catalog du nœud, sans slash final.

    Prend `url_catalog` de la config si présent ; sinon dérive l'URL du manager sur
    le port 3030 — la disposition de l'image Docker. Ce repli est faux dès qu'un nœud
    n'est pas bâti sur cette image : le nœud source expose son catalog sur 4030, et
    sans ce champ il irait interroger le catalog de son voisin (ou, celui-ci arrêté,
    retomberait silencieusement sur la version par défaut).
    """
    if conf.get("url_catalog"):
        return conf["url_catalog"].rstrip("/")
    parsed = urlparse(conf["url"].rstrip("/"))
    return f"{parsed.scheme}://{parsed.hostname}:3030/catalog"


def _api_version(conf: dict) -> str:
    """Récupère la version de l'API catalog du nœud RUDI."""
    try:
        return session.get(f"{url_catalog(conf)}/version", timeout=5).text.strip()
    except Exception as e:
        print(f"  [RUDI] AVERTISSEMENT : impossible de récupérer la version de l'API ({e}), valeur par défaut 1.4.0 utilisée.")
        return "1.4.0"


def _creer_writer(conf: dict) -> RudiNodeWriter:
    auth = RudiNodeAuth(usr=conf["usr"], pwd=conf["pwd"])
    return RudiNodeWriter(pm_url=conf["url"] + "/manager", auth=auth)


def _reinjecter_summary_html(rudi_metadata: dict, meta_json: dict) -> dict:
    """`rudi_node_write` (1.4.4, dernière version publiée) ne modélise que `lang`/`text`
    pour `summary[]` — son aller-retour from_json()/to_json() perd silencieusement `html`
    (le champ RichDictionaryEntry que le portail sait afficher depuis sa v3.3.2, voir
    markdown.py). On le réinjecte après coup, apparié par `lang`."""
    htmls = {e.get("lang"): e["html"] for e in rudi_metadata.get("summary", []) if e.get("html")}
    if not htmls:
        return meta_json
    for entry in meta_json.get("summary", []):
        html = htmls.get(entry.get("lang"))
        if html:
            entry["html"] = html
    return meta_json


def _put_metadata(writer: RudiNodeWriter, rudi_metadata: dict) -> None:
    """Équivalent de `writer.put_metadata(rudi_metadata)` (validations/normalisations de
    la lib conservées via RudiMetadata.from_json()), sans perdre `summary[].html` —
    voir `_reinjecter_summary_html`.

    Sérialise via `to_json_str()` (ce que `put_metadata()` utilise réellement en interne
    pour construire le corps de la requête), pas via `to_json()` : ce dernier a un bug
    dans la lib pour les champs de type liste de `Serializable` (`summary`/`synopsis`) —
    `clean_nones()` les ramène à des `list` Python nues avant le test `isinstance(val,
    Serializable)` du bloc liste, qui porte alors sur la liste elle-même (toujours fausse)
    au lieu de chaque élément : les objets `RudiDictionaryEntry` ressortent tels quels,
    non convertis en dict. `to_json_str()` l'évite en passant par `json.dumps(default=...)`,
    qui convertit chaque objet individuellement quelle que soit sa position."""
    meta_obj = RudiMetadata.from_json(rudi_metadata)
    meta_json = json.loads(meta_obj.to_json_str(ensure_ascii=True))
    meta_json = _reinjecter_summary_html(rudi_metadata, meta_json)
    writer.connector.put_catalog("resources", meta_json)


def _media_id_v4(existant: dict | None, nom_fichier: str) -> str:
    """Réutilise le media_id existant sur le nœud (UUIDv4), sinon en génère un."""
    if existant:
        for m in existant.get("available_formats", []):
            if m.get("media_name") == nom_fichier:
                return m["media_id"]
    return str(uuid.uuid4())


def toutes_metadonnees_rudi(conf: dict) -> list[dict]:
    """Retourne la liste de tous les datasets enregistrés sur le nœud RUDI."""
    writer = _creer_writer(conf)
    return writer.filter_metadata_list({})


def lister_organisations(conf: dict, statut: str | None = None) -> list[dict]:
    """Liste les organisations déclarées sur le nœud RUDI local.

    Sans ``statut`` : point d'entrée public minimal autour de
    ``RudiNodeWriter.organization_list`` (dicts ``organization_id``/
    ``organization_name``/``organization_caption``/``organization_summary`` …) —
    expose la liste sans rendre ``_creer_writer`` public. Nécessaire au rattrapage
    des organisations d'un nœud déjà peuplé lors d'un raccordement portail
    (``moissonneur-ods --raccorder-portail --scenario peuple``).

    Avec ``statut`` (ex. ``"VALIDATED"``, ``"DRAFT"``...) : filtre côté nœud sur
    ``organization_status`` — requête HTTP directe (pas via ``organization_list``,
    qui ne supporte pas ce filtre), car ce champ n'est renseigné que par le
    **rapport portail** reçu par le nœud quand un humain valide l'organisation
    dans l'UI Strukture (``PUT {noeud}/organizations/:id/report`` côté
    rudi-catalog, ``reportController.treatOrgnizationsReports``) — c'est le
    mécanisme de détection utilisé pour le renvoi automatique des ressources
    bloquées par une organisation en attente de validation.
    """
    if statut is None:
        return _creer_writer(conf).organization_list
    reponse = session.get(f"{url_catalog(conf)}/v1/organizations",
                          params={"organization_status": statut}, timeout=30)
    reponse.raise_for_status()
    return reponse.json()


def _media_file_deja_complet(media: dict) -> bool:
    """Un média ``FILE`` déjà entièrement formé par l'appelant (``file_size`` +
    ``checksum.hash`` déjà renseignés) — jamais destiné à être uploadé par
    ``publier_dataset`` (ex. empreinte calculée une fois sur un fichier distant,
    jamais stocké sur notre nœud). Distingue ce cas d'un FILE « placeholder » en
    attente d'upload (mode copie), pour ne pas le faire disparaître silencieusement
    du nettoyage Local→Rudi qui suit."""
    return bool(media.get("file_size")) and bool((media.get("checksum") or {}).get("hash"))


def _token_portail(url_portail: str, usr: str, pwd: str) -> str:
    """Token OAuth2 (client_credentials) auprès du **portail** (pas le nœud), avec les
    identifiants du compte ROBOT — même pattern que
    ``moissonneur-ods/portail_client.py::obtenir_token_robot()``, éprouvé contre le
    portail ROOB local. Lève une exception si le portail refuse (401 ``invalid_client``
    notamment, si ce compte n'est pas enregistré côté ACL comme client OAuth2 — vérifier
    avec l'équipe qui a fourni les identifiants dans ce cas)."""
    r = session.post(
        f"{url_portail}/oauth2/token",
        auth=(usr, pwd),
        data={"grant_type": "client_credentials", "username": usr, "password": pwd},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def demander_creation_organisation(conf: dict, organization: dict) -> str | None:
    """Demande la création d'une nouvelle organisation productrice **auprès du portail**
    (``POST {url_portail}/strukture/v1/organizations/request``, rôle PROVIDER requis —
    exactement celui du compte ROBOT du nœud), puis son rattachement à notre provider
    (``POST .../linked-producers/request/{uuid}``).

    À la différence d'un simple ``PUT /organizations`` sur le **nœud** (ce que ce module
    fait par ailleurs pour que la ressource publiée référence un ``organization_id``
    valide dès maintenant, sans attendre), cet appel déclenche une vraie tâche BPMN dans
    la file d'un modérateur portail — c'est la condition pour qu'``organization_status``
    passe un jour à ``VALIDATED`` (champ renseigné sur le nœud uniquement par le *rapport*
    que le portail renvoie après validation humaine, jamais par le nœud lui-même). Sans
    cet appel, une organisation créée seulement sur le nœud n'est jamais soumise à
    validation et reste invisible du portail — c'est le bug corrigé ici.

    Nécessite ``conf["url_portail"]`` (optionnel — absent : no-op, retourne ``None``,
    comportement historique sans portail intégré préservé). Toujours **best-effort** :
    ne lève jamais, journalise et retourne ``None`` en cas d'échec — ne bloque jamais la
    publication du dataset lui-même, qui doit pouvoir avancer même si le portail est
    indisponible ou si l'authentification portail échoue.
    """
    url_portail = conf.get("url_portail")
    if not url_portail:
        return None
    try:
        token = _token_portail(url_portail, conf["usr"], conf["pwd"])
    except Exception as e:
        print(f"  [RUDI] AVERTISSEMENT : auth portail échouée, pas de demande de validation d'organisation envoyée ({e})")
        return None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    corps = {
        "organization_id": organization["organization_id"],
        "organization_name": organization.get("organization_name", ""),
    }
    if organization.get("organization_summary"):
        corps["organization_summary"] = organization["organization_summary"]
    try:
        r = session.post(f"{url_portail.rstrip('/')}/strukture/v1/organizations/request",
                          json=corps, headers=headers, timeout=30)
        if r.status_code >= 400:
            print(f"  [RUDI] AVERTISSEMENT : demande de création d'organisation refusée par le portail "
                  f"({r.status_code}) : {r.text[:200]}")
            return None
        org_uuid = r.json()
        r2 = session.post(f"{url_portail.rstrip('/')}/strukture/v1/linked-producers/request/{org_uuid}",
                           headers=headers, timeout=30)
        if r2.status_code >= 400:
            print(f"  [RUDI] AVERTISSEMENT : demande de rattachement provider refusée ({r2.status_code}) : {r2.text[:200]}")
        print(f"  [RUDI] demande de validation portail envoyée pour l'organisation « {corps['organization_name']} » (uuid={org_uuid})")
        return org_uuid
    except Exception as e:
        print(f"  [RUDI] AVERTISSEMENT : échec de la demande de validation portail de l'organisation : {e}")
        return None


def publier_dataset(
    conf: dict,
    rudi_metadata: dict,
    fichiers_filtres: list[str],
) -> None:
    """
    Publie un dataset sur le nœud RUDI local.

    conf             : dict avec url/usr/pwd (contenu de rudi_node.json)
    rudi_metadata    : dict au format RUDI (issu de construire_rudi_metadata())
    fichiers_filtres : liste de chemins vers les fichiers filtrés à uploader
                       dans le même ordre que available_formats[0..n-1]
    """
    writer = _creer_writer(conf)

    # Cherche si le dataset existe déjà sur le nœud (pour réutiliser global_id et media_ids)
    local_id = rudi_metadata["local_id"]
    existants = writer.filter_metadata_list({"local_id": local_id})
    existant = existants[0] if existants else None

    rudi_metadata["global_id"] = existant["global_id"] if existant else str(uuid.uuid4())
    rudi_metadata.setdefault("metadata_info", {})["api_version"] = _api_version(conf)

    # organization_id : réutilise celui du nœud si l'org existe, sinon UUID v4
    org = rudi_metadata["producer"]
    org_name = org.get("organization_name", "")
    org_existante = next(
        (o for o in writer.organization_list if o.get("organization_name") == org_name),
        None,
    )
    if org_existante:
        # Si l'org existante n'a pas de summary mais l'entrant en a, enrichir
        if not org_existante.get("organization_summary") and org.get("organization_summary"):
            try:
                org_mise_a_jour = {**org_existante,
                                   "organization_caption": org.get("organization_caption", ""),
                                   "organization_summary": org.get("organization_summary", "")}
                writer.connector.put_catalog("organizations", org_mise_a_jour)
                org_existante = org_mise_a_jour
                print(f"  [RUDI] organisation « {org_name} » enrichie (caption + summary)")
            except Exception as e:
                print(f"  [RUDI] AVERTISSEMENT : impossible d'enrichir l'org « {org_name} » : {e}")
        rudi_metadata["producer"] = org_existante
    elif "organization_id" not in org:
        org["organization_id"] = str(uuid.uuid4())
        demander_creation_organisation(conf, org)

    # theme : vérifie que la valeur est dans les thèmes acceptés par ce nœud
    themes_valides = writer.themes or []
    if themes_valides and rudi_metadata.get("theme") not in themes_valides:
        print(f"  [RUDI] AVERTISSEMENT : thème '{rudi_metadata.get('theme')}' non reconnu par le nœud. "
              f"Thèmes valides : {themes_valides}. Précisez 'theme' dans datasets.py.")
        raise ValueError(f"Thème RUDI invalide pour ce nœud : {rudi_metadata.get('theme')!r}")

    # contacts : le nœud exige au moins un contact avec email valide. Le nœud déduplique
    # les contacts par email — un email de repli partagé ferait collapser tous les
    # fallbacks sur un seul contact — donc l'email de repli est unique par nom de
    # contact/producteur (voir email_par_defaut).
    contacts_source = rudi_metadata.get("contacts", [])
    if contacts_source:
        # Contacts extraits de la source (data.gouv.fr, WFS/WMS) — on les "booste" contre le nœud
        rudi_contacts = []
        for c in contacts_source:
            nom_contact = c.get("contact_name", org_name or "Contact")
            contact = writer.connector.get_or_create_contact_with_info(
                contact_name=nom_contact,
                contact_email=c.get("email") or email_par_defaut(nom_contact),
            )
            rudi_contacts.append(contact.to_json())
        rudi_metadata["contacts"] = rudi_contacts
    else:
        # Fallback : contact générique au nom de l'organisation productrice
        contact = writer.connector.get_or_create_contact_with_info(
            contact_name=org_name or "Contact",
            contact_email=email_par_defaut(org_name or "Contact"),
        )
        rudi_metadata["contacts"] = [contact.to_json()]

    medias = rudi_metadata["available_formats"]

    # Médias FILE écartés (upload refusé) — ne doivent pas faire échouer le reste du
    # dataset ; typiquement une variante JSON trop verbeuse d'un CSV déjà publiable
    # (ex: sirene-v3-consolidee, JSON à 1,4 Go pour une limite nœud de 500 Mo).
    noms_ecartes: set[str] = set()

    for i, chemin in enumerate(fichiers_filtres):
        if not os.path.isfile(chemin):
            print(f"  [RUDI] fichier introuvable, ignoré : {chemin}")
            continue
        nom = os.path.basename(chemin)
        media_id = _media_id_v4(existant, medias[i].get("media_name", nom))
        medias[i]["media_id"] = media_id
        caption = medias[i].get("media_caption", "")
        print(f"  [RUDI] upload {nom} (media_id={media_id[:8]}…)")
        media_info: RudiMediaFile | None = None
        derniere_erreur: Exception | None = None
        # Le commit peut échouer par un aléa transitoire côté nœud ("could not commit
        # file: time exceeded", vu sur des datasets à beaucoup de fichiers séquentiels,
        # ex. annuaire-avocats avec ~15 CSV) — une seconde tentative suffit en général.
        for tentative in range(2):
            try:
                media_info = writer.post_local_file_and_media_info(
                    file_local_path=chemin,
                    media_id=media_id,
                )
                derniere_erreur = None
                break
            except Exception as e:
                derniere_erreur = e
                if "too big to be uploaded" in str(e):
                    break
                if "time exceeded" in str(e) and tentative == 0:
                    print(f"  [RUDI] commit de {nom} expiré côté nœud, nouvelle tentative…")
                    time.sleep(5)
                    continue
                if "time exceeded" not in str(e):
                    raise

        if derniere_erreur is not None:
            if "too big to be uploaded" in str(derniere_erreur):
                taille_mo = os.path.getsize(chemin) / 1_048_576
                print(f"  [RUDI] {nom} ({taille_mo:.0f} Mo) dépasse la limite de taille du "
                      f"nœud — média écarté, le reste du dataset est publié quand même.")
            else:
                print(f"  [RUDI] {nom} : échec de commit persistant ({derniere_erreur}) — "
                      f"média écarté, le reste du dataset est publié quand même.")
            noms_ecartes.add(nom)
            continue
        # Remplace le media dict par celui retourné (contient file_type, file_size, checksum…)
        medias[i] = json.loads(str(media_info))
        if caption:
            medias[i]["media_caption"] = caption
        print(f"  [RUDI] URL storage : {medias[i]['connector']['url']}")

    # Nettoyage Local→Rudi : retirer les médias FILE dont le fichier local a disparu
    # ou dont l'upload a été écarté ci-dessus (trop volumineux pour le nœud) — sauf un
    # FILE déjà complet (checksum + file_size déjà renseignés par l'appelant, ex. empreinte
    # calculée sur un fichier distant jamais stocké chez nous) : il n'a jamais eu vocation
    # à être uploadé ici, le retirer serait le perdre silencieusement.
    noms_locaux = {os.path.basename(p) for p in fichiers_filtres if os.path.isfile(p)}
    medias[:] = [m for m in medias
                 if m.get("media_type") != "FILE"
                 or _media_file_deja_complet(m)
                 or (m.get("media_name") in noms_locaux and m.get("media_name") not in noms_ecartes)]

    # Corrige les media_ids des entrées non uploadées (SERVICE vers data.gouv.fr,
    # source-metadata…) — la lib RUDI valide que tous les media_id sont des UUID v4.
    # Les FILE restants ont tous été uploadés ci-dessus (les manquants viennent
    # d'être retirés), leur media_id est déjà correct : on ne touche que le reste.
    for m in medias:
        if m.get("media_type") != "FILE":
            m["media_id"] = _media_id_v4(existant, m.get("media_name", ""))

    print(f"  [RUDI] push métadonnées (local_id={local_id[:8]}…)")
    _put_metadata(writer, rudi_metadata)
    print(f"  [RUDI] publié.")


def supprimer_organisation(conf: dict, org_id: str) -> bool:
    """
    Supprime une organisation du nœud RUDI par son organization_id.
    Retourne True si la suppression a réussi.
    """
    writer = _creer_writer(conf)
    try:
        writer.connector.delete_org_with_id(org_id)
        print(f"  [RUDI] organisation {org_id[:12]}… supprimée du nœud.")
        return True
    except Exception as e:
        print(f"  [RUDI] Erreur suppression organisation {org_id[:12]}… : {e}")
        return False


def supprimer_contact(conf: dict, contact_id: str) -> bool:
    """
    Supprime un contact du nœud RUDI par son contact_id.
    Retourne True si la suppression a réussi.
    """
    writer = _creer_writer(conf)
    try:
        writer.connector.del_catalog(f"contacts/{contact_id}")
        print(f"  [RUDI] contact {contact_id[:12]}… supprimé du nœud.")
        return True
    except Exception as e:
        print(f"  [RUDI] Erreur suppression contact {contact_id[:12]}… : {e}")
        return False


def supprimer_dataset(conf: dict, global_id: str) -> bool:
    """
    Supprime un dataset du nœud RUDI par son global_id.
    Retourne True si la suppression a réussi.
    """
    writer = _creer_writer(conf)
    try:
        writer.connector.del_catalog(f"resources/{global_id}")
        print(f"  [RUDI] dataset {global_id[:12]}… supprimé du nœud.")
        return True
    except Exception as e:
        print(f"  [RUDI] Erreur suppression {global_id[:12]}… : {e}")
        return False
