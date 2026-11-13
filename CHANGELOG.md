# Changelog

## Non publié

### `rudi_client.demander_creation_organisation()` — `organization_id` déterministe

Corrige un doublon d'organisation observé en conditions réelles (nœud de démo RM,
2026-11-13) : l'`organization_id` envoyé au nœud était tiré aléatoirement
(`uuid.uuid4()`) à chaque appel — un échec ambigu suivi d'un nouvel essai pouvait
créer une 2e organisation distincte pour la même commune si le nœud n'avait pas fini
d'indexer la première. Désormais dérivé de `uuid.uuid5(namespace fixe, nom
normalisé)` — une 2e tentative vise la même ressource (contrainte d'unicité côté
nœud, confirmée dans son schéma Mongoose) au lieu d'en créer une 2e. Nouvelle
`rudi_client.organisation_par_id()` : récupération explicite par cet id si la
création échoue, pour ne pas perdre le lien dès ce run.

### `download_cache.telecharger()` — retry sur coupure réseau en cours de flux

Une coupure **en cours de flux** (`ConnectionError`/`ChunkedEncodingError`,
« Connection broken », observée sur le téléchargement national DVF de 609 Mo de
`rudi-commune-starterkit`) ne déclenchait aucune reprise — seules les erreurs avant
réception de la réponse HTTP (429/5xx) étaient retentées ailleurs. Jusqu'à 3
tentatives désormais, chacune reprenant le téléchargement depuis le début (pas de
`Range`/reprise partielle) — bénéficie à tous les appelants du toolkit.

## 0.5.0 — 2026-11-11 (Axe 5 de rudi-commune-starterkit, incréments A/B/C)

### `tabular.lire_parquet_filtre()` + dépendance `pyarrow` obligatoire

Variante Parquet de `lire_csv_filtre()` — même contrat de retour `(lignes, entetes)`,
projection de colonnes, comparaison déléguée à `_correspond()` (jamais un filtre
`pyarrow` natif typé), valeurs en types Python natifs (`to_pydict()`, jamais de
scalaires `numpy`). `pyarrow>=14` ajouté aux dépendances obligatoires du package
(premier et seul consommateur actuel : le jeu agrégé « donnees-des-elections-agregees »,
232 Mo par commune en Parquet contre 2,38 Go en CSV).

### `description.construire_description_structuree(glossaire=, limites=)`

Deux nouveaux paramètres optionnels (`None` = sortie inchangée, non-régression
testée) : `glossaire` (`{code: libellé}`, rendu « Codes et variables : ») et `limites`
(liste de phrases, rendu « Limites de couverture : »). Rend visible, directement dans
la fiche catalogue plutôt que dans un BACKLOG.md jamais consulté par un lecteur du
nœud, les nomenclatures opaques et les dégradations attendues — infrastructure
partagée entre l'Axe 4 (budget/DVF/DECP/eau_potable) et l'Axe 5 (élections) du plan v4.

## 0.4.0 — 2026-11-10

### Dates réelles (`http_dates.py`) et GeoJSON par ligne (`geojson.py`)

Nouveaux modules pour la v4 de `rudi-commune-starterkit` (Axes 2 et 3) :

- **`http_dates.py`** : `entete_derniere_modification()` (sonde HEAD/repli GET, pour
  une URL arbitraire), `date_dataset_ods()` (`metas.default.modified` d'un dataset
  Opendatasoft), `parser_date_iso_stricte()` (parseur ISO 8601 public, réutilisable).
  **Ne délègue jamais à `pivot.parser_date_http()`** : cette dernière retourne
  `datetime.now(UTC)` sur une date non parsable (repli pensé pour ne jamais bloquer
  l'assemblage d'un dataset) — ce module garantit `None` à la place, jamais une date
  inventée.
- **`download_cache.date_fichier_cache(chemin)`** : mtime d'un fichier en cache, ISO
  8601 UTC — pour les connecteurs qui dérivent leur date de publication de la date de
  récupération locale plutôt que d'une sonde réseau supplémentaire.
- **`geojson.py`** : `construire_feature_collection()` (FeatureCollection GeoJSON pure,
  un Point par ligne ayant des coordonnées exploitables, lignes invalides omises en
  silence), `AucuneGeometrieValide` (dégradation attendue, à distinguer d'une erreur de
  programmation). Jamais d'inversion `[lat, lon]` — testé explicitement (le seul
  garde-fou qui détecte ce piège, un contrôle de bornes ne le détecte pas).
- **`rudi_client.valider_alignement_medias()`** : garde-fou inséré avant la boucle
  d'upload de `publier_dataset()` — vérifie l'**ordre**, pas seulement le compte, des
  médias `FILE` réellement à uploader par rapport aux médias `FILE` hybrides déjà
  complets (un trou purement comptage aurait laissé passer une corruption silencieuse
  sur un module combinant les deux types, trouvé en relecture indépendante du plan v4).

## 0.3.0 — 2026-11-10

### `rne.py` (maire actuel) + enrichissement `wikipedia.py`

Correction post-livraison de la v3 de `rudi-commune-starterkit`, suite à un test réel
(commune d'Acigné) :

- **Nouveau** `rne.py` : `maire_actuel(code_insee)` — maire en exercice d'une commune
  via le Répertoire National des Élus (Ministère de l'Intérieur), préféré à Wikidata
  (propriété P6) pour une donnée qui change à chaque élection municipale sans que
  Wikidata ne le reflète de façon fiable (constaté : mandat 2014 affiché sans date de
  fin, alors que le RNE avait déjà le mandat renouvelé en mars 2026).
- `wikipedia.py` : `resumer_commune_wikipedia()` retourne désormais aussi
  `superficie_km2`/`gentile` (Wikidata P2046/P1549, requête SPARQL complémentaire sur
  le QID déjà résolu, best-effort — un échec ici n'invalide pas le résumé). Garde-fou
  anti-ébauches (`longueur_min`) abaissé de 250 à 80 caractères : un intro réel et
  court (ex. 192 caractères pour Acigné, 2 phrases factuelles) n'est pas une ébauche.

### nouveaux modules partagés pour la v3 de rudi-commune-starterkit

Code générique extrait lors de la v3 de `rudi-commune-starterkit` (voir son propre
BACKLOG/CHANGELOG pour le contexte produit) :

- `wikipedia.py` (nouveau) : résumé Wikipédia d'une commune désambiguïsé par code
  INSEE via Wikidata (`P374`), extrait MediaWiki complet (pas le résumé court de l'API
  `page/summary`), cache par code INSEE.
- `contacts.py` (nouveau) : migré depuis `moissonneuse-batteuse/src/connectors/
  contacts.py` (`extraire_contacts_datagouv()`, `resoudre_contacts()`,
  `contacter_pardefaut()`) — `email_par_defaut()` importée depuis `rudi_client`
  plutôt que redéfinie. `moissonneuse-batteuse` garde un shim de réexportation,
  zéro changement pour ses 6 appelants existants.
- `description.py` (nouveau) : `construire_description_structuree()`, assembleur de
  mise en page Markdown pur (quoi/comment construit/variables/fréquence/source),
  sans connaissance du domaine.
- `commune.py` : nouvelle `bbox_depuis_contour()` (bbox dataset simple depuis un
  GeoJSON Polygon/MultiPolygon).
- `pivot.py` : nouvelle constante `LICENCES_DATAGOUV_CONNUES` (table slug data.gouv.fr
  → licence RUDI, `lov2`/`odc-odbl`), réutilisable par tout harvester consommant
  `get_dataset_metadata()`.
- `tabular.py` : nouveau paramètre `prefixe: bool = False` sur `filtrer_csv()`/
  `lire_csv_filtre()` (égalité ou préfixe sur la colonne filtrée, ex. SIRET préfixé
  par un SIREN) — lève `ValueError` si `prefixe=True` avec une valeur vide.

### `supprimer_dataset_portail()` documentée comme redondante

Suite du bug ci-dessous : une fois l'URL corrigée, le `401` est resté — pas un
problème d'URL mais un vrai défaut d'autorisation, `supprimer_dataset_portail()`
nécessitant un compte ROBOT enregistré côté ACL OAuth2 du portail, que
`rudi-commune-starterkit` n'a jamais eu besoin d'avoir. Confirmé par le code source
du nœud (`rudi-catalog/genericController.js::deleteSingleObject`) que
`supprimer_dataset()` (suppression nœud seule) déclenche déjà ce relais
automatiquement, avec l'identité propre du nœud — même principe que le relais de
`demander_creation_organisation()`/`demander_detachement_producteur()`.
`supprimer_dataset_portail()` conservée (d'autres appelants l'utilisent encore,
ex. `moissonneuse-batteuse`) mais sa docstring documente maintenant cette
redondance ; `rudi-commune-starterkit` ne l'appelle plus (voir son propre
changelog/historique).

### fix `_token_portail()` (bug réel en conditions de production)

`_token_portail()` ne normalisait pas `url_portail` avant de construire l'URL
`oauth2/token`, contrairement à tous les autres appels portail du fichier
(`.rstrip('/')`) — un `url_portail` enregistré avec un slash final (cas réel :
profil `rudi-commune-starterkit` saisi via l'assistant interactif) donnait
`http://portail//oauth2/token`, rejeté par le portail (`401 Unauthorized`). Repéré via
un `--vider-commune` réel (2026-11-08) où les 13 suppressions nœud ont réussi mais
chaque suppression portail a échoué sur ce 401 — aucune donnée perdue (le contrat
best-effort existant a correctement marqué ces JDD en échec plutôt que de les retirer
de l'état local), mais bloquait tout usage réel de
`--vider-commune`/`--supprimer-organisation` avec un `url_portail` saisi avec un slash
final. Voir l'entrée suivante : la cause plus profonde (401 persistant même l'URL
corrigée) a mené à retirer l'appel portail séparé plutôt qu'à le corriger davantage.

### garde-fous organisation + idempotence suppression (rudi-commune-starterkit v2)

Ajouts dans `rudi_client.py`, motivés par le plan v2 de `rudi-commune-starterkit`
(registre de communes, garde-fou organisation, « vider une commune ») :

- **`organisation_par_nom(conf, organization_name)`** : recherche une organisation par
  nom normalisé via une requête HTTP brute (`GET {url_catalog}/v1/organizations`, sans
  filtre serveur), en garantissant la présence de `organization_status`/
  `linked_producer_status` dans le résultat — contrairement à `lister_organisations(conf)`
  sans `statut`, qui expose `organization_list` (pas de garantie sur ces deux champs).
  Volontairement séparée de `lister_organisations()`, dont le contrat existant
  (`resolution_noeud.py`, moissonneur-ods) n'est pas touché.
- **`global_id_pour_local_id(conf, local_id)`** : résout le `global_id` d'un dataset
  déjà publié à partir de son `local_id`, pour les appelants qui ne suivent localement
  que `local_id`/hash de contenu (comme `rudi-commune-starterkit`), jamais `global_id`.
- **Idempotence 404** sur `supprimer_dataset()` et `supprimer_organisation()` : un `404`
  (déjà supprimé) est désormais traité comme un succès, même principe que le `409` déjà
  géré par `demander_detachement_producteur()` — nécessaire pour qu'une suppression de
  commune reste ré-exécutable après une interruption (Ctrl-C) sans échec en boucle sur
  ce qui a déjà été supprimé au run précédent. `supprimer_dataset_portail()` et
  `demander_suppression_organisation()` (côté portail) ne reçoivent **pas** ce
  traitement : un `404` y est ambigu (ressource jamais moissonnée vs déjà supprimée),
  contrairement au nœud où l'appelant sait toujours que la ressource a existé.
- **`demander_creation_organisation()` : documentation corrigée, aucun code ajouté.**
  Une piste de garde-fou anti-zombie (suppression de l'organisation si le relais vers le
  portail semblait raté) a été explorée puis **abandonnée après investigation en
  conditions réelles** (2026-11-08, nœud source raccordé, portail coupé puis relancé) :
  le scénario qu'elle visait à corriger ne peut pas se produire sur ce nœud. Le code
  source confirme que le relais nœud→portail est **synchrone et bloquant**
  (`rudi-catalog/src/controllers/genericController.js::newRudiObject` fait
  `await createPortalOrganization(dbObject)` **avant** `dbObject.save()` — toute erreur du
  relais interrompt la fonction avant la sauvegarde locale), ce que confirme aussi le test
  réel : portail coupé → `503 "rudi-catalog semble injoignable"`, rien créé ; portail up →
  succès, relais confirmé. Il n'existe donc aucune organisation qui existe sur le nœud
  sans avoir été relayée — une vérification après coup n'aurait rien à corriger.
  La docstring documente ce comportement (et corrige une note antérieure, écrite après une
  lecture trop rapide de ce même fichier, qui décrivait ce relais comme fire-and-forget).

## 0.2.0 — Modules partagés génériques (ajouts additifs)

Ajout de 5 nouveaux modules, chacun généralisant une brique déjà dupliquée ailleurs dans
l'écosystème (`moissonneuse-batteuse`, `moissonneur-ods`). **Purement additif** : aucun
module existant (`pivot.py`, `rudi_client.py`, `publish.py`, `state.py`, `http.py`,
`markdown.py`, `__init__.py`) n'a été modifié, et aucun de ces nouveaux modules n'est importé
depuis `__init__.py` (pour que leurs dépendances restent optionnelles/différées — en
particulier, aucun des nouveaux modules n'a de dépendance supplémentaire au-delà de ce que
`rudi_harvest_toolkit.http` fournit déjà). `moissonneuse-batteuse` et `moissonneur-ods`
continuent de fonctionner avec leurs copies locales sans aucune action requise ; cette section
documente comment migrer **quand on le décide**, pas une obligation immédiate.

Objectif de cette section : donner à une future session de migration tout ce qu'il faut
sans redécouvrir les différences de comportement par la lecture du diff.

---

### `rudi_harvest_toolkit.tabular`

**Généralise** : le moteur de parsing CSV de
`moissonneuse-batteuse/src/harvest_batch.py::filtrer_csv()` (détection d'encodage/
délimiteur via `_detecter_encodage()`/`_detecter_delimiteur()`, lecture en flux par
`csv.DictReader`) — **sans** la cascade de détection géographique à 8 niveaux qui s'y trouve
câblée (`_ligne_est_rm()`, qui teste dans l'ordre IRIS/INSEE, code postal+ville, adresse,
SIREN via `obtenir_sirens_rm()`, EPCI, coordonnées, circonscription, département — voir
« Geographic detection in CSVs » dans `CLAUDE.md` de ce repo), qui reste dans
`moissonneuse-batteuse`, propre à ce projet.

**Différences à connaître avant de migrer** :
- Le filtre est **une seule valeur de colonne exacte** (`filtrer_csv(source, colonne,
  valeur)`), pas une cascade de règles géographiques à plusieurs champs. `filtrer_csv()`
  de `harvest_batch.py` prend dix paramètres de champs optionnels (`champ_cp`,
  `champ_ville`, `champ_iris`, `champ_adresse`, `champ_siren`, `champ_epci`, `champ_lat`,
  `champ_lon`, `champ_circonscription`, `champ_dep`) et choisit dynamiquement lequel utiliser
  ligne par ligne ; migrer un connecteur RM vers la version toolkit n'est pertinent que pour
  un cas à un seul critère exact (ex. un futur connecteur filtrant uniquement par SIREN), pas
  pour remplacer `filtrer_csv()` tel quel — son attribution de nom (`filtrer_csv`, même nom
  dans les deux modules) est une coïncidence à ne pas lire comme une parité d'API.
- Résolution de nom de colonne **tolérante** (accents/casse/underscores ignorés) — l'original
  de `moissonneuse-batteuse` attend un nom de colonne exact.
- Décompression gzip **automatique** par extension ou octets magiques — l'original ne gère
  le gzip qu'explicitement là où c'est câblé (fonctions `*_gz` séparées).
- `csv.field_size_limit(10_000_000)` repris à l'identique (même valeur que
  `moissonneuse-batteuse`, nécessaire pour les géométries/listes volumineuses de BAN/DVF/RNE).

**Avant** (`moissonneuse-batteuse`, cascade géographique à 10 champs possibles) :
```python
from harvest_batch import filtrer_csv

lignes, entetes = filtrer_csv(
    chemin_fichier, champ_cp="code_postal", champ_ville="ville",
    champ_iris=None, champ_adresse=None,
)  # _ligne_est_rm() teste le champ fourni, pas une valeur unique
```

**Après** (`rudi-commune-starterkit`, filtre à une valeur exacte, en flux) :
```python
from rudi_harvest_toolkit.tabular import filtrer_csv

for ligne in filtrer_csv("https://exemple.fr/ban-35.csv.gz", "code_insee", "35120"):
    ...  # rien en mémoire au-delà de la ligne courante
```

---

### `rudi_harvest_toolkit.datagouv`

**Généralise** : `moissonneuse-batteuse/src/connectors/datagouv.py`
(`get_dataset_metadata()` + `find_resource_by_format()`, premier match par format).

**Différences à connaître avant de migrer** (noms de fonctions réels vérifiés dans
`moissonneuse-batteuse/src/connectors/datagouv.py` au moment de l'écriture) :
- `get_dataset_metadata(dataset_id)` a la **même signature et le même comportement** —
  migration directe sans adaptation pour cette fonction précise.
- `selectionner_ressource()` remplace `find_resource_by_format(metadata, fmt,
  title_contains=None)` avec un **mode de sélection explicite et obligatoire** (`index=`,
  `motif_nom=` [regex insensible à la casse, remplace `title_contains` — sous-chaîne simple
  dans l'original — par un filtre plus expressif], ou `la_plus_recente=True`,
  optionnellement combiné à `format=`) — passer zéro ou plusieurs modes lève
  `ErreurSelectionRessource` plutôt que deviner.
- `find_resource_by_format()` retournait silencieusement `None` si rien ne correspondait ;
  `selectionner_ressource()` lève `RessourceIntrouvableError` — à adapter si l'appelant
  migré testait `if ressource is None`.
- Une sélection ambiguë (motif qui matche plusieurs ressources) lève
  `SelectionAmbigueError` plutôt que de retourner silencieusement la première — à anticiper
  si le code migré comptait implicitement sur un "premier match".
- `la_plus_recente=True` ignore les ressources sans `last_modified`/`created_at` exploitable,
  et prend la **première** en cas d'égalité stricte de date (comportement déterministe à
  vérifier si l'ordre des ressources retourné par l'API changeait).
- `download_resource()` (téléchargement simple, sans cache) n'a **pas** d'équivalent dans ce
  module — utiliser `rudi_harvest_toolkit.download_cache.telecharger()` à la place, qui
  ajoute un cache disque (voir section suivante).

**Avant** (`moissonneuse-batteuse`, premier CSV trouvé) :
```python
from connectors.datagouv import get_dataset_metadata, find_resource_by_format

meta = get_dataset_metadata("repertoire-national-des-elus")
ressource = find_resource_by_format(meta, "csv")  # le premier, parmi 12 mandats
```

**Après** (`rudi-commune-starterkit`, sélection explicite) :
```python
from rudi_harvest_toolkit.datagouv import get_dataset_metadata, selectionner_ressource

meta = get_dataset_metadata("repertoire-national-des-elus")
ressource = selectionner_ressource(meta, motif_nom=r"conseillers municipaux", format="csv")
```

---

### `rudi_harvest_toolkit.download_cache`

**Généralise** : `moissonneuse-batteuse/src/connectors/download.py` (cache disque MD5 de
l'URL, purge par ancienneté).

**Différences à connaître avant de migrer** (nom de fonction réel : `_telecharger()`,
privée, préfixée `_`, dans `connectors/download.py`) :
- **Aucune requête conditionnelle** (ETag/Last-Modified) dans l'original ni dans cette
  généralisation — confirmé par lecture du code.
- **Différence de fraîcheur plus importante que "juste un TTL des deux côtés"** : l'original
  ne vérifie **aucun âge à la lecture** — `if os.path.exists(chemin): return chemin`,
  point. Le TTL n'existe que côté purge manuelle (`_purger_cache(jours=30)`, à appeler
  explicitement, jamais invoqué automatiquement par `_telecharger()`). Le nouveau
  `telecharger()` vérifie l'âge **à chaque appel** (`_est_expire()`) et re-télécharge
  lui-même si expiré — un vrai changement de comportement, pas une simple extraction : un
  code migré qui comptait sur "une fois en cache, jamais ré-interrogé avant une purge
  explicite" verra désormais des requêtes réseau après `ttl_jours` (30 par défaut).
- `_telecharger()` **ne lève jamais d'exception** : elle retourne un tuple `(chemin, taille_mo,
  depuis_cache, erreur)` où `erreur` est `None` ou un message. `telecharger()` lève
  `ErreurTelechargement` à la place — tout code migré doit passer d'un test `if erreur:` à
  un `try/except ErreurTelechargement`.
- `plafond_mo` existait déjà dans l'original (défaut **200**) — **pas un ajout**, correction
  d'une affirmation erronée d'un brouillon précédent de ce changelog. La vraie différence :
  le défaut de `telecharger()` est `None` (illimité), pas 200 — un appelant migré qui voulait
  implicitement le plafond de 200 Mo doit désormais le passer explicitement.
- `dossier_cache_defaut()` retombe sur `$RUDI_HARVEST_CACHE`, puis XDG cache
  (`~/.cache/rudi-harvest-toolkit`) — l'original utilisait `conf.discover.CACHE_DIR`, un
  chemin fixe du projet. Un appelant qui veut le même emplacement qu'avant doit passer
  `dossier=` explicitement.

**Avant** (`moissonneuse-batteuse`, erreur par valeur de retour) :
```python
from connectors.download import _telecharger

chemin, taille_mo, depuis_cache, erreur = _telecharger(url, verbose=True, plafond_mo=200)
if erreur:
    ...  # gérer l'échec sans exception
```

**Après** (`rudi-commune-starterkit`) :
```python
from rudi_harvest_toolkit.download_cache import telecharger

chemin = telecharger(url, dossier="data/cache", ttl_jours=30)
```

---

### `rudi_harvest_toolkit.commune`

**Généralise** : rien d'existant à proprement parler — c'est une brique **nouvelle**,
écrite pour `rudi-commune-starterkit`, mais générique par construction (toute résolution
« code INSEE → nom/géographie/SIREN » est utile à un futur moissonneur, pas seulement à ce
projet). Pas de migration à documenter puisqu'il n'y a pas de copie locale équivalente à
remplacer dans `moissonneuse-batteuse`/`moissonneur-ods` (qui opèrent sur un territoire fixe,
codé en dur).

**Points d'attention pour tout futur appelant** :
- `resoudre_siren_commune()` envoie **toujours** `nature_juridique=7210` — sans ce filtre,
  `recherche-entreprises.api.gouv.fr` renvoie plusieurs entités (CCAS, syndicats...) pour un
  même code commune.
- Aucun `int(code_insee)` nulle part (compatibilité Corse `2A`/`2B`).
- Les codes d'arrondissement municipal (Paris/Lyon/Marseille) sont **refusés** avant tout
  appel réseau — ce ne sont pas des communes au sens de ces deux API.
- Aucun repli hors-ligne : une panne réseau lève une exception explicite.

---

### `rudi_harvest_toolkit.fichier_hybride`

**Généralise** : `moissonneur-ods/src/moissonneur_ods/mode.py`
(`_empreinte_distante()` / `_media_file_distant()` / `_media_id()`), qui reste la seule
implémentation locale de ce pattern dans l'écosystème à ce jour.

**Différences à connaître avant de migrer** `moissonneur-ods` vers cette version partagée
(signatures exactes vérifiées dans `moissonneur_ods/mode.py`) :
- Le schéma `media_id` est repris **à l'identique**, formule par formule :
  `_media_id(local_id, cle)` (original) et `media_id_hybride(local_id, cle)` (toolkit)
  calculent tous les deux `uuid5(NAMESPACE_URL, f"{local_id}/ods-media/{cle}")` puis forcent
  les mêmes nibbles version/variant — **à condition d'appeler les deux avec le même
  `cle`** (ici l'URL), pas une garantie automatique du seul fait d'utiliser le toolkit. C'est
  une exigence de stabilité incrémentale, pas un détail à ajuster : une migration qui
  changerait la `cle` passée republierait tous les médias hybrides déjà publiés sous un
  nouvel id.
- **Gestion d'erreur radicalement différente, pas un simple détail d'API** :
  `_empreinte_distante(url, taille_max, session, timeout=120)` de l'original **ne lève
  jamais** — elle retourne `{"hash":.., "taille":..}` ou `{"erreur": "reseau"|"trop_gros",
  ...}`, et `taille_max`/`session` sont **positionnels obligatoires**, sans défaut.
  `empreinte_distante()` du toolkit lève `ErreurEmpreinteDistante`/`FichierTropVolumineux`,
  et `taille_max`/`session_http` sont optionnels avec défauts (500 Mo, session partagée du
  toolkit). Un appelant migré qui testait `if "erreur" in empreinte:` doit passer à un
  `try/except`.
- `_media_file_distant(media_id, nom, caption, url, mimetype, empreinte)` de l'original
  exige un `media_id` et une `empreinte` **déjà calculés séparément** par l'appelant (deux
  appels explicites : `_media_id()` puis `_empreinte_distante()`, puis `_media_file_distant()`
  assemble). `construire_media_hybride(local_id, url, ...)` du toolkit **fait les trois en
  un seul appel** (calcule l'empreinte via `empreinte_distante()` si `empreinte=` n'est pas
  fourni, calcule le `media_id` via `media_id_hybride()`) — une simplification d'API, pas
  juste un renommage.
- `taille_max` (défaut 500 Mo dans le toolkit, même limite que le nœud RUDI) interrompt la
  lecture et lève `FichierTropVolumineux` plutôt que de construire un média pour un fichier
  qui serait rejeté par le nœud de toute façon — l'original retourne `{"erreur":
  "trop_gros", ...}` pour le même cas, sans valeur par défaut (l'appelant doit la fournir).
- Le résultat satisfait `rudi_client._media_file_deja_complet()` (vérifié par test) — ce
  prédicat existant n'est lui-même **pas modifié**, seul ce nouveau module construit un
  média qui le satisfait.

**Avant** (`moissonneur-ods`, trois appels, erreurs par valeur de retour) :
```python
from moissonneur_ods.mode import _media_id, _empreinte_distante, _media_file_distant
from moissonneur_ods.connectors.http import session

empreinte = _empreinte_distante(url, taille_max=500 * 1024 * 1024, session=session)
if "erreur" in empreinte:
    ...  # gérer l'échec sans exception
media_id = _media_id(local_id, url)
media = _media_file_distant(media_id, nom_fichier, caption, url, "text/csv", empreinte)
```

**Après** (équivalent partagé, un seul appel) :
```python
from rudi_harvest_toolkit.fichier_hybride import construire_media_hybride

media = construire_media_hybride(
    local_id, url, media_name=nom_fichier, media_caption=caption, file_type="text/csv",
)
```
