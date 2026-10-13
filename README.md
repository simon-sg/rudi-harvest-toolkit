# rudi-harvest-toolkit

Boîte à outils Python **partagée** pour la construction de métadonnées RUDI, le rendu
Markdown, la gestion d'état d'incrémental, une session HTTP mutualisée et la publication
vers un nœud RUDI.

Extrait de `moissonneuse-batteuse`, ce package est une **bibliothèque** (pas un
exécutable), découplée de toute logique propre à Rennes Métropole.

## Modules

| Module | Rôle |
|---|---|
| `rudi_harvest_toolkit.pivot` | `construire_rudi_metadata()` — fonction pivot **pure** ; helpers média (`media_filtre`, `media_source`, `media_metadata_page`, `media_dict`, `media_pdf`), `parser_date_http()`, `LICENCE_ETALAB`, `construire_licence()`. |
| `rudi_harvest_toolkit.markdown` | `markdown_vers_html()` — conversion d'un sous-ensemble de Markdown en HTML (alimente `summary[].html`). Zéro dépendance. |
| `rudi_harvest_toolkit.state` | `charger_etat()`, `sauvegarder_etat()`, `dataset_a_change()`, `construire_index_dossier()` — état d'incrémental, entièrement paramétré par chemin. |
| `rudi_harvest_toolkit.http` | `session` — session `requests` mutualisée (pool de connexions + retry/backoff sur 429/5xx). |
| `rudi_harvest_toolkit.rudi_client` | `charger_conf_rudi(chemin)`, `noeud_pret()`, `url_catalog()`, `publier_dataset()`, `supprimer_dataset()`, `supprimer_dataset_portail()`, `supprimer_organisation()`, `supprimer_contact()`, `toutes_metadonnees_rudi()`, `lister_organisations(conf, statut=None)`, `demander_creation_organisation()`, `demander_mise_a_jour_organisation()`, `televerser_piece_jointe()`, `demander_detachement_producteur()`, `demander_suppression_organisation()`, `email_par_defaut()`, `organisations_nouvellement_validees()`/`marquer_organisations_traitees()`/`ressources_pour_organisations()` (détection d'orgs validées + état, voir « Renvoi après validation d'organisation »), `renvoyer_ressources_connues()` (renvoi sérialisé vers le portail via un PUT producteur normal — pas de route admin). |
| `rudi_harvest_toolkit.publish` | `publier_si_configue(conf, rudi_metadata, fichiers_filtres)` + verrou de publication et suivi des `local_id` publiés dans le run. |

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

1. **Ordre des UUID : demander AVANT de décider `organization_id`.** Le portail assigne son
   propre UUID et ignore celui qu'on lui propose dans le corps de la requête. Il faut donc
   appeler `demander_creation_organisation()` **avant** de fixer `organization_id`, et
   adopter l'UUID **retourné** — jamais l'inverse, sinon le rapport de validation que le
   portail renverra plus tard au nœud ne pourra pas se raccrocher à la bonne organisation.
   (C'est exactement ce que fait `publier_dataset()`.)
2. **Ne pas appeler `linked-producers/request` explicitement.** Le portail génère
   automatiquement la tâche de rattachement du provider à la suite de la demande de
   création (vérifié : une 2e tâche apparaît dans la file de modération sans action de
   notre part). Un appel explicite à ce stade échoue (`400 "Organization is not in a valid
   state"`, l'organisation n'étant pas encore validée).
3. **Identifiants nœud ≠ identifiants portail.** Le login/mot de passe manager du **nœud**
   (compte local, ex. base SQLite du nœud — `admin`/`admin` en local) et les identifiants
   ROBOT du **portail** (compte ACL/OAuth2, ex. UUID + mot de passe généré) sont deux
   systèmes d'authentification **totalement distincts**. Ils se configuent séparément :
   `usr`/`pwd` pour le nœud, `usr_portail`/`pwd_portail` pour le portail (s'ils manquent,
   repli sur `usr`/`pwd`). Un `401 invalid_client` signale typiquement qu'on a fourni des
   identifiants nœud, jamais enregistrés côté ACL portail comme client OAuth2.

### `demander_creation_organisation(conf, organization)`

Si `conf["url_portail"]` est renseigné (clé optionnelle de `rudi_node.json`, en plus de
`url`/`url_catalog`/`usr`/`pwd`), obtient un token OAuth2 auprès du **portail** avec les
identifiants ROBOT (rôle `PROVIDER` requis côté Strukture — c'est le rôle normal d'un compte
nœud), puis appelle `POST {url_portail}/strukture/v1/organizations/request`, qui crée une
vraie tâche BPMN de modération. **Best-effort** : sans `url_portail`, ou en cas d'échec
d'authentification/réseau, ne bloque jamais la publication du dataset — journalise un
avertissement et continue.

**Test en local** : les services portail `strukture` (envoi du rapport de validation),
`kalim` (moissonnage) et `selfdata` (appariement) doivent pouvoir résoudre l'URL du nœud
source natif (`host:4030`) depuis l'intérieur de leurs conteneurs. Sans
`extra_hosts: ["host.docker.internal:host-gateway"]` dans `docker-compose-source.yml`,
l'appel échoue **silencieusement** (simple log côté Java, jamais une erreur visible) — voir
la section dédiée dans `REF_ENV_RUDI_LOCAL.md`.

### `demander_mise_a_jour_organisation(conf, organization, image_id=None)`

Met à jour une organisation **déjà connue du portail** (enrichissement
`organization_summary`/caption/`organization_url`/logo d'un producteur préexistant) en
passant par le **workflow BPMN officiel** `DRAFT_UPDATE` — le chemin direct
(`PUT /organizations/request`) est bogué côté Strukture (remet à `null` des champs d'audit)
et inutilisable. Appelé automatiquement par `enrichir_organisations.py`, en complément du
`PUT /organizations` sur le nœud — sans cet appel, l'UI Strukture conserve l'ancienne
description (le `PUT` nœud ne touche que la copie locale).

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
(`DELETE {url_portail}/strukture/v1/organizations/request/{uuid}`, même compte ROBOT que la
création, rôle `PROVIDER`). Sans cet appel, l'organisation reste présente dans l'UI
Strukture / le référentiel du portail après sa suppression côté nœud — c'est le pendant
« portail » de la suppression d'organisation, comme `supprimer_dataset_portail()` l'est
aux datasets.

Contrairement à la création (tâche BPMN + validation modérateur), la suppression de
l'organisation elle-même est appliquée **directement** (aucune validation côté Strukture).
L'`organization_id` doit être celui **assigné par le portail** (adopté à la création) : un
id purement local répond `404`. Un `401` (token expiré) est rejoué une fois avec un token
renouvelé. **Best-effort**, retourne ``True``/``False``/``None`` (``None`` = pas de
`url_portail`, aucune requête).

**Prérequis avant suppression : détacher le producteur.** Toute organisation créée par le
circuit officiel a automatiquement un `linked_producer` (table liée par une contrainte de
clé étrangère) ; `demander_suppression_organisation()` échoue avec un `409` tant qu'il
n'a pas été détaché. Appeler d'abord
`demander_detachement_producteur(conf, organization_id)` (`DELETE
{url_portail}/strukture/v1/linked-producers/request/{uuid}`) — **celui-ci a sa propre
tâche BPMN avec validation modérateur** (contrairement à la suppression de l'organisation) —
et ne réessayer la suppression qu'une fois cette tâche validée dans l'UI Strukture.
Vérifié de bout en bout le 2026-10-13 : ce n'est pas un bug RUDI, juste une étape du
process absente de la documentation jusque-là.

### `supprimer_dataset(conf, global_id)` vs `supprimer_dataset_portail(conf, global_id)`

`supprimer_dataset()` ne supprime que sur le **nœud**. Si Kalim a déjà moissonné la
ressource, celle-ci reste résiduelle dans le catalogue du portail : la supprimer aussi
côté portail nécessite `supprimer_dataset_portail()`
(`DELETE {url_portail}/kalim/v1/resources/{global_id}`, authentification ROBOT, **DELETE
asynchrone** traité par le planificateur Kalim — laisser quelques minutes avant de
conclure à un blocage). Portée depuis `moissonneur-ods` pour être partagée, notamment par
`moissonneuse-batteuse`. **Best-effort**, retourne ``True``/``False``/``None`` (``None`` =
pas de `url_portail`, aucune requête).

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
