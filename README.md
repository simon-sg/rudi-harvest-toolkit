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
| `rudi_harvest_toolkit.rudi_client` | `charger_conf_rudi(chemin)`, `noeud_pret()`, `url_catalog()`, `publier_dataset()`, `supprimer_dataset()`, `supprimer_organisation()`, `supprimer_contact()`, `toutes_metadonnees_rudi()`, `lister_organisations(conf, statut=None)`, `demander_creation_organisation()`, `email_par_defaut()`. |
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

### TODOs connus (pas encore implémentés — ne pas les tenir pour résolus)

- **Mise à jour** d'une organisation existante (enrichissement caption/summary) : passe
  encore par un `PUT /organizations` direct sur le nœud, sans validation portail. Devrait
  utiliser `PUT {portail}/strukture/v1/organizations/request` (même principe, verbe
  différent) — jamais fait à ce jour.
- **Suppression** d'un dataset : `supprimer_dataset()` ne touche que le nœud. Si Kalim a
  déjà moissonné la ressource, elle reste résiduelle côté portail. La bonne méthode existe
  déjà dans `moissonneur-ods` (`supprimer_ressources_portail()`, `DELETE
  {portail}/kalim/v1/resources/{global_id}`) mais n'a jamais été portée dans ce toolkit
  pour que `moissonneuse-batteuse` en bénéficie aussi.

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
