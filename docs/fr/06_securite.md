# 06 — Sécurité

Ce chapitre dit ce qui est vérifié, et surtout ce qui ne l'est pas. Un
raccourcisseur est un outil de redirection ouvert : sa surface, c'est
l'endroit où il envoie les gens.

## Ce que faisait le service de 2016

Quatre défauts, tous corrigés, tous cités parce qu'ils décrivent
exactement ce que les tests protègent aujourd'hui.

1. **Injection SQL.** Les requêtes étaient construites en `.format()` :
   `INSERT INTO WEB_URL (URL, NUM) VALUES ('{url}', '{num}')`. Une
   apostrophe dans l'URL suffisait. Tout passe désormais par des
   requêtes paramétrées via SQLAlchemy.
2. **Aucune validation de cible.** `javascript:alert(1)`,
   `data:text/html;base64,…`, `file:///etc/passwd`,
   `http://127.0.0.1:6543/admin` étaient acceptés, rangés, puis servis
   en `Location:`.
3. **Codes séquentiels.** Le compteur allait `0, 1, … 9, a, … z, A, …`.
   Connaître un code donnait le suivant ; le corpus entier s'énumérait
   en quelques milliers de requêtes.
4. **CDN tiers.** La page tirait Bootstrap et Font Awesome de maxcdn à
   chaque affichage, ce qui indiquait à un tiers qui consultait quoi.

## Ce qui est vérifié aujourd'hui

**Schéma** : liste blanche `http` / `https`. Tout le reste est refusé.

**Autorité** : pas d'identifiants (`https://votre-banque.example@méchant.test/`
— le visiteur lit avant l'arobase, le navigateur va après). Syntaxe de
nom d'hôte contrôlée, forme IDNA acceptée, littéral IPv6 validé.

**Caractères de contrôle** : refusés à l'entrée. Un retour chariot dans
une URL stockée devient une injection d'en-tête le jour où elle est
écrite dans `Location:`.

**Hôte canonique** : une seule écriture de l'hôte est calculée, puis
tous les contrôles portent sur elle et c'est elle qui est stockée.
L'encodage international suit **UTS #46 non-transitionnel**, c'est-à-dire
ce que fait un navigateur, et non le codec `idna` intégré à Python, qui
implémente RFC 3490 (IDNA2003). Les deux divergent sur des noms qui
existent : `faß.de` donne `fass.de` avec le codec et `xn--fa-hia.de`
dans un navigateur — deux domaines, potentiellement deux propriétaires.
Pour un service dont la promesse entière est « tu arrives là où tu as
demandé », résoudre un hôte autrement que le navigateur qui suivra le
lien n'est pas une nuance.
Cela ferme deux contournements trouvés par l'audit externe : les
écritures alternatives d'une IPv4 (`2130706433`, `127.1`,
`0x7f000001`, `0177.0.0.1` sont toutes `127.0.0.1` pour un navigateur,
et `ipaddress` n'en connaît qu'une), et les deux orthographes d'un nom
international (`bücher.example` et `xn--bcher-kva.example` sont le même
nom DNS). Un hôte à l'allure numérique qui n'est pas une adresse
valable (`1.2.3.4.5`) est refusé : un navigateur le rejette, le stocker
reviendrait à fabriquer un lien mort.

**Adresses privées** : refusées par défaut, sur la forme canonique.
Le critère est `is_global` — c'est-à-dire « joignable sur l'internet
public » — plutôt qu'une liste de propriétés tenue à la main, qui est
courte par construction. Cela couvre la loopback, `10/8`, `192.168/16`,
`169.254/16` (métadonnées cloud), `::1`, `localhost`, **et aussi** les
plages de documentation (`192.0.2/24`, `198.51.100/24`, `203.0.113/24`,
`2001:db8::/32`). `urlshortener.block_private_targets = false` lève la
garde pour un service purement interne.

**Port** : validé avant tout le reste. `parts.port` est une propriété
paresseuse qui lève sur `:99999` ou `:abc` ; la lire tardivement
transformait une saisie fautive en 500.

**Codes** : tirés de `secrets`, **onze caractères** par défaut — la
longueur d'un identifiant YouTube (`youtu.be/dQw4w9WgXcQ`). Soit
62¹¹ ≈ 5,2 × 10¹⁹ possibilités, 65,5 bits ; leur alphabet compte 64
symboles et le nôtre 62, les deux tiennent donc dans un demi-bit l'un de
l'autre. Collisions gérées par SAVEPOINT et nouveau tirage.

Le chiffre qui compte n'est pas le taux de collision — la reprise les
absorbe, et ce n'a jamais été la contrainte — mais le taux de succès
d'un tirage à l'aveugle, `liens_stockés / 62^longueur`. Avec un million
de liens en base :

| Longueur | Un succès tous les… |
| --- | --- |
| 7 | 3,5 millions d'essais — l'après-midi d'un moissonneur patient |
| 9 | 13 milliards d'essais |
| **11** | **52 000 milliards d'essais** |

La longueur ne gouverne que les codes **frappés**. Tout code légal reste
résoluble quelle que soit sa taille — le corpus de 2016 commence à un
caractère — donc aucun lien diffusé ne change.

**En-têtes** : CSP avec `frame-ancestors 'none'` (une page de
raccourcisseur encadrée dans un autre site est un accessoire
d'hameçonnage), `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy: no-referrer` sur la redirection, `Cache-Control:
no-store` pour qu'un lien reste révocable.

**Sélecteur de langue** : le paramètre `came_from` n'est jamais renvoyé
tel quel. Il est mis en correspondance avec une **route nommée** de
l'application, et l'adresse de retour est **reconstruite** par Pyramid à
partir du nom de cette route. Quoi que le visiteur envoie, la réponse ne
peut être qu'une URL que l'application sait fabriquer. Filtrer la chaîne
était un jeu perdu d'avance : l'audit externe a montré que
`/\evil.example` passait la garde précédente, et le standard URL impose
au navigateur de lire l'antislash comme un séparateur. La route
`/{code}` est explicitement exclue de la liste : elle correspond à
tout, et « revenir » sur un lien court après un changement de langue
ferait quitter le site.

**Taille du corps** : plafonnée à 16 Ko. `max_url_length` limitait
l'URL à 2 Ko, rien ne limitait l'enveloppe qui la transporte, et
waitress accepte 1 Gio par défaut — dans un conteneur déclaré à 512 Mo
de mémoire. Le contrôle applicatif lit `Content-Length` et **ne touche
jamais au corps** : lire un corps pour découvrir qu'il est trop gros,
c'est le déni de service lui-même. Une requête qui ne déclare pas de
longueur (transfert par morceaux) est arrêtée par le serveur, qui porte
le même nombre. Un seul réglage,
`URLSHORTENER_MAX_BODY_BYTES`, alimente les trois étages — nginx,
waitress, application — et un test échoue s'ils divergent.

**Créations depuis un autre site** : refusées. Il n'y a ni session ni
compte, donc pas de jeton CSRF à vérifier — la réponse sans session est
`Sec-Fetch-Site`, que le navigateur pose lui-même et qu'une page ne peut
ni retirer ni choisir. Un en-tête absent laisse passer : `curl` et tout
client non-navigateur n'en envoient pas, et l'attaque vit précisément
dans les navigateurs, qui l'envoient toujours.

L'API exige `Content-Type: application/json`. Les encodages de
formulaire sont des types « simples » au sens CORS : une page tierce
peut les poster **sans préflight**, donc les accepter rendait la liste
`cors_origins` décorative. Seule la création est gardée ; suivre un
lien court depuis n'importe quel site reste l'usage normal.

Limite connue, réduite au train 0024 : la garde `Sec-Fetch-Site`
refuse désormais `GET /?url=` porté cross-site par un navigateur — la
balise `<img>` d'une page tierce envoie `cross-site`, une navigation
légitime `none`, et une page ne peut ni retirer ni choisir cet
en-tête. Restent atteignables : l'inclusion depuis le même site
(couverte par la confiance `same-site` de D-02) et les clients
non-navigateurs, qui n'envoient rien. Le fermer entièrement reste
`enable_legacy_get = false` (chapitre 02).

**CORS** : rien par défaut, liste explicite sinon.

**Chaîne d'approvisionnement** : trois verrous hachés, installation en
`--require-hashes`, image de base épinglée par digest, `pip-audit` en
CI.

## Ce qui n'est pas vérifié — et pourquoi

**Aucune résolution DNS, aucune requête vers la cible.** Une résolution
faite à la création ne dit rien de l'endroit où le nom pointera à la
redirection : la payer achèterait un faux sentiment de sécurité. Donc
`http://interne.exemple.com` passe même s'il résout vers `10.0.0.5`.
Seuls les littéraux numériques sont attrapés. C'est une limite assumée,
testée explicitement (`test_a_name_is_never_resolved`).

**Aucune vérification de réputation.** Le service ne sait pas si la
cible héberge un logiciel malveillant. Un raccourcisseur public finira
par servir des liens d'hameçonnage ; prévoir une procédure de retrait
(`DELETE FROM links WHERE code = ?`), pas un filtre magique.

**Identité de limitation** : l'adresse IPv4 complète, mais le **/64**
en IPv6. Un abonné reçoit un préfixe entier, donc compter par adresse
complète ne compte rien : une machine change de source à chaque
requête. Le formulaire et l'API partagent la même identité, sinon la
limite serait doublée en alternant les deux.

**La limitation de débit intégrée est une courtoisie, pas une
défense.** Elle vit dans le processus : N workers autorisent N fois le
débit annoncé, et un redémarrage oublie tout. Elle arrête un script
bloqué. La vraie limite est dans le reverse proxy — `limit_req`, exemple
au chapitre 04.

**Pas de CSRF.** Il n'y a ni session, ni compte, ni action privilégiée :
un jeton CSRF ne protégerait rien et casserait les clients écrits contre
`POST /` en 2016. Cela changera avec le SSO Keycloak (chapitre 07) : le
jour où une action est liée à une identité, le jeton devient
obligatoire.

## Vie privée

**Aucune adresse IP n'est écrite en base.** La table des liens
contiendrait sinon un journal de qui a publié et lu quoi. La fenêtre de
limitation garde les adresses en mémoire au plus le temps de la fenêtre,
puis les jette.

Ce qui est conservé par lien : la cible, le code, la date de création,
un compteur de visites, la date de dernière visite. Le compteur peut
être coupé (`urlshortener.count_hits = false`).

Le journal applicatif n'écrit pas les URL raccourcies en INFO. Passer
`sqlalchemy.engine` en INFO les écrirait toutes — à éviter en
production.

## Audits

Versés sous [`docs/fr/audits/`](audits/README.md), datés et
autoportants. Un audit n'est jamais réécrit après coup : une découverte
revue plus tard donne lieu à une nouvelle passe qui cite la précédente.

- **[Audit interne](audits/20260822_audit_securite_interne.md)** — une
  découverte haute (S-01, cible non-ASCII servie brute dans
  `Location:`), trois moyennes, six basses, quatre risques assumés.
- **[Audit externe, première passe](audits/20260822_audit_externe_chatgpt.md)**
  — quatre P0. Trois choses que l'audit interne n'avait pas vues, toutes
  des **canonicalisations manquantes** : quatre écritures d'une IPv4,
  deux orthographes d'un nom international, un antislash lu comme un
  séparateur. Trains 0002 à 0010.
- **[Audit externe, seconde passe](audits/20260822_audit_externe_chatgpt_2.md)**
  — « globalement solide ». Trois découvertes, de la même famille :
  l'encodage IDNA divergeant de celui des navigateurs (D-01), le
  formulaire échappant au préflight (D-02), et une identité de
  limitation qui ne limitait rien en IPv6 (D-04). Trains 0012 à 0014.

Chaque découverte corrigeable l'a été avec son propre test de
non-régression, démonstration rouge/vert faite train par train.

**Deux décisions restent ouvertes**, aucune n'étant un correctif :
l'écriture du compteur de visites à chaque redirection
(`count_hits`) et la date de coupure de `GET /?url=`. La protection
de la branche `main` — troisième de cette liste depuis la seconde
passe — a désormais son contrat, ses commandes et son verrou dans la
section « Gouvernance du dépôt » ci-dessous.

## Gouvernance du dépôt

Les réglages d'un hébergeur dérivent en silence, exactement comme un
fichier de déploiement : personne ne les relit, rien n'échoue quand ils
changent. Le contrat de protection de `main` est donc consigné ici,
avec les commandes qui l'appliquent — et un test lie les noms de
contrôles ci-dessous aux jobs réellement définis dans
`.github/workflows/`, parce que renommer un job décroche le contrôle
requis côté GitHub sous son ancien nom : la branche attendrait alors,
pour toujours, un contrôle qui ne rendra plus jamais compte.

Le contrat :

- quatre contrôles obligatoires avant toute arrivée sur `main`, sous
  leurs noms exacts : `tests (3.11)`, `tests (3.12)`, `quality` et
  `smoke` — le quatrième est exigible depuis le train 0020, qui l'a
  mis sur pied ;
- poussées forcées et suppression de branche refusées ; historique
  linéaire exigé — un commit par train, pas de commit de fusion ;
- signatures exigées sur les nouveaux commits. L'historique antérieur
  reste non signé : le réécrire changerait les SHA que les audits
  citent ;
- les administrateurs ne sont pas soumis (`enforce_admins: false`) :
  le mainteneur garde une voie d'urgence, et les comptes d'agents,
  simples collaborateurs, sont pleinement liés.

Les commandes, à rejouer telles quelles si les réglages doivent être
reconstruits :

```bash
gh api -X PUT repos/michaellaunay/urlshortener/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["tests (3.11)", "tests (3.12)", "quality", "smoke"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true
}
JSON

# Signatures : à activer une fois chaque compte qui pousse muni d'une
# clé. Les fusions « squash » sont signées par GitHub lui-même ; un
# agent qui livre par PR squashée n'a donc pas besoin de clé propre.
gh api -X POST \
  repos/michaellaunay/urlshortener/branches/main/protection/required_signatures

# Vérification
gh api repos/michaellaunay/urlshortener/branches/main/protection \
  --jq '{contexts: .required_status_checks.contexts,
         force: .allow_force_pushes.enabled,
         signatures: .required_signatures.enabled}'
```

Conséquence assumée sur le geste de livraison : un commit neuf poussé
directement sur `main` est refusé, ses contrôles n'ayant pas encore
tourné. Le geste devient :

```bash
git checkout -b train-00XX
git push -u origin HEAD
gh pr create --fill
gh pr merge --auto --rebase   # fusionne seul quand les quatre passent
```

`--rebase` préserve la signature du commit et l'historique linéaire.

## Signaler une faille

`michaellaunay@logikascium.com`. Merci de ne pas ouvrir de ticket public
avant correction.
