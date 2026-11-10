# rudi-harvest-toolkit

Boîte à outils Python **partagée** pour la construction de métadonnées RUDI, le rendu
Markdown, la gestion d'état d'incrémental, une session HTTP mutualisée et la publication
vers un nœud RUDI.

Extrait de `moissonneuse-batteuse`, ce package est une **bibliothèque** (pas un
exécutable), découplée de toute logique propre à Rennes Métropole.

## Modules

| Module | Rôle |
|---|---|
| `rudi_harvest_toolkit.pivot` | `construire_rudi_metadata()` — fonction pivot **pure** ; helpers média (`media_filtre`, `media_source`, `media_metadata_page`, `media_dict`, `media_pdf`), `parser_date_http()`, `LICENCE_ETALAB`, `construire_licence()`, `LICENCES_DATAGOUV_CONNUES` (table slug data.gouv.fr → licence RUDI, ex. `lov2`→etalab-2.0). |
| `rudi_harvest_toolkit.markdown` | `markdown_vers_html()` — conversion d'un sous-ensemble de Markdown en HTML (alimente `summary[].html`). Zéro dépendance. |
| `rudi_harvest_toolkit.state` | `charger_etat()`, `sauvegarder_etat()`, `dataset_a_change()`, `construire_index_dossier()` — état d'incrémental, entièrement paramétré par chemin. |
| `rudi_harvest_toolkit.http` | `session` — session `requests` mutualisée (pool de connexions + retry/backoff sur 429/5xx). |
| `rudi_harvest_toolkit.rudi_client` | `charger_conf_rudi(chemin)`, `noeud_pret()`, `url_catalog()`, `publier_dataset()`, `supprimer_dataset()`, `supprimer_dataset_portail()`, `supprimer_organisation()`, `supprimer_contact()`, `toutes_metadonnees_rudi()`, `lister_organisations(conf, statut=None)`, `organisation_par_nom(conf, organization_name)` (recherche par nom normalisé, garantit `organization_status`/`linked_producer_status` dans le résultat), `global_id_pour_local_id(conf, local_id)`, `demander_creation_organisation()`, `demander_mise_a_jour_organisation()`, `televerser_piece_jointe()`, `demander_detachement_producteur()`, `demander_suppression_organisation()`, `email_par_defaut()`, `organisations_nouvellement_validees()`/`marquer_organisations_traitees()`/`ressources_pour_organisations()` (détection d'orgs validées + état, voir « Renvoi après validation d'organisation »), `renvoyer_ressources_connues()` (renvoi sérialisé vers le portail via un PUT producteur normal — pas de route admin). |
| `rudi_harvest_toolkit.publish` | `publier_si_configue(conf, rudi_metadata, fichiers_filtres)` + verrou de publication et suivi des `local_id` publiés dans le run. |
| `rudi_harvest_toolkit.tabular` | `iter_lignes_csv(source)`, `filtrer_csv(source, colonne, valeur, prefixe=False)`, `lire_csv_filtre(...)` — lecteur CSV streaming (sniffing délimiteur/encodage, décompression gzip à la volée, résolution de colonne tolérante accents/casse) + filtre générique par valeur de colonne exacte ou par préfixe (`prefixe=True`, ex. SIRET filtré sur un SIREN). Généralise le moteur de parsing de `moissonneuse-batteuse/src/harvest_batch.py`, sans sa cascade Rennes Métropole à 8 niveaux. |
| `rudi_harvest_toolkit.datagouv` | `get_dataset_metadata(id)`, `lister_ressources(id)`, `selectionner_ressource(..., index=/motif_nom=/la_plus_recente=, format=)` — client data.gouv.fr générique avec sélection explicite de ressource (au lieu du « premier match par format » de `moissonneuse-batteuse/src/connectors/datagouv.py`). |
| `rudi_harvest_toolkit.download_cache` | `telecharger(url, dossier=, ttl_jours=, plafond_mo=)`, `purger_cache()`, `invalider()` — téléchargement streaming avec cache disque (clé MD5 de l'URL, TTL simple — **aucune** requête conditionnelle ETag/Last-Modified). Généralise `moissonneuse-batteuse/src/connectors/download.py`. |
| `rudi_harvest_toolkit.commune` | `resoudre_commune(code_insee)`, `resoudre_siren_commune(code_insee)` (filtre `nature_juridique=7210` obligatoire), `valider_code_insee()`, `bbox_depuis_contour(contour)` (bbox dataset simple depuis un GeoJSON Polygon/MultiPolygon, `None` si `contour` est `None`) — résolution géographique/SIREN d'une commune via `geo.api.gouv.fr`/`recherche-entreprises.api.gouv.fr`, avec garde-fous explicites (arrondissements municipaux, codes Corse non convertis en `int`). |
| `rudi_harvest_toolkit.fichier_hybride` | `empreinte_distante(url)`, `construire_media_hybride(local_id, url, ...)` — média RUDI `FILE` dont `connector.url` reste distant (empreinte SHA-256+taille calculée en flux, jamais stocké). Généralise `moissonneur-ods/src/moissonneur_ods/mode.py::_empreinte_distante`/`_media_file_distant`/`_media_id`. |
| `rudi_harvest_toolkit.wikipedia` | `resumer_commune_wikipedia(code_insee)` — résumé Wikipédia d'une commune, désambiguïsé par code INSEE via Wikidata (`P374`, jamais par nom), extrait MediaWiki complet (intro, pas le résumé court de `page/summary`), + `superficie_km2`/`gentile` (Wikidata `P2046`/`P1549`, omis si absents). Cache disque par code INSEE. |
| `rudi_harvest_toolkit.rne` | `maire_actuel(code_insee)` — maire en exercice d'une commune via le Répertoire National des Élus (Ministère de l'Intérieur), préféré à Wikidata (propriété `P6`, qui peut rester affichée indéfiniment après une élection non répercutée). |
| `rudi_harvest_toolkit.contacts` | `extraire_contacts_datagouv(metadata)`, `resoudre_contacts(...)`, `contacter_pardefaut(...)` — extraction/résolution de contacts depuis `contact_points` data.gouv.fr, avec repli générique. Migré depuis `moissonneuse-batteuse/src/connectors/contacts.py` (shim de réexportation conservé côté origine). |
| `rudi_harvest_toolkit.description` | `construire_description_structuree(quoi=, comment_construit=, structure_variables=, frequence_maj=, source_label=, url_source=)` — assembleur de mise en page Markdown pur (quoi/comment construit/liste de variables/fréquence/source), sans connaissance du domaine ; lève `ValueError` si `structure_variables` est vide. |

## Organisations productrices et validation portail

Quand `publier_dataset()` crée une **nouvelle** organisation productrice (producteur du
JDD moissonné, ex. "MyDataBall" — pas le producteur/nœud harvesteur lui-même), un simple
`PUT /organizations` sur le **nœud** ne déclenche **aucune** tâche de validation côté
portail (Strukture) : `organization_status` sur le nœud n'est renseigné que par le
*rapport* que le portail renvoie après qu'un modérateur a validé l'organisation dans son
UI — jamais par le nœud lui-même. Sans demande explicite au portail, l'organisation créée
reste invisible du workflow de modération, et `organization_status` reste vide
indéfiniment.

La méthode ci-dessous a été **validée de bout en bout** (publication → demande →
validation humaine via un compte animateur → `organization_status`/`linked_producer_status`
= `VALIDATED` sur le nœud) : c'est la méthode **par défaut** à réutiliser dans tous les
pipelines, pas un cas particulier.

### Règles (apprises par le test réel, à appliquer par défaut)

1. **La création passe par le NŒUD, pas directement par le portail (correction du
   2026-10-14, remplace une version précédente de cette section).** Voir
   `demander_creation_organisation()` ci-dessous — c'est le changement le plus important :
   l'ancienne implémentation appelait le portail directement et exigeait des identifiants
   ROBOT **portail** séparés, introuvables/non fonctionnels sur un nœud externe réel (démo
   RM, `401 invalid_client`). La bonne méthode n'a besoin que de l'auth **nœud** habituelle.
2. **`organization_id` : généré côté client (uuid4), requis par le nœud.** Contrairement à
   l'ancienne route portail directe (qui assignait son propre UUID en ignorant toute valeur
   proposée), le nœud **exige** `organization_id` dans le corps du `POST` (`400` sinon,
   constaté le 2026-10-15) et l'**honore tel quel** — c'est `demander_creation_organisation()`
   qui génère cet UUID, l'appelant n'a rien à faire de spécial.
3. **Ne pas appeler `linked-producers/request` explicitement.** Le portail génère
   automatiquement la tâche de rattachement du provider à la suite de la validation de la
   demande de création (vérifié en local ET en conditions réelles RM : une 2e tâche apparaît
   dans la file de modération sans action de notre part). Un appel explicite à ce stade
   échoue (`400 "Organization is not in a valid state"`, l'organisation n'étant pas encore
   validée).
4. **Identifiants nœud ≠ identifiants portail — et aucun appelant de ce toolkit n'a
   jamais eu les seconds.** Le login/mot de passe manager du **nœud** (compte local) et
   les identifiants ROBOT du **portail** (compte ACL/OAuth2, rôle applicatif) restent
   deux systèmes d'authentification distincts — `usr`/`pwd` pour le nœud,
   `usr_portail`/`pwd_portail` pour le portail (repli sur `usr`/`pwd` si absents, ce qui
   échoue systématiquement : un compte nœud n'est jamais aussi un compte ACL portail).
   Seule `demander_suppression_organisation()` (suppression de l'**organisation**
   elle-même côté Strukture — pas la création, pas le détachement, pas la suppression
   des **datasets**, voir plus bas) fait encore un appel portail direct de ce type, et
   échoue donc en `401` pour tous les appelants réels connus de ce toolkit, confirmé 3
   façons différentes (OAuth2 `client_credentials`, `grant_type=password`, login
   classique) sur plusieurs nœuds. Ce n'est **pas un bug de route à corriger** : seul un
   compte animateur personnel (accès humain à l'UI Strukture) peut faire cette
   suppression précise — voir `rudi-commune-starterkit`, qui ne l'appelle plus du tout
   et demande confirmation manuelle à la place.

### `demander_creation_organisation(conf, organization)`

**Crée l'organisation sur le NŒUD** (`POST {url_catalog}/organizations`, authentification
nœud habituelle — celle déjà utilisée pour publier des ressources, **aucun identifiant
portail séparé requis**). Le nœud **lui-même** relaie la demande au portail
(`genericController.js::newRudiObject` → `createPortalOrganization()`, côté `rudi-catalog`)
en utilisant l'identité propre du nœud, configurée une fois pour toutes au raccordement —
exactement ce que fait l'UI du nœud quand un humain crée une organisation à la main.

**Pourquoi ce n'est plus un appel portail direct** : une version précédente de cette
fonction appelait `POST {url_portail}/strukture/v1/organizations/request` et exigeait donc
des identifiants ROBOT portail séparés. Sur un nœud externe réel (démo RM), ces
identifiants n'existaient pas (`401 invalid_client`), alors que **le compte nœud existant
fonctionne parfaitement** pour obtenir le même résultat via cette route — confirmé par
lecture du code source du nœud et par un test de bout en bout contre un portail de
préprod réel (création → `organization_status=DRAFT` → validation modérateur →
`VALIDATED`, cascade de rattachement automatique incluse).

⚠️ **Le verbe HTTP exact est `POST`, pas `PUT`.** `rudi_node_write.get_or_create_org_with_info()`
(PUT) existe mais échoue en conditions réelles sur certains nœuds (`503`, relais interne
manager→catalog en défaut) — ne pas s'y fier à la place de l'appel `POST` direct utilisé ici.

**Best-effort** : en cas d'échec (nœud injoignable, etc.), ne bloque jamais la publication
du dataset — journalise un avertissement et continue (`organization_id` généré localement
en repli, comportement historique).

**Test en local** : si le nœud et le portail sont tous deux en conteneurs Docker, le
service `strukture` (qui reçoit l'appel du nœud et envoie plus tard le rapport de
validation) doit pouvoir résoudre l'URL du nœud source natif (`host:4030`) depuis
l'intérieur de son conteneur. Sans `extra_hosts: ["host.docker.internal:host-gateway"]`
dans `docker-compose-source.yml`, l'appel échoue **silencieusement** côté portail (simple
log Java, jamais une erreur visible) — voir la section dédiée dans `REF_ENV_RUDI_LOCAL.md`.
Sans objet pour un nœud/portail externes réels (pas de conteneurs à notre charge).

### `demander_mise_a_jour_organisation(conf, organization, image_id=None)` — ⚠️ CASSÉE, ne plus appeler

**Signalée cassée par l'équipe RUDI elle-même (2026-10-15).** N'est plus appelée nulle part
dans le flux normal (ni `publier_dataset()`, ni `enrichir_organisations.py`) — conservée
uniquement au cas où un correctif côté RUDI la rendrait de nouveau utilisable. Une
organisation doit désormais être complète **dès sa création**
(`demander_creation_organisation()`) plutôt que de compter sur un enrichissement a
posteriori. Le reste de cette section documente son fonctionnement **tel qu'il était
censé marcher**, à titre d'archive :

Met à jour une organisation **déjà connue du portail** (enrichissement
`organization_summary`/caption/`organization_url`/logo d'un producteur préexistant) en
passant par le **workflow BPMN officiel** `DRAFT_UPDATE` — le chemin direct
(`PUT /organizations/request`) est bogué côté Strukture (remet à `null` des champs d'audit)
et inutilisable.

Enchaînement : `POST /organizations/tasks` (brouillon, `name`/`description` **requis** au
niveau supérieur), réinjection du `form` dans `asset.form`, puis `PUT /organizations/tasks/start`.
Le robot (rôle `PROVIDER`) ne peut pas auto-valider la tâche : **un modérateur doit valider la
demande dans l'UI Strukture** pour que la modification soit appliquée
(`publishOrganizationModification`). `description` est tronquée à **1024** caractères (validateur
`MAXLENGTH`) ; `url` doit satisfaire le REGEXP `^(https?|ftp)://[a-zA-Z0-9.-]+(/\S*)?$` sinon elle
est retirée. **Idempotent** : si le portail porte déjà la description voulue (et la même url) et
qu'aucune image n'est fournie, aucune demande n'est déposée. L'`organization_id` doit être celui
**assigné par le portail** (adopté à la création). **Best-effort**, retourne
``True``/``False``/``None`` (``None`` = pas de `url_portail`, aucune requête).

`image_id` (optionnel) : UUID d'une pièce jointe obtenu via `televerser_piece_jointe()`,
transmis comme champ `organizationImage` du formulaire (logo du producteur, appliqué à la
validation). Fournir une image **force** le dépôt même si description/url sont déjà à jour
(le portail n'expose pas « a déjà un logo personnalisé » : la route média renvoie toujours
*un* logo, par défaut le cas échéant) — à l'appelant de ne pas re-soumettre indéfiniment.

### `televerser_piece_jointe(conf, contenu, nom_fichier, type_mime=None)`

Téléverse une pièce jointe (image d'organisation) sur le portail :
`POST {url_portail}/strukture/v1/attachments` (multipart, champ `file`, même compte ROBOT
que les autres demandes). Retourne l'UUID d'attachement (``str``), à passer comme `image_id`
de `demander_mise_a_jour_organisation()`. Le portail n'accepte que **jpeg/png, ≤ 10 Mo**
(vérifié localement avant l'envoi). **Best-effort** : retourne ``None`` sans lever (pas de
`url_portail`, type/taille invalide, auth échouée, refus, réseau).

### `supprimer_organisation(conf, org_id)` vs `demander_suppression_organisation(conf, organization_id)`

`supprimer_organisation()` ne supprime que la copie **locale** de l'organisation sur le
**nœud**. `demander_suppression_organisation()` la supprime aussi **côté portail**
(`DELETE {url_portail}/strukture/v1/organizations/request/{uuid}`, rôle `PROVIDER`
applicatif). Sans cet appel, l'organisation reste présente dans l'UI Strukture / le
référentiel du portail après sa suppression côté nœud.

**En pratique, inutilisable sans un compte ACL portail dédié que ce toolkit n'a jamais
eu** (confirmé en conditions réelles le 2026-10-15 et de nouveau le 2026-11-08, `401`
systématique quelle que soit la méthode d'auth essayée — voir règle 4 plus haut) —
contrairement à `supprimer_dataset_portail()` (datasets, voir la section suivante), il
n'existe **aucun relais nœud** équivalent pour cette opération précise : le nœud ne
relaie que les actes `attach`/`detach`/`has_task` pour les organisations, jamais la
suppression (vérifié dans `rudi-catalog/src/routes/routes.js`, aucune route `delete`
pour `portal/organizations/:id`). `rudi-commune-starterkit` ne l'appelle donc plus du
tout : une fois le producteur détaché, il demande à l'utilisateur de confirmer qu'il a
lui-même supprimé l'organisation dans l'UI Strukture (son propre accès animateur) avant
de nettoyer la copie locale du nœud. Fonction conservée ici pour compatibilité (d'autres
appelants, ex. `moissonneuse-batteuse`) et pour le jour où de vrais identifiants ACL
seraient disponibles.

Contrairement à la création (tâche BPMN + validation modérateur), la suppression de
l'organisation elle-même est appliquée **directement** (aucune validation côté Strukture).
L'`organization_id` doit être celui **assigné par le portail** (adopté à la création) : un
id purement local répond `404`. Un `401` (token expiré) est rejoué une fois avec un token
renouvelé. **Best-effort**, retourne ``True``/``False``/``None`` (``None`` = pas de
`url_portail`, aucune requête).

**Prérequis avant suppression : détacher le producteur.** Toute organisation créée par le
circuit officiel a automatiquement un `linked_producer` (table liée par une contrainte de
clé étrangère) ; `demander_suppression_organisation()` échoue avec un `409` tant qu'il
n'a pas été détaché. Appeler d'abord `demander_detachement_producteur(conf,
organization_id)` — **celui-ci a sa propre tâche BPMN avec validation modérateur**
(contrairement à la suppression de l'organisation) — et ne réessayer la suppression qu'une
fois cette tâche validée dans l'UI Strukture. Vérifié de bout en bout le 2026-10-13 : ce
n'est pas un bug RUDI, juste une étape du process absente de la documentation jusque-là.

**Corrigé le 2026-10-15** : contrairement à la suppression ci-dessus (qui reste un appel
portail direct, aucune route nœud équivalente trouvée), le détachement passe désormais
par le **nœud** (`GET {url_catalog}/portal/organizations/{uuid}/detach` — **sans** segment
`admin/`, sinon le manager redirige silencieusement vers l'UI et `requests` suit cette
redirection, donnant un faux succès) — trouvé en capturant le trafic réseau du bouton
« détacher » de l'UI du nœud. Plus besoin de `url_portail`/identifiants portail séparés
pour cette opération.

### `supprimer_dataset(conf, global_id)` vs `supprimer_dataset_portail(conf, global_id)`

`supprimer_dataset()` ne supprime que sur le **nœud** — mais, **confirmé en conditions
réelles le 2026-11-08** (pas seulement par lecture de code, contrairement à une version
antérieure de cette section) : si Kalim a déjà moissonné la ressource, cette suppression
nœud **déclenche déjà** sa suppression côté portail, automatiquement, avec l'identité
propre du nœud (`genericController.js::deleteSingleObject` → `deletePortalMetadata()`,
appelé dès que `objectType === 'resources'` et que la ressource n'a pas de
`collection_tag` — notre cas général). Même principe que le relais de
`demander_creation_organisation()`/`demander_detachement_producteur()`.

`supprimer_dataset_portail()` (`DELETE {url_portail}/kalim/v1/resources/{global_id}`,
authentification OAuth2 directe au portail) est donc **redondante pour l'usage courant**
et, comme `demander_suppression_organisation()` ci-dessus, **échoue en `401`** pour tout
appelant sans compte ACL portail dédié (la plupart). `rudi-commune-starterkit` ne
l'appelle plus du tout depuis cette découverte. Conservée ici pour compatibilité
(d'autres appelants l'utilisent encore, ex. `moissonneuse-batteuse`) et pour le cas,
rare, où un vrai compte ACL existe. **Best-effort**, retourne
``True``/``False``/``None`` (``None`` = pas de `url_portail`, aucune requête).

### Suppression d'un média (fichier storage) — impossible via l'API standard

Trouvé en conditions réelles le 2026-10-16 (démo nœud RM) : retirer un média
d'`available_formats`, ou supprimer le dataset entier via `supprimer_dataset()`, **ne
libère jamais l'espace storage**. Vérifié dans le code source `rudi-catalog` :
`genericController.js::deleteSingleObject` ne supprime que l'entrée Mongo + notifie le
portail, aucun appel vers le service storage.

`rudi-storage` a bien une vraie route de suppression (`POST /delete/:uuid`, exécute un
`rmSync()` réel sur le fichier) — mais elle exige une permission `-wx` que seul un rôle
`admin`/`delegate` côté **storage** possède. Un compte producteur (celui que ce toolkit
utilise toujours) n'a que `-w-` → `401 "Access not granted: execution access not set for
the user"`. **Un rôle admin côté manager ne suffit pas non plus** (testé) : les comptes
autorisés côté storage (`admin`, `rudimanager`, `rudiprod`, `rudiadmin`) sont des comptes
système codés en dur dans la config propre de `rudi-storage`, déconnectés du système de
rôles du manager — le JWT storage dérivé via `manager/api/storage/jwt` attribue toujours un
rôle `producer`, quel que soit le rôle manager réel de l'utilisateur. **Capacité
définitivement hors de portée de ce toolkit, sur n'importe quel nœud** — pas une fonction à
ajouter, l'API ne le permet pas pour un compte producteur.

**Seule protection fiable pour qui teste des tailles/volumes de médias : le nom de fichier
fixe.** Le `media_id` est dérivé de façon déterministe du `media_name` (`_media_id_v4()`) —
réuploader sous le **même nom** écrase le fichier au même chemin disque (storage écrit avec
`flag: 'w'`), sans jamais dupliquer. Changer de nom entre deux essais sur le même usage crée
en revanche un **orphelin permanent et invisible** (plus de référence catalogue, fichier
toujours présent, espace toujours consommé).

**Rattrapage possible si un orphelin existe déjà** : le neutraliser en ré-uploadant un
fichier vide/minuscule sous le **même `media_id` connu**, directement via
`writer.post_local_file_and_media_info(file_local_path=..., media_id=media_id_connu)` —
storage ne vérifie jamais qu'un `media_id` est encore référencé par une fiche catalogue.

### Renvoi après validation d'organisation

Une organisation créée via le circuit officiel passe par une tâche BPMN de validation
modérateur (UI Strukture) ; tant qu'elle n'est pas validée, toute ressource qui la
référence comme producteur est refusée par Kalim (`ERR-112`). Trois fonctions,
génériques (aucune dépendance à un projet en particulier), détectent les organisations
nouvellement validées et isolent les ressources locales concernées :

- `organisations_nouvellement_validees(conf, chemin_etat)` — compare les organisations à
  `organization_status: VALIDATED` côté nœud à un état persisté sur disque (JSON,
  `{"organisations_traitees": [...]}`), pour ne retraiter que celles **nouvellement**
  validées depuis le dernier appel.
- `marquer_organisations_traitees(chemin_etat, organisation_ids)` — à appeler **après**
  la tentative de renvoi (jamais avant), pour ne pas perdre la trace d'une organisation
  validée si le renvoi échoue en cours de route.
- `ressources_pour_organisations(metadonnees, organisation_ids)` — filtre une liste de
  métadonnées (ex. `toutes_metadonnees_rudi()`) sur `producer.organization_id`.

Portée depuis `moissonneur-ods` (2026-10-11) pour être partagée le 2026-10-13, à la
demande de son usage par `moissonneuse-batteuse`. Le renvoi lui-même est désormais unifié
aussi, via `renvoyer_ressources_connues(conf, metadonnees)` — **jamais** la route admin du
nœud (`/catalog/admin/portal/resources/send`, qui exige un profil — `rudi_api_pm`/Postman —
qu'aucun producteur/harvester ne doit détenir), ni un push direct vers Kalim avec le compte
ROBOT du portail (ce que faisait `moissonneur-ods` jusqu'au 2026-10-13) : un producteur
normal dépose sur son nœud, c'est tout. Un simple `PUT /catalog/v1/resources` (route
producteur normale, celle que `publier_dataset()` utilise déjà) suffit : le nœud
(`overwriteMetadata` → `sendToPortal`) relaie lui-même vers le portail dès que ses médias
sont disponibles — indépendant du statut de validation de l'organisation. Un `global_id` (un
dict de métadonnées, en l'occurrence) à la fois, pause de 2s entre chaque, **jamais en lot** :
`sendToPortal()` côté nœud est fire-and-forget (pas attendu par le PUT qui le déclenche) —
des PUT consécutifs sans pause déclenchent donc des envois concurrents qui peuvent
surcharger le service de consultation du portail, quel que soit le point d'entrée qui les a
lancés (route admin ou route producteur).

## Découplage

`construire_rudi_metadata()` est une fonction pivot **pure** : elle ne résout jamais
elle-même la géographie, le producteur ou les contacts. L'appelant fournit :

- `geography: dict | None = None` — emprise explicite (clé omise de la sortie si `None`) ;
- `producer: dict` — producteur **entièrement pré-formé** (`organization_name` +
  enrichissements éventuels) ;
- `contacts_source: list[dict]` — **obligatoire** (au moins un contact valide attendu
  par le nœud RUDI).

Les responsabilités de résolution de repli (enrichissement d'organisation, contacts par
défaut) restent à la charge de l'appelant, exécutées **avant** l'appel.

## Installation en mode éditable

Layout `src/`, backend `setuptools` (`pyproject.toml`). Environnement Debian
« externally-managed », d'où `--break-system-packages` :

```bash
pip install --user --break-system-packages -e /media/simon/DATA4T/Dev/rudi-harvest-toolkit
```

Pour l'installation par tag (run stable) :

```bash
pip install --user --break-system-packages "git+ssh://git@github.com/<org>/rudi-harvest-toolkit.git@v0.1.0"
```

Dépendances runtime : `requests`, `rudi-node-write` (publication RUDI).

## Tests

```bash
python3 -m unittest discover tests/
# ou
python3 -m pytest tests/
```

Les tests sont de la logique pure, sans réseau (les tests de sérialisation
`summary[].html` nécessitent `rudi-node-write` installé).
