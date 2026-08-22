# Audit de sécurité interne — 22 août 2026

**Objet** : `michaellaunay/urlshortener` 2.0.0, réécriture de
`ecreall/urlshortener` (2016).
**Auditeur** : interne (moi-même, sur mon propre code — voir la réserve
en fin de chapeau).
**Méthode** : lecture adversariale du code, sondes contre le service
réellement démarré sur une socket, `ruff`, `bandit -ll`, `pip-audit`
sur le verrou d'exécution.
**Verdict** : **une découverte haute**, trois moyennes, six basses,
quatre risques assumés. Toutes les découvertes corrigeables l'ont été
dans ce même passage, chacune avec un test de non-régression
(`tests/test_audit_20260822.py`), démonstration rouge/vert faite.

## Chapeau — ce que vaut cet audit

C'est un **auto-audit**. Il trouve des défauts que j'ai moi-même
introduits, ce qui est déjà utile, mais il ne trouvera pas ceux dont je
partage l'angle mort avec le code. Deux zones méritent un regard
extérieur : la validation d'URL (S-01 montre qu'elle en avait besoin) et
la chaîne de déploiement. Le point de comparaison honnête, c'est la
série d'audits externes d'AlirPunkto : elle a régulièrement trouvé ce
que je n'avais pas vu, y compris des régressions de mon fait.

Réserve supplémentaire : l'image Docker **n'a pas été construite** dans
l'environnement où cet audit a été mené. Tout ce qui concerne le
conteneur est donc de la lecture, pas de l'observation ; c'est signalé
au cas par cas (S-06).

## Ce que le service de 2016 faisait, pour mémoire

L'audit s'ouvre là-dessus parce que les tests de la 2.0 sont écrits
contre ces quatre défauts, et qu'ils décrivent le point de départ :

1. requêtes SQL construites en `.format()` sur l'entrée utilisateur ;
2. aucune validation de cible — `javascript:`, `data:`, `file:`,
   `http://127.0.0.1:6543/admin` acceptés puis servis en `Location:` ;
3. codes séquentiels, corpus entier énumérable ;
4. Bootstrap et Font Awesome tirés d'un CDN tiers à chaque affichage.

Tous les quatre sont traités dans la 2.0.0 et verrouillés par des tests.
Ce ne sont donc **pas** des découvertes de cet audit ; ce qui suit l'est.

---

## S-01 — Cible non-ASCII : 500 permanent, ou redirection mutilée

**Gravité : haute.** Corrigé.

### Le fait

Un en-tête HTTP est de l'ASCII. WebOb transmet l'en-tête à waitress, qui
fait `res.encode("latin-1")` sur tout le bloc. Une cible portant des
caractères non-ASCII donnait donc l'un de deux résultats, tous deux
mauvais :

- **dans la plage latin-1** (`https://münchen.example/café`) : l'UTF-8
  était ré-encodé en latin-1 et le visiteur partait vers une adresse
  **mutilée** — pas celle qui avait été raccourcie ;
- **hors plage latin-1** (japonais, cyrillique, emoji) :
  `UnicodeEncodeError`, donc **500 avec pile d'appels à chaque visite**,
  définitivement, sur un lien qui avait pourtant été accepté à la
  création.

### La preuve

Contre le service réellement démarré :

```
japanese       redirect -> HTTP/1.1 500 Internal Server Error
emoji          redirect -> HTTP/1.1 500 Internal Server Error
cyrillic host  redirect -> HTTP/1.1 500 Internal Server Error

UnicodeEncodeError: 'latin-1' codec can't encode character '\U0001f517'
  File "waitress/task.py", line 283, in build_response_header
    return res.encode("latin-1")
```

Et pour la plage latin-1, les octets sur le fil :

```
Location: https://m\xfcnchen.example/caf\xe9      (pas de l'ASCII)
```

### Pourquoi ça comptait

Trois conséquences, dans l'ordre de gravité :

1. **Lien empoisonné à vie.** La création réussissait, la ligne était
   rangée, et c'est la *lecture* qui échouait. Un lien diffusé, puis
   mort à chaque clic, sans que personne ne sache pourquoi.
2. **Redirection vers une autre destination** dans le cas latin-1. Pour
   un raccourcisseur, envoyer ailleurs que là où on a promis est le
   défaut le plus grave qui soit, même sans intention malveillante.
3. **Inondation de journal par un anonyme.** Créer un lien vers une URL
   contenant un emoji, puis le marteler, produit une pile d'appels par
   requête.

Le collage de KuneAgi rend le cas concret et pas théorique : les URL
tapées ou collées depuis une barre d'adresse arrivent souvent en UTF-8
brut, et les titres d'articles francophones ou d'autres langues de
l'Union en portent.

### Le correctif

Une fonction `to_wire_url()` : IDNA pour l'hôte, encodage-pourcent pour
le chemin, la requête et le fragment, `%` laissé sûr pour qu'une URL
déjà encodée ne le soit pas deux fois (`%20` reste `%20`, il ne devient
pas `%2520`).

Appliquée à **deux** endroits, et c'est le point important :

- à la création, pour que les lignes neuves soient rangées sous forme
  transmissible ;
- **au moment de la redirection**, parce que les lignes importées du
  fichier de 2016 le sont *verbatim* et n'ont jamais traversé la
  création. Sans cette seconde application, l'import aurait pu déposer
  des lignes mortelles.

C'est exactement la leçon des greps de migration incomplets : corriger
le chemin qu'on a en tête et pas tous les appelants.

**Tests** : `test_s01_*` (5 cas). Sans le correctif : 6 échecs.

---

## S-02 — Les codes hérités sont énumérables

**Gravité : moyenne.** Atténué, et **risque résiduel assumé**.

Les codes de 2016 font un à trois caractères et sont **séquentiels**
(`0`, `1`, `2`, … `4f2`). Sonde : trois cibles retrouvées en seize
essais sur `/api/v1/links/{code}`.

```
enumerated in 16 guesses:
  https://secret.example/report-0
  https://secret.example/report-1
  https://secret.example/report-2
```

Il faut le dire nettement : **cela ne peut pas être corrigé**. Les codes
courts sont repris tels quels, parce que les réattribuer tuerait les
liens diffusés — c'est le contrat central de la migration. Et l'API
n'est pas le vrai vecteur : la redirection elle-même révèle la cible,
elle est publique par définition, et elle ne sera jamais limitée puisque
c'est la fonction du service.

Ce qui est fait : `urlshortener.throttle_max_reads` (0 par défaut)
permet de freiner l'énumération en masse sur l'API JSON. Ce qui doit
être dit aux utilisateurs : **un lien court n'a jamais été un secret**,
et les liens de 2016 le sont moins que les autres. Les codes neufs font
sept caractères tirés de `secrets`, ce qui ferme le sujet pour la suite.

**Tests** : `test_s02_*`.

---

## S-03 — L'import « en lecture seule » ne l'était pas toujours

**Gravité : moyenne.** Corrigé.

`read_legacy_rows` construisait `"file:%s?mode=ro" % path`. Un chemin
contenant `?` — ou forgé en `sauvegarde.db?mode=rwc` — faisait basculer
le reste en **paramètres d'URI**, et la garantie de lecture seule
disparaissait sans un mot.

L'enjeu n'est pas une attaque : c'est que l'outil se met alors à écrire
dans le fichier même qui sert de **retour arrière** à l'exploitant, au
moment précis d'une migration. Le chemin est désormais rendu absolu puis
échappé, de sorte qu'un `?` reste un caractère de nom de fichier.

**Test** : `test_s03_a_path_containing_a_question_mark_stays_read_only`.

---

## S-04 — Le limiteur pouvait devenir le déni de service

**Gravité : moyenne.** Corrigé.

La clé du limiteur est l'adresse cliente, donc influencée par
l'attaquant — et entièrement contrôlée par lui si la configuration de
proxy est fausse (voir S-05). Le dictionnaire n'avait pas de plafond :
le ménage ne retirait que les files vides. Un balayage depuis un grand
nombre d'adresses le faisait croître jusqu'à la mort du processus. Un
limiteur qui devient l'épuisement qu'il devait émousser.

Plafond dur de 20 000 clés, expiration d'abord, éviction de la plus
ancienne ensuite. L'attaquant peut se racheter un budget — c'est à quoi
sert la limite du proxy — mais il ne peut plus épuiser la mémoire.

**Tests** : `test_s04_*` (5 000 adresses distinctes, ≤ 100 clés
conservées avec un plafond de 100).

---

## S-05 — Le nombre de sauts de proxy était implicite

**Gravité : basse.** Corrigé.

`production.ini` posait `trusted_proxy` mais pas `trusted_proxy_count`.
Waitress lit l'adresse à cette position **depuis la droite** de
`X-Forwarded-For` ; avec un seul proxy, le défaut de 1 est juste, et la
sonde le confirme (la tentative d'usurpation depuis la loopback n'a rien
donné). Mais le jour où un CDN est mis devant sans passer ce nombre à 2,
c'est la valeur fournie par le **visiteur** qui atterrit à cette
position, et la clé de limitation devient contrôlée par l'attaquant.

Un nombre, deux proxys, panne silencieuse. Il est maintenant explicite,
avec le raisonnement écrit à côté.

**Test** : `test_s05_production_declares_its_trusted_proxy_count`.

---

## S-06 — Durcissement du conteneur : partiel, et je le dis

**Gravité : basse.** Partiellement appliqué.

`cap_drop: ALL` est ajouté : waitress écoute sur un port haut sous un
compte non privilégié et n'a besoin d'aucune capability.

`read_only: true` (avec un tmpfs pour `/tmp`) est la marche suivante et
**n'est pas activé**. Raison assumée : l'image n'a pas été construite
ici, donc ce drapeau n'a pas été éprouvé contre un vrai démarrage.
Livrer un durcissement non testé qui casse le premier lancement est pire
que ne pas le livrer — c'est précisément le genre de « vert supposé »
qui a coûté cher ailleurs. À valider dans le workflow *smoke*, puis à
activer.

---

## S-07 — Le `runtime.ini` dérivé pouvait porter un mot de passe

**Gravité : basse.** Corrigé.

`apply_server_overrides.py` écrit `var/runtime.ini` **sur le volume de
données**, et ce fichier peut contenir une URL PostgreSQL avec son mot
de passe. Il héritait de l'umask. Il est désormais créé en 0600 — créé
ainsi dès l'ouverture, et non par un `chmod` postérieur qui laisserait
une fenêtre pendant laquelle il est lisible.

**Test** : `test_s07_the_runtime_ini_is_created_0600`.

---

## S-08 — Une CVE de dépendance impossible à corriger

**Gravité : basse.** Exception documentée.

`pip-audit` signale PYSEC-2026-3447 sur `setuptools` 81.0.0. Deux points
méritent d'être posés :

- `setuptools` est ici une dépendance **d'exécution** : pyramid,
  zope-deprecation et zope-sqlalchemy la déclarent via `pkg_resources`,
  elle est donc dans l'image ;
- l'avis est corrigé en 83.0.0, mais **pyramid 2.1 épingle
  `setuptools<82`**. La montée est impossible sans quitter pyramid 2.1.
  Tentative faite, résolution refusée :

```
ResolutionImpossible: SpecifierRequirement('setuptools<85,>=83')
                      vs SpecifierRequirement('setuptools<82') from pyramid-2.1
```

Le job qualité porte donc **une** exception nommée et datée
(`--ignore-vuln PYSEC-2026-3447`), avec sa justification dans le
fichier. Tout autre avis fait toujours échouer le job. À revoir à chaque
publication de pyramid.

Je n'ai pas évalué l'exploitabilité de cet avis dans ce contexte : je
n'en ai pas la description ici. C'est une **décision qui te revient**, et
non un point clos.

**Test** : `test_s08_the_pip_audit_exception_is_written_down` — une
exception non justifiée dans le fichier fait échouer la suite.

---

## S-09 — Chaque 404 comptait toute la table

**Gravité : basse.** Corrigé.

La page 404 affichait le nombre de liens, donc exécutait un agrégat sur
toute la table. Un énumérateur produit un échec par essai : chaque
échec coûtait un `COUNT(*)`. Et le gestionnaire de 404 tombait lui-même
quand la base était indisponible — la page d'erreur en panne au moment
où on en a besoin.

**Test** : `test_s09_the_404_page_does_not_count_the_links`.

---

## S-10 — Un GET qui écrit, sans jeton

**Risque assumé.** Documenté.

`GET /?url=...` crée une ligne. N'importe quelle page tierce peut donc
faire créer un lien par ses visiteurs (`<img src="…/?url=…">`), sans
jeton et à leur adresse IP — ce qui répartit aussi la limitation.

Conservé volontairement : c'est le point d'entrée de 2016, KuneAgi
l'utilise, et le casser casserait l'intégration existante. La création
est de toute façon anonyme et publique ; il n'y a aucune action
privilégiée à protéger. **Cela change avec le SSO Keycloak** : dès
qu'une action est liée à une identité, le jeton devient obligatoire
(chapitre 07).

---

## S-11 — Le paquet reconfigurait les moteurs des autres

**Gravité : basse.** Corrigé.

Les pragmas SQLite étaient attachés à la **classe** `Engine` de
SQLAlchemy, à l'import. Importer `urlshortener` forçait donc WAL et
l'intégrité référentielle sur **tout autre moteur du même processus**.
Une bibliothèque ne reconfigure pas des connexions qu'on ne lui a pas
confiées. Le listener est maintenant posé sur notre moteur.

**Test** : `test_s11_importing_the_package_does_not_reconfigure_other_engines`.

---

## S-12 à S-15 — Risques assumés, écrits plutôt que corrigés

**S-12 — redirection ouverte.** C'est la fonction du produit. Aucun
écran d'avertissement n'est affiché avant de partir. Un raccourcisseur
public finit par servir un lien d'hameçonnage : ce qu'il faut préparer,
c'est une **procédure de retrait** (`DELETE FROM links WHERE code = ?`),
pas un filtre magique. Décision à prendre : interstitiel ou non.

**S-13 — pas de résolution DNS.** Une résolution faite à la création ne
dit rien de l'endroit où le nom pointera à la redirection ; la payer
achèterait un faux sentiment de sécurité. Seuls les littéraux numériques
privés sont refusés. Le *rebinding* DNS n'est donc pas couvert, et c'est
testé explicitement (`test_a_name_is_never_resolved`).

**S-14 — amplification d'écriture.** Chaque redirection est un `UPDATE`
du compteur de visites, sans limitation. Marteler un lien sérialise des
écritures SQLite (200 redirections : 0,75 s au banc). Atténuations
disponibles : `count_hits = false`, ou `limit_req` au proxy. Non traité
en code : limiter la redirection reviendrait à limiter le service.

**S-15 — `curl` dans l'image d'exécution**, uniquement pour le
`HEALTHCHECK`. Surface superflue ; une sonde en python du venv ferait
la même chose sans paquet supplémentaire. Non corrigé pour ne pas
toucher au Dockerfile sans pouvoir reconstruire l'image ici.

---

## Ce que je n'ai pas pu vérifier

À dire, parce qu'un audit qui ne borne pas son périmètre ment par
omission :

- **l'image n'a pas été construite** : Dockerfile, entrypoint et compose
  sont audités par lecture et par tests structurels, pas par
  observation ;
- **aucun test de charge**, aucune mesure de concurrence réelle sur
  SQLite au-delà des 200 redirections du banc ;
- **pas de revue cryptographique** — il n'y a pas de cryptographie ;
- **pas de revue des traductions** par des locuteurs (un message
  d'erreur mal traduit peut induire un utilisateur en erreur, ce qui est
  un problème de sûreté, pas seulement de qualité).

## État après ce passage

187 tests verts, `ruff` propre, `bandit -ll` sans découverte,
`pip-audit` vert avec l'unique exception nommée. Les 17 tests de
`tests/test_audit_20260822.py` échouent tous sur le code d'avant —
démonstration rouge/vert faite pour S-01 (6 échecs).

## Décisions qui te reviennent

1. **S-08** : accepter l'exception `setuptools`, ou quitter pyramid 2.1.
2. **S-12** : écran d'avertissement avant redirection, oui ou non ?
3. **S-02** : faut-il activer `throttle_max_reads` en production, et à
   quelle valeur, sachant que KuneAgi appellera l'API depuis une seule
   adresse ?
4. **S-06** : valider `read_only: true` au prochain *smoke*, puis
   l'activer.
5. Un **regard extérieur** sur la validation d'URL. S-01 était dans mon
   propre code, écrit le jour même, avec des tests que je croyais
   complets.
