# 05 — Migration depuis le service de 2016

## Ce qu'on reprend

Le service de 2016 tient tout dans une table :

```sql
CREATE TABLE WEB_URL(
    ID  INTEGER PRIMARY KEY AUTOINCREMENT,
    NUM TEXT NOT NULL UNIQUE,
    URL TEXT NOT NULL UNIQUE)
```

`NUM` est le code court. Il est imprimé sur les pages d'autrui, dans les
courriels d'autrui, dans les contenus KuneAgi. **Il est repris tel
quel** : un code réattribué est un lien mort.

Les URL sont reprises telles quelles elles aussi, et c'est un choix. Les
passer dans `normalise_url` en « corrigerait » certaines — or une URL
corrigée est une destination différente de celle que le lien promet
depuis dix ans. `normalise_url` sert donc de **juge** et jamais de
transformateur : son résultat est jeté, seule sa décision compte.

### Deux sortes de refus

Elles appellent deux actions différentes, d'où la séparation dans le
rapport.

**Refus « unfixable »** — la ligne ne peut pas fonctionner, ou ne doit
pas. Aucun drapeau ne les lève :

| Motif | Ce que ça veut dire |
| --- | --- |
| `bad_code` | Le code n'appartient pas à l'alphabet |
| `reserved_code` | **Une route occupe déjà ce chemin** |
| `empty_url` | Pas de cible |
| `control_chars` | Un retour chariot devient une injection d'en-tête |
| `bad_port` | Aucun client n'accepte ce port — et le redirect le supprimerait en silence : autre destination |
| `bad_host` | Aucun client ne résout cet hôte — et, non-ASCII irrécupérable, il ferait un 500 à chaque visite |
| `credentials` | Ce qui précède `@` est un déguisement — ou un secret republié, quand c'est une vraie authentification |
| `scheme:javascript` (et `data`, `vbscript`, `file`) | Mettrait un vecteur d'attaque — ou un chemin de fichier — dans un `Location:` sous ton domaine |

`reserved_code` mérite un mot : `healthz` fait sept caractères de
l'alphabet, donc `is_valid_code` le déclarait légal et il s'importait
proprement — vers une ligne que la vue de redirection ne sera jamais
interrogée sur, puisque `/healthz` est une route.
`tests/test_routes.py` affirme déjà qu'aucune route ne doit masquer un
code ; l'import était la porte restée ouverte. L'outil **signale et
s'arrête** plutôt que de renommer : un code renommé est un lien mort, et
seul toi peux peser un lien mort contre un lien injoignable. Les deux
issues sont d'accepter la perte, ou de déplacer la route.

**Refus « policy »** — le lien fonctionne très bien, ce sont seulement
les règles de la 2.x qui ne l'auraient pas créé aujourd'hui : schéma
fonctionnel hors liste (`ftp:`), cible privée, hôte de la
liste noire, URL trop longue. Ceux-là, tu peux les reprendre en
connaissance de cause :

```bash
python -m urlshortener.tools.import_legacy production.ini urls.db --allow-unsafe-legacy
```

Le drapeau lève **exactement** les refus de politique, jamais les
autres : un drapeau capable d'importer un vecteur XSS n'est pas un
drapeau, c'est un piège tendu à un exploitant pressé.

## Procédure

```bash
# 1. copie du fichier de production, service arrêté ou non (lecture seule)
docker cp <conteneur_legacy>:/app/var/urls.db ./urls.db
sha256sum urls.db | tee urls.db.sha256

# 2. répétition à blanc — ne écrit rien, dit tout
python -m urlshortener.tools.import_legacy production.ini urls.db --dry-run

# 3. import réel
python -m urlshortener.tools.import_legacy production.ini urls.db
```

Sortie :

```
rows read              : 1428
imported               : 1425
already present        : 0
duplicate target URL   : 0
refused (unfixable)    : 2
refused (policy)       : 2
  REFUSED  bb2            scheme:javascript            javascript:alert(1)
  REFUSED  healthz        reserved_code                https://exemple.org/x
  POLICY   cc3            error_url_scheme:ftp         ftp://exemple.org/fichier
  POLICY   dd4            error_url_private:127.0.0.1  http://127.0.0.1/admin

The POLICY rows are links that work; the 2.x rules simply would not
create them today.
Read the list, then re-run with --allow-unsafe-legacy to import them
anyway.

The REFUSED rows cannot be imported by any flag. A reserved_code is
shadowed by a route: either that link is lost, or the route moves.
```

L'import est **idempotent** : un code déjà présent est laissé tel quel
et compté en `already present`. Un import interrompu se reprend en le
relançant.

Le fichier hérité est ouvert en `mode=ro` : l'ancien service peut
continuer à tourner pendant l'opération.

## Contrôles avant bascule

```bash
# le nombre de liens correspond
curl -fsS http://127.0.0.1:5123/healthz

# un code ancien, tiré au hasard, résout vers la bonne cible
sqlite3 urls.db "SELECT NUM, URL FROM WEB_URL ORDER BY random() LIMIT 5"
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:5123/<NUM>
```

C'est ce contrôle-là qui compte. Le reste peut attendre ; un lien
ancien qui ne résout plus, non.

## Brancher KuneAgi

Le vhost existant fait :

```nginx
location /urlmetadata/ {
    rewrite    /urlmetadata/(.*) /$1 break;
    proxy_pass http://urlmetadataws;
}
upstream urlmetadataws { server 127.0.0.1:5123; }
```

Le préfixe est retiré avant transmission : l'application voit `/` et
`/<code>`, elle n'a donc rien à savoir du montage. En revanche
`urlshortener.base_url` doit porter le préfixe **public** :

```
URLSHORTENER_BASE_URL=https://publicpolicies.cosmopolitical.coop/urlmetadata/
```

Bascule : arrêter l'ancien service, démarrer le nouveau sur le même
port, `upstream` inchangé. Retour arrière en dix secondes en
redémarrant l'ancien conteneur — d'où l'intérêt de ne pas le supprimer
tout de suite.

Point d'exploitation connexe : le conteneur legacy de KuneAgi héberge ce
service sur 5123. Tant que la bascule n'a pas eu lieu, l'éteindre coupe
`/urlmetadata/`.

## Différences visibles après bascule

- Un code inconnu répond `404` au lieu de `200`. Une supervision qui
  comptait les 200 verra le changement — c'est le but.
- Une URL refusée répond `400`. Le corps JSON garde sa forme.
- Plus d'`Access-Control-Allow-Origin: *` : renseigner
  `urlshortener.cors_origins` si un script tiers appelait le service
  depuis un navigateur.
- Les codes neufs font 7 caractères et sont tirés au hasard ; les
  anciens gardent leur longueur d'origine. Les deux cohabitent sans
  difficulté, l'alphabet est le même.
