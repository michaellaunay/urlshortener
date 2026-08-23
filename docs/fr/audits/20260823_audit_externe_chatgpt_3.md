# Audit de sécurité externe — troisième passe, 23 août 2026

**Objet** : `michaellaunay/urlshortener` **2.0.17**, commit `056ef3b`.
**Auditeur** : externe (ChatGPT), à la demande de Michaël Launay.
**Passe précédente** :
[seconde passe du 22 août](20260822_audit_externe_chatgpt_2.md), sur la
2.0.10.
**Méthode déclarée** : analyse statique du HEAD, connecteur GitHub.
**Verdict** : aucune vulnérabilité critique/P0 dans le cœur
applicatif ; un défaut **nouveau** du déploiement bare-metal (l'unité
systemd livrée incohérente avec la configuration qu'elle sert), une
régression de version, et les points des passes précédentes toujours
ouverts.

## Provenance et réserves

Ce document est le **versement** de l'audit reçu, avec sa mise en
correspondance avec les trains. Conformément à la règle de ce
répertoire, le texte reçu n'a pas été retouché.

Réserves à porter au dossier :

- l'auditeur a travaillé sur `056ef3b` (2.0.17). Les trains 0018 et
  0019 ont atterri **le même jour, avant ce versement**, et corrigent
  E-01 à E-04 ; les identifiants E-01 à E-04 ont été attribués au
  moment des correctifs (voir `CHANGES.txt`, 2.0.18 et 2.0.19), le
  texte reçu numérotant ses sections 1 à 8 ;
- la réserve de l'auditeur — « aucun statut CI associé au HEAD » via
  le connecteur GitHub — a été **élucidée** par l'audit croisé : le
  workflow Smoke était du YAML invalide depuis le commit initial et
  n'avait jamais tourné une seule fois. Voir
  [l'audit externe croisé (Claude)](20260823_audit_externe_claude.md),
  constat N-01, corrigé au train 0020.

## Correspondance avec les trains

| Constat de la passe | Identifiant | Suite |
| --- | --- | --- |
| Unité systemd livrée incohérente : `%(here)s` → `etc/var/`, illisible sous `ProtectSystem=strict` | E-01 | **Corrigé**, train 0019 |
| Le `.env` documenté jamais chargé ; deux unités divergentes dans le dépôt | E-02 | **Corrigé**, trains 0018 et 0019 |
| Paquet 2.0.17, `__version__` 2.0.16 | E-03 | **Corrigé**, train 0019 (source unique) |
| Six variables non transmises par Compose (`COUNT_HITS`, …) | E-04 | **Corrigé**, train 0019 |
| `--allow-unsafe-legacy` autorise des URL techniquement invalides | point 5 | **Corrigé**, train 0021 — durci au-delà du constat (port, hôte, credentials, `file:`) |
| Un `UPDATE` SQLite par redirection (`count_hits`) | — | Décision d'exploitation ; désactivable partout depuis E-04 |
| `GET /?url=` créateur activé | — | Risque **réduit** au train 0024 (`Sec-Fetch-Site`) ; la coupure reste une décision datée |
| `/healthz` divulgue le compte de liens | — | Requalifié par l'audit croisé (compte public en pied de page) ; décision restante |
| `main` non protégée, commits non signés | — | Contrat, commandes et verrous consignés au train 0023 ; les gestes GitHub restent au mainteneur |

## L'audit reçu, tel quel

Audit mis à jour sur le **HEAD actuel** :

`056ef3b8defc91d242898e2db152657258210b7c` — version déclarée **2.0.17**. Il n'y a qu'un commit supplémentaire depuis ma dernière passe.

### Verdict actuel

Je ne trouve toujours **aucune vulnérabilité critique/P0** dans le cœur applicatif. Le nouveau commit corrige correctement le CLI d'upgrade transactionnel et ajoute un durcissement systemd intéressant.

En revanche, cette passe révèle un **nouveau défaut important du déploiement bare-metal**, ainsi qu'une régression de version. Les deux problèmes de ma passe précédente — propagation incomplète des variables Docker et import legacy `--allow-unsafe-legacy` — sont toujours présents.

| Priorité     | Problème                                                                | 2.0.17                  |
| ------------ | ----------------------------------------------------------------------- | ----------------------- |
| 🔴 **P1**    | Installation systemd livrée incohérente avec `production.ini` et `.env` | **Nouveau**             |
| 🟠 **P1**    | Variables de configuration non transmises par Compose                   | Toujours présent        |
| 🟠 **P1/P2** | `--allow-unsafe-legacy` autorise certaines URL techniquement invalides  | Toujours présent        |
| 🟠 **P1**    | Un `UPDATE` SQLite par redirection par défaut                           | Toujours présent        |
| 🟠 **P1**    | `GET /?url=` créateur reste activé                                      | Risque assumé           |
| 🟡 **P2**    | `2.0.17` dans le paquet mais `__version__ = 2.0.16`                     | **Nouvelle régression** |
| 🟡 P2        | `/healthz` divulgue/compte le nombre de liens                           | Présent                 |
| 🟡 P2        | `main` non protégée et commits non signés                               | Présent                 |
| 🟢           | Validation URL/IDNA/IP/CORS/rate limiter                                | Bon état                |

### 1. Nouveau P1 : le déploiement systemd livré ne peut pas utiliser correctement le layout documenté

La documentation recommande :

```text
/srv/urlshortener/
├── app/
├── var/
└── etc/
    ├── production.ini
    └── .env
```

L'unité nouvellement ajoutée lance bien :

```ini
ExecStartPre=... urlshortener.upgrades /srv/urlshortener/etc/production.ini
ExecStart=... pserve /srv/urlshortener/etc/production.ini

ProtectSystem=strict
ReadWritePaths=/srv/urlshortener/var
```

Mais `production.ini` contient :

```ini
sqlalchemy.url = sqlite:///%(here)s/var/urlshortener.sqlite
```

Avec le fichier situé dans :

```text
/srv/urlshortener/etc/production.ini
```

`%(here)s` vaut `/srv/urlshortener/etc`.

La base devient donc :

```text
/srv/urlshortener/etc/var/urlshortener.sqlite
```

et **pas** :

```text
/srv/urlshortener/var/urlshortener.sqlite
```

Or systemd n'autorise en écriture que :

```text
/srv/urlshortener/var
```

Avec `ProtectSystem=strict`, `/srv/urlshortener/etc/var` n'est pas writable.

#### Conséquence

Une installation suivant exactement la documentation risque de mourir dans :

```text
ExecStartPre
```

lors de la création/ouverture SQLite.

C'est d'autant plus important que le commit 2.0.17 a précisément pour objectif de rendre ce chemin de démarrage fiable.

#### Correction recommandée

Dans le `production.ini` installé pour systemd :

```ini
sqlalchemy.url = sqlite:////srv/urlshortener/var/urlshortener.sqlite
```

ou mieux utiliser explicitement :

```text
SQLALCHEMY_URL=sqlite:////srv/urlshortener/var/urlshortener.sqlite
```

Mais cela mène au second problème.

---

### 2. Le `.env` bare-metal documenté n'est vraisemblablement jamais chargé

La documentation place :

```text
/srv/urlshortener/etc/.env
```

Mais l'unité systemd ne contient aucun :

```ini
EnvironmentFile=/srv/urlshortener/etc/.env
```

L'application essaie elle-même de trouver `.env` avec :

```python
find_dotenv(usecwd=True)
```

La nouvelle unité utilise :

```ini
WorkingDirectory=/srv/urlshortener
```

alors que `.env` est dans un **sous-répertoire** `etc/`.

`find_dotenv()` remonte les parents ; il ne descend pas chercher dans `etc/`.

Donc :

```text
/srv/urlshortener/etc/.env
```

ne sera pas trouvé depuis :

```text
/srv/urlshortener
```

La documentation contient en plus une autre unité systemd avec :

```ini
WorkingDirectory=/srv/urlshortener/app
```

Il y a donc désormais **deux unités systemd différentes dans le dépôt**.

#### Correction propre

Je ne compterais pas sur `python-dotenv` pour systemd.

Utilise directement :

```ini
EnvironmentFile=/srv/urlshortener/etc/.env
```

puis :

```ini
WorkingDirectory=/srv/urlshortener/app
```

Cela rend explicite le contrat d'exploitation et évite toute dépendance au cwd pour des secrets/configurations.

---

### 3. Nouvelle régression : la version est à nouveau incohérente

Le commit modifie :

```toml
version = "2.0.17"
```

mais le code actuel contient encore :

```python
__version__ = "2.0.16"
```

Donc les logs vont annoncer :

```text
urlshortener 2.0.16 ready
```

alors que le paquet installé est 2.0.17.

Ce n'est pas une faille de sécurité, mais après les problèmes de traçabilité des premières versions, je mettrais un test systématique :

```python
from importlib.metadata import version
import urlshortener

assert urlshortener.__version__ == version("urlshortener")
```

Encore mieux : supprimer `__version__` codé en dur et faire :

```python
from importlib.metadata import version

__version__ = version("urlshortener")
```

Une seule source de vérité.

---

### 4. Le problème Docker de la passe précédente reste entier

Compose transmet :

```text
URLSHORTENER_BASE_URL
URLSHORTENER_CODE_LENGTH
URLSHORTENER_BLOCK_PRIVATE_TARGETS
URLSHORTENER_ENABLE_LEGACY_GET
URLSHORTENER_BLOCKED_HOSTS
URLSHORTENER_THROTTLE_MAX
URLSHORTENER_THROTTLE_WINDOW
URLSHORTENER_CORS_ORIGINS
...
```

mais toujours pas notamment :

```text
URLSHORTENER_COUNT_HITS
URLSHORTENER_THROTTLE_MAX_READS
URLSHORTENER_MAX_URL_LENGTH
URLSHORTENER_CODE_MAX_ATTEMPTS
URLSHORTENER_DEFAULT_SCHEME
URLSHORTENER_ALLOWED_SCHEMES
```

La documentation dit pourtant explicitement que ces variables existent.

Cela signifie notamment que :

```env
URLSHORTENER_COUNT_HITS=false
```

dans le `.env` Docker ne permet toujours pas d'arrêter les écritures SQLite sur chaque redirect.

**Toujours P1.**

---

### 5. `--allow-unsafe-legacy` reste incorrectement permissif

Le code n'a pas changé.

Dès que :

```python
allow_unsafe
```

est vrai :

```python
if allow_unsafe:
    return None, False
```

et `normalise_url()` n'est plus appelée.

Cela autorise toujours comme « policy override » des choses qui ne sont pas de simples décisions de politique, par exemple :

```text
http://example.org:99999/
```

Un port invalide devrait être **toujours refusé**.

Je maintiens ma recommandation de distinguer :

**Non contournables :**

```text
invalid host
invalid port
credentials
control characters
reserved/bad code
javascript/data/vbscript
```

**Contournables explicitement pour compatibilité :**

```text
private target
blocked host
URL trop longue
éventuellement ancien schéma fonctionnel
```

---

### 6. L'écriture sur chaque redirect reste le principal vecteur de charge applicative

Toujours :

```ini
urlshortener.count_hits = true
```

Donc chaque visite d'un code connu déclenche un `UPDATE`.

Aucun changement dans ce commit ne concerne ce problème.

Je recommande toujours pour l'instance publique :

```ini
urlshortener.count_hits = false
```

puis statistiques depuis nginx ou un compteur asynchrone.

---

### 7. Le GET legacy reste volontairement ouvert

Toujours :

```ini
urlshortener.enable_legacy_get = true
```

Le choix de compatibilité avec l'ancien client est documenté et raisonnable temporairement, mais ses propriétés restent mauvaises :

```text
GET avec effet de bord
URL cible dans la query string
création déclenchable par une ressource externe
```

Pas de nouveau constat ici.

---

### 8. Supply-chain : inchangé

`main` est toujours :

```text
protected: false
```

et le nouveau commit est :

```text
verified: false
reason: unsigned
```

Le connecteur GitHub ne me remonte par ailleurs **aucun statut CI associé au HEAD actuel**. Le message de commit indique « 486 tests », mais je ne peux donc pas considérer depuis GitHub que les trois workflows sont effectivement obligatoires ou validés sur ce SHA.

C'est maintenant probablement le principal manque de gouvernance du dépôt.

---

## Bilan 2.0.17

Le cœur sécurité reste **bon**. Les corrections importantes des passes précédentes sont toujours là : URL canonicalisées comme les navigateurs, IP alternatives filtrées, IDNA UTS #46, API JSON-only, protection `Sec-Fetch-Site`, rate limiter O(1), `/64` IPv6, limites HTTP, proxy correctement traité, secrets Docker mieux protégés.

Mais je corrigerais **avant d'annoncer la 2.0.17 comme release opérationnelle** :

1. **réparer l'unité systemd + le chemin SQLite + le chargement de `.env`** ;
2. **corriger la propagation de toutes les variables dans Compose** ;
3. **corriger `--allow-unsafe-legacy`** ;
4. remettre `__version__` en cohérence, idéalement avec une seule source de vérité ;
5. ensuite traiter `count_hits`, le GET legacy et la protection de `main`.

Le point le plus urgent de cette nouvelle passe est donc assez paradoxal : **le code de l'upgrade 2.0.17 est meilleur, mais l'environnement systemd nouvellement livré autour de lui est actuellement incohérent avec la configuration qu'il doit utiliser.**
