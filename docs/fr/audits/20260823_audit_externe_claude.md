# Audit de sécurité externe (Claude) — 23 août 2026

**Objet** : `michaellaunay/urlshortener`, HEAD
`7db2b6b8dba9eb6f0ccce7b5511ba5b2aba3df29` — version déclarée **2.0.19**
(train 0019).
**Auditeur** : externe (Claude, Anthropic), à la demande de Michaël
Launay.
**Passe croisée** : troisième passe externe ChatGPT, portée sur
`056ef3b` (2.0.17), soit **deux trains avant** ce HEAD — les
trains 0018 et 0019 ont atterri entre l'audit croisé et celui-ci, le
même jour.
**Méthode** : clone du dépôt ; lecture intégrale du code applicatif, des
fichiers de déploiement, des trois workflows et des nouveaux tests ;
exécution de la suite complète dans l'environnement verrouillé
(`requirements-test.lock`, `--require-hashes`) ; vérifications GitHub
par l'API REST et par les badges de workflow ; validation YAML de tous
les fichiers de déploiement ; rejeu historique des constats ChatGPT sur
le commit qu'ils visaient (`git show 056ef3b:...`).
**Limites déclarées** : pas de test de charge ; pas d'accès aux
paramètres du dépôt réservés aux administrateurs (le champ `protected`
de `main` n'a pas pu être relu, l'API anonyme ayant atteint sa limite
de débit après les premières requêtes) ; pas d'exécution du workflow
Smoke (impossible, voir N-01).

**Verdict** : le cœur applicatif reste **sans vulnérabilité
critique/P0**, et les quatre constats de la troisième passe ChatGPT
(E-01 à E-04) sont **réellement corrigés** au HEAD — chaque correctif a
été vérifié dans le code, pas seulement dans le changelog. Le point le
plus important de cette passe est ailleurs, et ChatGPT ne pouvait pas
le voir : **le workflow Smoke — la porte écrite pour valider le
déploiement — est du YAML invalide depuis le commit initial et n'a
jamais tourné une seule fois** (N-01, correctif fourni et vérifié).

---

## 1. Croisement, constat par constat, avec la troisième passe ChatGPT

La passe croisée visait 2.0.17. Deux trains ont été livrés depuis ;
chaque ligne ci-dessous dit ce que j'ai vérifié **au HEAD actuel**.

| Constat ChatGPT (sur 2.0.17) | Vérifié au HEAD 2.0.19 | Preuve |
| --- | --- | --- |
| 🔴 P1 — unité systemd incohérente avec `production.ini` (`%(here)s` → `etc/var/`, illisible sous `ProtectSystem=strict`) | ✅ **Corrigé** (train 0019) | `EnvironmentFile=` fixe `SQLALCHEMY_URL` absolu sous `ReadWritePaths` ; `tests/test_deployment_coherence.py::test_e01_*` verrouillent le chemin ; voir §2.1 pour la chaîne complète |
| 🟠 P1 — le `.env` documenté jamais chargé ; deux unités divergentes dans le dépôt | ✅ **Corrigé** (trains 0018 + 0019) | Une seule unité livrée, `WorkingDirectory=/srv/urlshortener/app`, `EnvironmentFile=/srv/urlshortener/etc/urlshortener.env` ; les deux chapitres d'installation pointent vers le fichier livré (zéro bloc `[Service]` en ligne dans les docs) ; tests `test_e02_*` |
| 🟠 P1 — six variables non transmises par Compose (`COUNT_HITS`, `THROTTLE_MAX_READS`, `MAX_URL_LENGTH`, `CODE_MAX_ATTEMPTS`, `DEFAULT_SCHEME`, `ALLOWED_SCHEMES`) | ✅ **Corrigé** (train 0019) | Les six figurent dans `docker-compose.yaml` et `.env.example` ; le test de parité couvre désormais **toutes** les `URLSHORTENER_*` lues par `constants_and_globals.py`, pas seulement les variables serveur |
| 🟡 P2 — paquet 2.0.17, `__version__` 2.0.16 | ✅ **Corrigé** (train 0019) | `__version__` vient d'`importlib.metadata` — la source unique recommandée par la passe croisée, appliquée telle quelle ; deux tests `test_e03_*` |
| 🟠 P1/P2 — `--allow-unsafe-legacy` importe des URL techniquement invalides | ❌ **Toujours présent** — `tools/import_legacy.py` inchangé depuis la passe croisée. J'ajoute des conséquences concrètes qui renforcent le constat, voir N-03 | Lecture du code + rejeu de `to_wire_url` |
| 🟠 P1 — un `UPDATE` SQLite par redirection | ⚠️ **Toujours le défaut**, mais le constat a changé de nature : `URLSHORTENER_COUNT_HITS=false` fonctionne désormais **partout** (c'était l'objet d'E-04). WAL est actif en atténuation. C'est maintenant une décision d'exploitation, plus un défaut de plomberie | `services.record_hit` honore le réglage ; Compose le transmet |
| 🟠 P1 — `GET /?url=` créateur activé | ⚠️ **Risque assumé, inchangé** — journalisé, `Deprecation` + `Link` vers le successeur. Je propose une atténuation compatible 2016, voir N-05 | `views._legacy_get_json` |
| 🟡 P2 — `/healthz` divulgue le nombre de liens | ⚠️ **Présent, mais à requalifier** : le compte est déjà **public par conception** en pied de chaque page (`layout.pt`, « links stored »). Il ne reste qu'un point mineur, voir N-04 | `templates/layout.pt` l. 43-45 |
| 🟡 P2 — `main` non protégée, commits non signés | ⚠️ Non-signature **confirmée** par l'API (`verified: false, reason: unsigned` sur les trois derniers commits). La protection de branche n'a pas pu être relue (limite de débit) ; le `protected: false` de la passe croisée reste la seule mesure | API `/commits`, 23/08 |
| 🟢 — validation URL/IDNA/IP/CORS/limiteur en bon état | ✅ **Confirmé**, par relecture indépendante — détail au §4 | — |
| Réserve ChatGPT : « aucun statut CI associé au HEAD » via le connecteur | 🆕 **Élucidé, et c'est le constat majeur de cette passe** : sur ce HEAD, `tests (3.11)` ✔, `tests (3.12)` ✔, `quality` ✔ — et **Smoke n'a jamais tourné, sur aucun commit, depuis la création du dépôt** (N-01) | API `check-runs` (3 runs, tous `success`) + badge + `ScannerError` |

Bilan du croisement : la passe ChatGPT était **exacte sur ses quatre
constats nouveaux** — je les ai rejoués sur `056ef3b` et tous les
quatre s'y vérifient à la lettre — et les trains 0018/0019 les ont
**réellement** fermés, avec les verrous de non-régression qui
conviennent. Les points restants de sa liste sont soit des décisions
d'exploitation déjà documentées comme telles, soit le point 5
(`--allow-unsafe-legacy`), que je reprends et aggrave ci-dessous.

---

## 2. Vérifications de fond des correctifs 0018/0019

Un changelog qui dit « corrigé » n'est pas une preuve. Voici ce que
j'ai vérifié.

### 2.1 La chaîne systemd fonctionne réellement de bout en bout

Le point subtil d'E-01 n'était pas seulement le chemin SQLite : c'est
que `ExecStartPre` (le CLI d'upgrade) et `ExecStart` (`pserve`) doivent
**tous deux** voir le `SQLALCHEMY_URL` du fichier d'environnement.
Vérifié :

- systemd applique `EnvironmentFile=` à **toutes** les directives
  `Exec*`, `ExecStartPre` compris ;
- `upgrades.main()` passe par `pyramid.paster.bootstrap()`, qui
  instancie la fabrique `urlshortener:main`, laquelle lit
  `os.environ["SQLALCHEMY_URL"]` **avant** de construire le moteur —
  le moteur que `ensure_database_directory()` et `create_schema()`
  reçoivent est donc bien celui du chemin absolu sous
  `ReadWritePaths`, pas celui du `%(here)s` de l'ini ;
- `ensure_database_directory()` (train 0018) crée `var/` seulement
  pour un fichier SQLite sur disque — ni `:memory:`, ni PostgreSQL —
  ce qui est la bonne portée.

L'installation documentée démarre donc, y compris sur machine vierge.

### 2.2 La parité Compose est verrouillée au bon niveau

Le test d'E-04 ne compare plus une liste écrite à la main : il extrait
par expression régulière **toutes** les `URLSHORTENER_*` de
`constants_and_globals.py` et exige leur présence dans
`docker-compose.yaml` **et** `.env.example`. C'est exactement ce qui
manquait au test du train 0004 (qui ne couvrait que les variables
serveur) — la classe de régression est fermée, pas seulement
l'instance. Réserve : ce verrou ne couvre pas le côté systemd, voir
N-02.

### 2.3 La suite passe, et la documentation est verrouillée dessus

```
506 passed, 28 warnings in 15.52s
Required test coverage of 85% reached. Total coverage: 92.70%
```

Environnement : lock de test en `--require-hashes`, Python 3.12.3 —
la même recette que `tests.yml`. Détail appréciable :
`tests/test_documentation.py::test_the_quoted_test_count_is_the_real_one`
verrouille le « 506 tests » cité dans le README et les deux chapitres
d'installation contre le compte réellement collecté — mon propre patch
(§3.1) a déclenché ce verrou, ce qui est précisément son travail.

---

## 3. Découvertes propres à cette passe

### N-01 (P1, gouvernance) — le workflow Smoke est du YAML invalide depuis le commit initial et n'a jamais tourné

**Le fait.** `.github/workflows/smoke.yml`, ligne 33 :

```yaml
        run: curl -fsS http://127.0.0.1:5123/healthz | tee /dev/stderr | grep -q '"status": "ok"'
```

Le scalaire est **nu** (il commence par `curl`, pas par un guillemet),
donc les apostrophes internes sont des caractères ordinaires — et la
séquence `": "` à l'intérieur de `'"status": "ok"'` est, pour YAML, un
indicateur de mapping en plein milieu d'un scalaire. Tout analyseur
conforme refuse le fichier :

```
yaml.scanner.ScannerError: mapping values are not allowed here
  in ".github/workflows/smoke.yml", line 33, column 91
```

**Depuis quand.** `git log -S'"status": "ok"' -- .github/workflows/smoke.yml`
ne renvoie qu'un commit : `f7c5642`, le commit initial du dépôt. Le
fichier n'a jamais été retouché. **La porte Smoke n'a donc jamais
fermé — pas une fois, sur aucun des dix-neuf trains.**

**Preuves convergentes côté GitHub.**

- Badge du workflow : « **smoke.yml - failing** » — et le fait que le
  badge affiche le *nom de fichier* plutôt que le nom `Smoke` déclaré
  dedans est le symptôme classique d'un fichier de workflow que GitHub
  n'a pas pu analyser ;
- `GET /commits/7db2b6b…/check-runs` : `total_count: 3` —
  `tests (3.11)` ✔, `tests (3.12)` ✔, `quality` ✔. Aucun check
  `smoke` : un workflow au fichier invalide produit un run en échec
  « startup », sans check runs — ce qui explique au passage pourquoi le
  connecteur GitHub de la passe croisée ne « voyait » rien de net ;
- `tests.yml`, `quality.yml` et `docker-compose.yaml` sont, eux, du
  YAML valide (vérifié).

**Pourquoi c'est le constat le plus important de cette passe.** Le
dépôt a déjà nommé ce motif lui-même : D-05 était « deux portes qui
existaient et n'ont jamais fermé » (les checks compose sautés faute de
PyYAML). En voici la **troisième occurrence**, et la plus lourde : le
Smoke est précisément la porte de niveau *déploiement* — la classe de
défauts d'E-01/E-02 est celle qu'il existe pour attraper (côté
conteneur). Le changelog 2.0.18 écrit d'ailleurs « ni le workflow
Smoke ni une ré-exécution […] ne l'ont jamais montré » : la phrase est
vraie, mais pas pour la raison crue — le Smoke n'a rien montré parce
qu'il n'a jamais existé à l'exécution. Et le README annonce « three CI
workflows » : trois fichiers, deux exécutions.

**Correctif — fourni et vérifié.** Scalaire de bloc pour la ligne
fautive, plus un méta-test qui analyse chaque fichier de
`.github/workflows/` (PyYAML est déjà dans le lock de test depuis
D-05, coût nul), plus la mise à jour du compte de tests que le verrou
documentaire exige (506 → 510). Le patch complet est en **annexe A** ;
je l'ai appliqué sur un arbre vierge (`git apply --check` propre), le
YAML corrigé est valide, et la suite passe : `510 passed`. Une fois
poussé, vérifier que le run Smoke va **au vert** — le YAML n'a jamais
été exécuté, donc les étapes elles-mêmes n'ont jamais été éprouvées en
CI (à la lecture, elles sont cohérentes avec le Compose actuel : la
grep `"status": "ok"` correspond bien à la sortie du renderer JSON de
Pyramid, et les variables d'environnement du job sont transmises).

### N-02 (P2) — trois variables du fichier d'environnement systemd sont inertes

`deploy/systemd/urlshortener.env.example` livre :

```ini
URLSHORTENER_LISTEN=127.0.0.1:5123
URLSHORTENER_TRUSTED_PROXY=127.0.0.1
URLSHORTENER_TRUSTED_PROXY_COUNT=1
```

Or ces trois variables ne sont lues **que** par
`docker/apply_server_overrides.py` — qui ne s'exécute que dans le
conteneur. Sur le chemin bare-metal, `pserve` lit `[server:main]`
directement dans `production.ini`, et rien ne fait le pont : un
opérateur qui change `URLSHORTENER_LISTEN` dans `urlshortener.env` est
**ignoré en silence**. Les valeurs par défaut coïncident
(`127.0.0.1:5123` ≈ `localhost:5123` de l'ini), donc rien ne casse à
l'installation — c'est exactement ce qui rend le défaut invisible.

C'est la **troisième maison** du motif C-07/E-04 : « un réglage auquel
l'opérateur croit et qui n'arrive jamais ». Et le verrou d'E-04 ne le
voit pas, car il ne couvre que les variables du module de réglages
applicatifs, pas celles d'`apply_server_overrides.OVERRIDES`.

Deux corrections possibles, au choix du mainteneur :

1. **(simple, recommandée)** retirer ces trois lignes de
   `urlshortener.env.example` et y écrire une phrase : sur bare metal,
   `listen`/`trusted_proxy`/`trusted_proxy_count` se règlent dans
   `[server:main]` de `production.ini` — plus un test de parité côté
   unité : aucune variable d'`OVERRIDES` ne doit figurer dans
   `urlshortener.env.example` tant que rien ne la consomme sur ce
   chemin ;
2. (symétrique) faire dériver un `runtime.ini` par
   `apply_server_overrides.py` dans un `ExecStartPre`, comme le fait le
   conteneur — plus lourd, mais une seule mécanique pour les deux
   déploiements.

### N-03 (P2) — `--allow-unsafe-legacy` : le constat ChatGPT est confirmé, et ses conséquences sont pires que « des URL techniquement invalides »

Le point 5 de la passe croisée tient toujours : dès que `allow_unsafe`
est vrai, `classify()` court-circuite `normalise_url()` entièrement.
Seuls `bad_code`, `reserved_code`, `empty_url`, `control_chars` et les
schémas `javascript/data/vbscript` restent infranchissables. J'ajoute
ce que produisent **concrètement** les lignes ainsi importées, en
suivant le propre critère du module (« refusé TOUJOURS quand l'import
produit quelque chose qui *ne peut pas* fonctionner ») :

- **Port invalide** (`http://example.org:99999/`) : la ligne ne peut
  pas fonctionner — et pire, elle fonctionne *de travers*. Au
  redirect, `to_wire_url()` attrape le `ValueError` de `parts.port`
  (la branche héritée de C-16, écrite pour les lignes legacy) et
  reconstruit le netloc **sans le port** : le visiteur est envoyé sur
  `http://example.org/` — une **autre destination** que celle stockée.
  C'est une violation silencieuse du contrat verbatim que l'outil
  d'import défend par ailleurs. Par le critère du module lui-même, le
  port invalide appartient à `ALWAYS_REFUSED`.
- **Hôte non encodable en IDNA portant du non-ASCII** (par exemple
  `http://☃.net/`, U+2603 étant *disallowed* en UTS #46) :
  `canonical_host(strict=False)` rend l'hôte inchangé, `to_wire_url()`
  le remet tel quel dans le netloc, et la `Location:` contient du
  non-ASCII — c'est la **résurgence exacte de S-01** (500 à chaque
  visite, à jamais, journal inondable sans authentification) pour ces
  lignes-là, alors que S-01 a été fermé partout ailleurs.
- **Credentials dans l'autorité** (`http://banque.example@evil.test/`) :
  le déguisement refusé à la création est importable — plus discutable
  (le lien « marche »), mais c'est un vecteur, pas une politique.
- **`file:` (et tout schéma hors `javascript/data/vbscript`)** :
  importable. Un `Location: file:///…` n'est pas suivi par un
  navigateur moderne, mais servir cela sous son propre domaine reste
  indéfendable ; `file:` a sa place dans `NEVER_IMPORTED_SCHEMES`.

**Recommandation** : la partition proposée par la passe croisée est la
bonne ; je la précise. À déplacer dans l'infranchissable : **port
invalide**, **hôte irrécupérable** (échec `canonical_host` strict),
**credentials** ; à ajouter à `NEVER_IMPORTED_SCHEMES` : `file`.
Restent contournables, et c'est légitime : cible privée, hôte bloqué,
URL trop longue, schéma *fonctionnel* hors liste (`ftp:` d'époque). Le
rapport d'import gagnerait une ligne par catégorie déplacée, pour que
l'opérateur voie ce que le drapeau ne lève plus.

### N-04 (P3) — `/healthz` : requalification du P2 de la passe croisée

Le compte de liens n'est pas une divulgation : il est affiché **en
pied de chaque page** (« *N links stored* », `layout.pt`). Ce qui
reste : un `COUNT(*)` non authentifié par appel, sur un endpoint que
seul le healthcheck Docker consomme — lequel ne greppe que
`"status": "ok"`. Correction à coût nul si souhaitée : retirer `links`
du payload (aucun consommateur ne le lit), ou réserver `/healthz` au
réseau interne dans la recette nginx. À défaut, risque assumé
parfaitement défendable.

### N-05 (P3, opportunité) — appliquer `Sec-Fetch-Site` au GET legacy

Le triptyque C-09 (GET qui écrit, cible dans la query string, aucune
barrière cross-origin) est un risque assumé tant que KuneAgi appelle.
Or la barrière D-02 existe déjà dans le code et n'est simplement **pas
branchée** sur ce chemin : `_legacy_get_json()` n'appelle pas
`cross_site_creation()`. La brancher :

- **bloque** le vecteur navigateur (`<img src="…/?url=…">`, prefetch,
  page tierce) — tout navigateur actuel envoie
  `Sec-Fetch-Site: cross-site` sur ces requêtes, et une page ne peut
  ni le retirer ni le choisir ;
- **ne casse pas KuneAgi** : un appel serveur-à-serveur n'envoie pas
  l'en-tête, et la fonction est *fail-open* par construction — le
  contrat 2016 pour les clients non-navigateurs est intact.

C'est la seule des trois branches du triptyque qui se ferme sans
attendre la migration des appelants ; les deux autres (GET avec effet
de bord, cible dans la query string) tombent avec l'extinction du
point d'entrée, comme prévu.

---

## 4. Ce que la relecture indépendante confirme sain

Relu en entier, sans s'appuyer sur les audits précédents :
`urlvalidation.py` (les quatre graphies IPv4 du standard URL, UTS #46
non transitionnel, `is_global` en complément, port lu avant tout,
credentials et caractères de contrôle refusés, une seule
canonicalisation partagée par tous les contrôles et par le stockage) ;
l'anti-open-redirect du sélecteur de langue (le paramètre n'est jamais
réécho : la destination est régénérée depuis une route nommée) ; le
limiteur (O(1) amorti, plafond de clés avec éviction LRU, /64 IPv6,
jamais d'adresse en base) ; les en-têtes (CSP sur HTML seulement,
`frame-ancestors 'none'`, `Vary: Origin` y compris sur refus,
`Referrer-Policy` et `Cache-Control: no-store` sur le redirect) ; le
corps borné par `Content-Length` déclaré, waitress portant la même
limite ; SQL intégralement paramétré (SQLAlchemy Core/ORM, aucun
f-string) ; Chameleon échappe `${…}` par défaut dans les trois
gabarits ; la création sous SAVEPOINT avec reprise du concurrent ;
WAL par moteur et non par classe (S-11) ; l'import legacy en
lecture seule avec chemin quoté (S-03) ; la chaîne
d'approvisionnement (locks hachés trois profils, image par digest,
wheel-only à une exception près et nommée, `runtime.ini` créé 0600,
URL de base masquée dans les logs quand elle porte un secret,
sauvegarde `umask 077` en flux) ; `pip-audit` vert en CI sur ce SHA
avec **une** exception documentée (PYSEC-2026-3447, setuptools épinglé
par pyramid 2.1 — à revisiter à chaque release de pyramid, comme le
commentaire l'exige). Rien d'autre à signaler dans ce périmètre.

---

## 5. Ordre des actions recommandé

1. **N-01** — appliquer le patch de l'annexe A, pousser, vérifier que
   le run Smoke va au vert. Tant qu'il ne tourne pas, le dépôt a deux
   portes sur les trois qu'il annonce.
2. **Point 5 / N-03** — reclasser port invalide, hôte irrécupérable et
   credentials dans l'infranchissable ; `file` dans
   `NEVER_IMPORTED_SCHEMES`. C'est le dernier constat de la passe
   croisée encore ouvert dans le code.
3. **N-02** — assainir `urlshortener.env.example` (option 1) et
   étendre la parité au fichier d'environnement de l'unité.
4. **Gouvernance** — protéger `main`, exiger les trois workflows
   (Smoke réparé compris) comme checks obligatoires, signer les
   commits. Sans le 1, exiger Smoke bloquerait tout ; c'est pourquoi
   il vient d'abord.
5. **Décisions d'exploitation**, dans l'ordre déjà documenté :
   `count_hits = false` sur l'instance publique (désormais possible
   partout), N-05 sur le GET legacy en attendant la migration KuneAgi,
   N-04 si souhaité.

---

## Annexe A — patch N-01, vérifié

Appliqué sur `7db2b6b` : `git apply --check` propre, YAML valide,
`510 passed` (le verrou documentaire sur le compte de tests est
satisfait). À appliquer depuis la racine du dépôt :
`git apply 20260823_n01_smoke.patch`.

```diff
diff --git a/.github/workflows/smoke.yml b/.github/workflows/smoke.yml
index 3f0ca7d..10de223 100644
--- a/.github/workflows/smoke.yml
+++ b/.github/workflows/smoke.yml
@@ -30,7 +30,8 @@ jobs:
         run: docker compose -f docker/docker-compose.yaml up -d --wait
 
       - name: The service is healthy
-        run: curl -fsS http://127.0.0.1:5123/healthz | tee /dev/stderr | grep -q '"status": "ok"'
+        run: |
+          curl -fsS http://127.0.0.1:5123/healthz | tee /dev/stderr | grep -q '"status": "ok"'
 
       - name: A link can be created and then resolves
         run: |
diff --git a/README.md b/README.md
index 01586cb..0b35215 100644
--- a/README.md
+++ b/README.md
@@ -78,7 +78,7 @@ curl -I http://localhost:5123/h6QStqWsRk3   # 302 -> https://example.org/a/long/
 - **Operable**: digest-pinned multi-stage image, hash-checked
   dependency locks, non-root, health check, backup script, schema
   upgrade steps.
-- **Tested**: 506 tests, 91% coverage, three CI workflows (unit,
+- **Tested**: 510 tests, 91% coverage, three CI workflows (unit,
   quality, container smoke).
 - **Audited**: one internal pass and one external pass, both filed
   under `docs/fr/audits/`, every fixable finding fixed with a
diff --git a/docs/en/01_installation.md b/docs/en/01_installation.md
index 07f2986..aaa42eb 100644
--- a/docs/en/01_installation.md
+++ b/docs/en/01_installation.md
@@ -58,7 +58,7 @@ pytest -q
 pytest -q --cov=urlshortener --cov-report=term-missing
 ```
 
-506 tests, 91% coverage. The three exact quality-CI commands — run
+510 tests, 91% coverage. The three exact quality-CI commands — run
 these verbatim before any delivery:
 
 ```bash
diff --git a/docs/fr/01_installation.md b/docs/fr/01_installation.md
index cbb70a7..c900b0d 100644
--- a/docs/fr/01_installation.md
+++ b/docs/fr/01_installation.md
@@ -60,7 +60,7 @@ pytest -q
 pytest -q --cov=urlshortener --cov-report=term-missing
 ```
 
-506 tests, 91 % de couverture. Les trois commandes exactes de la CI
+510 tests, 91 % de couverture. Les trois commandes exactes de la CI
 qualité — à reproduire telles quelles avant toute livraison :
 
 ```bash
diff --git a/tests/test_workflows_parse.py b/tests/test_workflows_parse.py
new file mode 100644
index 0000000..a7622bc
--- /dev/null
+++ b/tests/test_workflows_parse.py
@@ -0,0 +1,40 @@
+# -*- coding: utf-8 -*-
+"""Every workflow file must be YAML a parser accepts (audit N-01).
+
+The Smoke workflow shipped in the very first commit with a plain
+scalar containing ``: `` -- ``grep -q '"status": "ok"'`` -- which YAML
+reads as a mapping indicator. GitHub refused the file, so the one gate
+written to validate the DEPLOYMENT never ran once, while its two
+siblings went green beside it. Same shape as D-05: a gate that exists
+and never closes fails nothing and protects nothing.
+
+PyYAML is already in the test lock (brought in by D-05 for the compose
+file), so this costs nothing new.
+"""
+import glob
+import os
+
+import pytest
+
+HERE = os.path.dirname(os.path.abspath(__file__))
+ROOT = os.path.dirname(HERE)
+WORKFLOWS = sorted(
+    glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))
+    + glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yaml"))
+)
+
+
+def test_there_are_workflows_to_check():
+    """An empty glob would make the test below pass by silence."""
+    assert WORKFLOWS, "no workflow files found under .github/workflows/"
+
+
+@pytest.mark.parametrize(
+    "path", WORKFLOWS, ids=[os.path.basename(p) for p in WORKFLOWS]
+)
+def test_workflow_is_valid_yaml_with_jobs(path):
+    yaml = pytest.importorskip("yaml")
+    with open(path, encoding="utf-8") as handle:
+        document = yaml.safe_load(handle)
+    assert isinstance(document, dict), "%s is not a YAML mapping" % path
+    assert document.get("jobs"), "%s declares no jobs" % path
```

---

## Suites au versement (23 août 2026)

Section ajoutée au moment du versement ; le rapport ci-dessus est
celui livré, inchangé, conformément à la règle du répertoire.

| Constat | Suite |
| --- | --- |
| N-01 — `smoke.yml` invalide depuis le commit initial, porte jamais fermée | **Corrigé**, train 0020 — premier run Smoke de l'histoire du dépôt : vert |
| Point 5 / N-03 — `--allow-unsafe-legacy` | **Corrigé**, train 0021 |
| N-02 — variables serveur inertes du fichier d'environnement systemd | **Corrigé**, train 0022 |
| Marche 4 — gouvernance de `main` | Contrat, commandes `gh api` et verrous consignés au train 0023 ; l'application des réglages reste un geste GitHub du mainteneur |
| N-05 — `Sec-Fetch-Site` sur le GET legacy | **Corrigé**, train 0024 — le verrou 0013 qui épinglait le trou est retourné |
| N-04 — compte de liens dans `/healthz` | Décision d'exploitation restante |
| Annexe A | Remplacée par la forme complète du train 0020, estampille comprise |
