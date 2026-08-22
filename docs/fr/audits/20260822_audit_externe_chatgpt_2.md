# Audit de sécurité externe — seconde passe, 22 août 2026

**Objet** : `michaellaunay/urlshortener` 2.0.10.
**Auditeur** : externe (ChatGPT), à la demande de Michaël Launay.
**Passe précédente** :
[audit externe du 22 août](20260822_audit_externe_chatgpt.md), sur la
2.0.0.
**Méthode déclarée** : analyse statique, complétée par des tests ciblés.
**Verdict** : « globalement solide », trois points à corriger avant une
exposition publique importante. Aucun des défauts structurels de la
première passe ne subsiste.

## Provenance et réserves

Ce document est le **versement** de l'audit reçu, avec sa mise en
correspondance avec les trains. Conformément à la règle de ce
répertoire, la première passe n'a **pas** été retouchée : ce qu'elle
laissait ouvert est repris ci-dessous.

Deux réserves à porter au dossier :

- l'auditeur a travaillé sur le commit `8ec6081`, soit la **2.0.10**,
  donc un train avant la 2.0.11. Ce train ne touchait qu'à la
  documentation, aucun de ses constats n'en dépend ;
- ce SHA **n'existe plus**. L'historique a été réécrit le même jour pour
  donner un commit par train ; l'équivalent est `e0e5870`. Rien du
  contenu n'a changé à cette occasion, hormis la suppression de
  `.pytest_cache/`.

## La leçon de cette passe

Les trois vraies découvertes se ressemblent, et ressemblent à celles de
la première passe : ce sont des **canonicalisations et des hypothèses
de navigateur**. La première passe avait montré qu'une adresse s'écrit
de quatre façons ; celle-ci montre qu'un nom international s'encode de
deux façons, et qu'un formulaire n'est pas soumis aux mêmes règles
qu'un appel JSON.

## Correspondance constat → train

| Id | Constat | Train | État |
| --- | --- | --- | --- |
| D-01 | `str.encode("idna")` implémente IDNA2003 ; un navigateur suit UTS #46 non-transitionnel. `faß.de` était stocké `fass.de` là où un navigateur atteint `xn--fa-hia.de` — **deux domaines différents** | 0012 | Corrigé |
| D-02 | Un `POST` en `x-www-form-urlencoded` est une requête CORS simple : aucun préflight, donc créations depuis n'importe quelle page tierce, à l'adresse des visiteurs | 0013 | Corrigé |
| D-04 | Clé de limitation = adresse complète ; un abonné IPv6 possède un /64 entier, donc la limite ne limitait rien | 0014 | Corrigé |
| D-03 | Mémoire du limiteur bornée au train 0004, mais chaque nouvelle clé au plafond balayait 20 000 entrées, verrou tenu (0,83 ms mesurées) | 0014 | Corrigé |
| D-05 | `PyYAML` dans aucun verrou : les deux contrôles qui analysent le `docker-compose.yaml` sautaient partout, CI comprise | 0014 | Corrigé |
| D-06 | `GET /?url=` toujours actif par défaut | — | **Risque accepté**, mesuré (train 0010) |
| D-07 | Anciens codes de 1 à 3 caractères énumérables | — | **Risque accepté** ; non corrigeable sans tuer les liens de 2016 |
| D-08 | Chaque redirection fait un `UPDATE` sur un moteur mono-écrivain, sur un chemin jamais limité | — | **Décision en attente** |
| D-09 | `main` non protégée, commits non signés | — | **Décision en attente**, hors code |
| D-10 | `setuptools 81` | — | Exception confirmée, voir ci-dessous |

## Ce que cette passe a résolu pour nous

L'audit interne laissait l'avis `setuptools` en question ouverte, faute
de pouvoir l'évaluer. L'auditeur le nomme — **CVE-2026-59890** — et en
donne le périmètre : génération de distributions source sur APFS/HFS+
avec des noms Unicode normalisés différemment. Sans rapport avec un
conteneur Linux qui ne construit rien.

L'exception nominative de `pip-audit` passe donc du statut « je ne sais
pas » à celui d'**acceptation informée**. Elle reste datée et à revoir
à chaque publication de pyramid, qui épingle `setuptools<82`.

## Ce que les trains ont trouvé et que l'audit n'avait pas vu

À noter, parce que c'est la troisième fois de ce projet qu'une
vérification mal lue vaut une vérification absente :

- **D-02, seconde moitié.** Le formulaire et l'API utilisaient deux
  fonctions de clé de limitation différentes, donc alterner entre les
  deux doublait le quota. Trouvé en unifiant l'identité au train 0014.
- **D-01, seconde moitié.** La liste noire souffrait du même écart
  IDNA : une entrée écrite `faß.de` bloquait `fass.de`, un domaine
  différent, et laissait passer celui qu'on voulait interdire. La
  déduplication était cassée de la même façon.
- **Une régression de ma part**, corrigée au train 0009 : `bandit`
  sortait en 1 depuis le train 0004 sur un faux positif B104, et je
  lisais sa sortie à travers un motif assez lâche pour paraître vert.

## Ce qui reste ouvert

Trois décisions, aucune n'étant un correctif :

1. **D-08 — `count_hits` par défaut.** Chaque redirection est une
   écriture SQLite, sur le chemin que la documentation déclare jamais
   limité : un seul code valide connu suffit à en générer autant qu'on
   veut. Passer à `false` retire une fonctionnalité ; les journaux
   nginx donnent la même information. Recommandation : `false` en
   production, `true` en développement.
2. **D-06 — date de coupure de `GET /?url=`.** Le train 0010 a rendu la
   décision mesurable (en-tête `Deprecation`, une ligne de journal par
   usage). Il manque la date.
3. **D-09 — protection de `main`.** Rendre les trois workflows
   obligatoires avant modification, ajouter un `schedule:` hebdomadaire
   pour que `pip-audit` tourne même sans développement, signer les
   commits et les étiquettes.

Restent aussi, depuis les passes précédentes : `read_only: true` sur le
conteneur, à valider au premier *smoke* réel, et l'écran d'avertissement
avant redirection, si tu le souhaites.
