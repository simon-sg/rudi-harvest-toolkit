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
reste invisible du workflow de modération.

`demander_creation_organisation(conf, organization)` comble ce manque : si
`conf["url_portail"]` est renseigné (clé optionnelle de `rudi_node.json`, en plus de
`url`/`url_catalog`/`usr`/`pwd`), elle obtient un token OAuth2 auprès du **portail** avec
les identifiants du compte ROBOT (rôle `PROVIDER` requis côté Strukture — c'est le rôle
normal d'un compte nœud), puis appelle `POST {url_portail}/strukture/v1/organizations/request`
(crée une tâche BPMN de modération) et `POST .../linked-producers/request/{uuid}`
(rattachement à notre provider). Appelée automatiquement par `publier_dataset()` dès
qu'une nouvelle organisation est créée. **Best-effort** : sans `url_portail`, ou en cas
d'échec d'authentification/réseau, ne bloque jamais la publication du dataset — journalise
un avertissement et continue.

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
