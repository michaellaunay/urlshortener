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

**Codes** : tirés de `secrets`, 62⁷ possibilités à la longueur par
défaut, collisions gérées par SAVEPOINT et nouveau tirage.

**En-têtes** : CSP avec `frame-ancestors 'none'` (une page de
raccourcisseur encadrée dans un autre site est un accessoire
d'hameçonnage), `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy: no-referrer` sur la redirection, `Cache-Control:
no-store` pour qu'un lien reste révocable.

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

- [22 août 2026 — audit interne](audits/20260822_audit_securite_interne.md) :
  une découverte haute (S-01, cible non-ASCII servie brute dans
  `Location:` — 500 permanent ou redirection mutilée), trois moyennes,
  six basses, quatre risques assumés. Toutes les découvertes
  corrigeables l'ont été, avec un test de non-régression chacune.

## Signaler une faille

`michaellaunay@logikascium.com`. Merci de ne pas ouvrir de ticket public
avant correction.
