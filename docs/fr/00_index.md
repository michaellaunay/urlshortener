# urlshortener — documentation

Raccourcisseur d'URL. Successeur de `ecreall/urlshortener` (2016),
réécrit en Pyramid 2 / SQLAlchemy 2, sous licence AGPL v3.

La documentation existe en deux langues, `docs/fr` et `docs/en`, qui
sont des miroirs : toute modification de l'une appelle la modification
de l'autre.

## Sommaire

| Chapitre | Contenu |
| --- | --- |
| [01 — Installation](01_installation.md) | Poser le service, en développement puis sur un serveur |
| [02 — API et routes](02_api.md) | Les points d'entrée, dont ceux hérités de 2016 |
| [03 — Internationalisation](03_i18n.md) | Le registre des langues, ajouter une langue |
| [04 — Docker et exploitation](04_docker.md) | Image, compose, sauvegardes, supervision |
| [05 — Migration depuis 2016](05_migration.md) | Reprendre `var/urls.db`, brancher KuneAgi |
| [06 — Sécurité](06_securite.md) | Ce qui est vérifié, ce qui ne l'est pas |
| [07 — SSO Keycloak (à venir)](07_sso_keycloak.md) | Feuille de route de l'itération suivante |
| [Audits](audits/README.md) | Audits de sécurité, datés et autoportants — un interne, un externe |

## En trois phrases

Le service accepte une adresse longue, en range une copie et rend un
code court ; il sert ensuite une redirection 302 pour ce code. La même
adresse rend toujours le même code. Tout le reste — les langues, la
base de données, le préfixe public des liens, les règles de refus —
est de la configuration.

## Ce qui vient de 2016 et ce qui a changé

Le contrat public est conservé : `GET /?url=`, `POST /`, `GET /<code>`
et l'alphabet des codes sont identiques, donc **aucun lien court déjà
diffusé ne meurt**. Sous ce contrat, tout a été refait : requêtes
paramétrées, validation des cibles, codes tirés au hasard, en-têtes de
sécurité, plus aucun appel à un CDN tiers.

Le détail exhaustif, écarts assumés compris, est dans `CHANGES.txt`.

## Conventions du dépôt

- Code et noms de fichiers en anglais ; documentation bilingue.
- Commits en anglais, à l'impératif.
- Livraisons sous forme de diff appliqué par `git apply`.
- Trois verrous de dépendances hachés : `requirements.lock` (exécution),
  `requirements-test.lock`, `requirements-quality.lock`.
- Toute modification d'une structure persistée **ajoute** une étape dans
  `urlshortener/upgrades.py`. Jamais de modification en place d'une
  étape déjà publiée.
