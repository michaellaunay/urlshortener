# 07 — SSO Keycloak (itération suivante)

Rien de ce chapitre n'est implémenté. Il est écrit maintenant pour que
les décisions structurantes soient prises avant, et non après, le code.

## Le besoin

Aujourd'hui le service est entièrement anonyme : n'importe qui
raccourcit, personne n'administre. Il manque deux choses :

- une **administration** — lister, chercher, révoquer un lien
  (hameçonnage, erreur, demande de retrait) ;
- une **attribution** — savoir quel membre a créé quel lien, pour les
  liens créés depuis KuneAgi ou AlirPunkto.

Ces deux besoins ont la même réponse : le Keycloak déjà en place, celui
qui sert AlirPunkto et KuneAgi, avec les membres fédérés depuis LDAP.

## Ce qui est déjà en place pour l'accueillir

- Le service n'a **aucune session** aujourd'hui, donc rien à démonter.
- Les vues sont minces : les règles vivent dans `services.py`, qui ne
  connaît pas HTTP. Ajouter une identité n'y touche pas.
- `RESERVED_CODES` et `tests/test_routes.py` garantissent qu'ajouter
  `/admin` ne rendra pas injoignable un lien existant — à condition
  d'ajouter `admin` à la liste, ce que le test exige.

## Forme visée

Reprendre le greffon OIDC écrit pour KuneAgi (`novaideo/oidc_sso.py`) :
code d'autorisation, découverte `.well-known` mise en cache, `state` et
`nonce` à usage unique, validation `iss` / `aud` / `exp` / `nonce`,
recoupement du `sub` via UserInfo.

Principe déjà tenu dans les deux projets, à tenir ici : **les routes SSO
ne sont enregistrées que si `oidc_sso.*` est configuré**. Sans
configuration, le greffon est inerte et le service reste exactement ce
qu'il est aujourd'hui. Un déploiement qui n'a pas de Keycloak ne doit
rien voir changer.

## Décisions à prendre avant d'écrire une ligne

1. **La création reste-t-elle anonyme ?** Trois options :
   (a) anonyme comme aujourd'hui, l'authentification ne sert qu'à
   l'administration ; (b) authentification obligatoire, ce qui casse
   `GET /?url=` et donc l'intégration KuneAgi actuelle ; (c) anonyme
   avec quota, authentifié sans quota. **(c) semble le bon compromis, à
   confirmer.**

2. **Quel modèle de rôles ?** Un rôle `urlshortener-admin` dans
   Keycloak, ou une dérivation depuis les groupes AlirPunkto existants ?
   Le second évite un référentiel de plus, le premier reste lisible.

3. **Que stocke-t-on du créateur ?** Le `sub` OIDC est un pseudonyme
   stable et suffit à répondre « qui a créé ce lien ». Y adjoindre le
   courriel ou le pseudonyme ferait de la table un annuaire.
   **Recommandation : le `sub` seul, et rien d'autre**, avec une étape
   de schéma dédiée et une colonne nullable — les liens importés de 2016
   n'ont pas de créateur, et n'en auront jamais.

4. **Le CSRF devient obligatoire.** Dès qu'une action est liée à une
   identité, `POST /admin/...` doit porter un jeton. La question est de
   savoir si `POST /` anonyme en reste exempt (probablement oui,
   sinon les clients de 2016 cassent).

5. **La déconnexion.** Locale seulement, comme dans le greffon KuneAgi,
   ou déconnexion propagée à Keycloak ?

## Étapes prévues

1. Étape de schéma 2 : colonne `created_by_sub` nullable, index inclus.
2. Greffon OIDC inerte par défaut, routes `/oidcsso/login` et
   `/oidcsso/callback`.
3. Vues d'administration derrière un contrôle de rôle : liste, recherche
   par code ou par cible, révocation.
4. Journal des révocations — qui, quand, pourquoi. Une révocation sans
   trace est une panne indistinguable d'un incident.
5. Documentation bilingue et tests, dont un scénario bout en bout avec
   un Keycloak de test.

## Ce qui ne changera pas

La redirection reste anonyme, sans cookie, sans session : un visiteur
qui suit un lien court n'a pas à s'authentifier, et le service n'a pas à
savoir qui il est.
