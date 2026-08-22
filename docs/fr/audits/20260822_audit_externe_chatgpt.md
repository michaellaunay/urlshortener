# Audit de sécurité externe — 22 août 2026

**Objet** : `michaellaunay/urlshortener` 2.0.0.
**Auditeur** : externe (ChatGPT), à la demande de Michaël Launay.
**Méthode déclarée** : analyse statique, complétée par des tests ciblés
sur les fonctions de validation. L'auditeur signale n'avoir pas pu
exécuter `bandit`, `pip-audit` ni `ruff` faute d'accès réseau dans son
environnement.
**Verdict** : quatre P0, quatre P1, cinq P2, un P3. Aucune vulnérabilité
d'exécution de code, aucune injection SQL, aucun secret en dur.

## Provenance et réserve

Ce document est le **versement** de l'audit reçu, avec sa mise en
correspondance avec les trains de correctifs. Le texte de l'auditeur
n'est pas reproduit intégralement ici ; ses constats sont repris avec
leurs identifiants, et le lecteur qui veut la formulation d'origine la
trouvera dans les transcrits.

Une réserve à porter au dossier : l'auditeur annonce **127 tests** là où
le dépôt en comptait 170 au moment de son passage. Il n'a donc
probablement pas travaillé sur l'arbre exact. Cela n'invalide aucune de
ses découvertes — toutes ont été **reproduites** contre le code réel
avant d'être corrigées — mais cela veut dire que son verdict global
porte peut-être sur un état légèrement différent.

## Ce que l'audit a trouvé que l'audit interne n'avait pas vu

Trois découvertes, et elles se ressemblent : ce sont toutes des
**canonicalisations manquantes**. L'audit interne du même jour avait
cherché des failles ; celui-ci a cherché des écritures différentes d'une
même chose. C'est la leçon la plus utile du passage.

| Id | Constat | Train | État |
| --- | --- | --- | --- |
| C-02 | `block_private_targets` ne tenait pas : `2130706433`, `127.1`, `0x7f000001`, `0177.0.0.1` acceptés, tous `127.0.0.1` pour un navigateur | [0002](../../../CHANGES.txt) | Corrigé |
| C-08 | `blocked_hosts` comparait l'hôte brut : `bücher.example` passait une liste contenant `xn--bcher-kva.example` | 0002 | Corrigé |
| C-01 | Redirection ouverte dans `/locale/` : `/\evil.example` passait la garde de chaîne | 0003 | Corrigé |
| C-16 | Port non validé — et, dans mon correctif 2.0.1, une `ValueError` non rattrapée, donc un 500 | 0002 | Corrigé |
| C-04 | Corps de requête à 1 Gio par défaut dans waitress, conteneur à 512 Mo | 0005 | Corrigé |
| C-06 | Recette nginx fautive deux fois : `location = /` n'hérite pas des `proxy_set_header`, et `limit_req` ne couvrait pas `/api/v1/shorten` | 0004 | Corrigé |
| C-07 | `URLSHORTENER_TRUSTED_PROXY` non transmis par compose ; `trusted_proxy = 127.0.0.1` faux en conteneur | 0004 | Corrigé |
| C-09 | `GET /?url=` : GET qui écrit, cible dans le journal d'accès | 0010 | Rendu décidable |
| C-10 | L'import héritait d'une fraction de la politique ; un code `healthz` s'importait en lien injoignable | 0006 | Corrigé |
| C-12 | `backup.sh` sans `umask`, et copie en `:memory:` sous `mem_limit: 512m` | 0004 | Corrigé |
| C-14 | Codes de 7 caractères (41,7 bits) | 0007, 0008 | 11 caractères |
| C-15 | CORS annoncé sans réponse au préflight `OPTIONS` | 0009 | Corrigé |
| C-17 | Configuration impossible acceptée au démarrage | 0009 | Corrigé |
| C-03 | Fuite mémoire du limiteur | — | Déjà corrigé en 2.0.1 (S-04) |
| C-11 | Identifiants SQL dans `runtime.ini` | — | Déjà corrigé en 2.0.1 (S-07) |
| C-13 | API de consultation bavarde (`hits`, `created_at`, `links`) | — | **Risque accepté** par Michaël |

## Une découverte trouvée en corrigeant, pas dans l'audit

Deux défauts sont apparus **pendant** les trains, et méritent d'être
notés parce qu'aucun des deux audits ne les avait vus :

- **La pile compose ne servait rien.** `production.ini` écoute sur
  `localhost:5123`, injoignable en conteneur, et `URLSHORTENER_LISTEN`
  n'était transmis par rien. Trouvé en instrumentant C-07 (train 0004).
- **Le job qualité échouait depuis le train 0004.** Mon propre correctif
  comparait une adresse au littéral `"0.0.0.0"`, que bandit lit comme
  une écoute sur toutes les interfaces (B104). Je ne l'avais pas vu
  parce que je lisais la sortie à travers un `grep` assez lâche pour
  matcher la mauvaise ligne. Corrigé au train 0009.

Le second est le plus instructif : **une porte de qualité mal lue vaut
une porte absente.**

## Désaccord assumé

L'auditeur recommande `enable_legacy_get = false` par défaut sur une
installation neuve. Le train 0010 le laisse à **true** : KuneAgi appelle
ce point d'entrée, et la première promesse du projet est que rien
d'écrit contre le service de 2016 ne casse. Ce qui a été livré est la
capacité de couper, plus un en-tête `Deprecation`, un `Link` vers le
successeur et une ligne de journal par usage — de quoi transformer la
coupure en décision datée plutôt qu'en pari.

## Ce qui reste ouvert

- **C-13** — API bavarde : décision de Michaël, risque accepté.
- **S-12** (audit interne) — redirection ouverte par nature, pas
  d'écran d'avertissement. Décision à prendre.
- **S-06** — `read_only: true` sur le conteneur, à valider au premier
  *smoke* réel.
- **S-08** — l'exception `pip-audit` sur setuptools, impossible à lever
  tant que pyramid 2.1 épingle `setuptools<82`.
