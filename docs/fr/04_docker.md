# 04 — Docker et exploitation

## Démarrer

Toutes les commandes se lancent depuis la **racine du dépôt**.

```bash
./docker/init.sh          # crée docker/.env — une seule fois
$EDITOR docker/.env       # URLSHORTENER_BASE_URL surtout
docker compose --env-file docker/.env -f docker/docker-compose.yaml up -d --build
docker compose -f docker/docker-compose.yaml logs -f
```

## Ce que fait l'image

Construction en deux étages :

- **builder** : venv, installation du verrou d'exécution en mode
  `--require-hashes` (un paquet substitué fait échouer la construction),
  puis installation de l'application **en wheel** ;
- **runtime** : ne reçoit que le venv et une liste blanche explicite de
  fichiers de configuration — jamais `COPY .`.

Points fixés volontairement :

- image de base épinglée par **digest**, pas par tag. Le digest est
  celui déjà vérifié et en production dans la pile AlirPunkto : les deux
  services partagent une base identique et connue ;
- `--only-binary=:all:` avec **une** exception nommée,
  `pyramid-chameleon`, qui n'existe qu'en sdist sur PyPI mais est du
  python pur. Aucun compilateur dans aucun étage ; un futur sdist hors
  liste fait échouer la construction au lieu d'entraîner discrètement
  une chaîne de compilation ;
- exécution sous l'utilisateur non privilégié `urlshortener` (uid 1002),
  `no-new-privileges` ;
- `HEALTHCHECK` sur `/healthz`, qui fait un vrai aller-retour en base ;
- reproductibilité stricte optionnelle : `URLSHORTENER_UBUNTU_SNAPSHOT`
  épingle apt sur `snapshot.ubuntu.com`.

## L'entrée en service

`docker/start_urlshortener.sh` :

1. se place dans `APP_HOME` — ce n'est pas décoratif. `find_dotenv()`
   remonte depuis le **fichier appelant** ; l'application étant
   installée en wheel, cette remontée partirait de `site-packages` et ne
   croiserait jamais le `.env` du déploiement. C'est exactement la
   panne qui a empêché AlirPunkto de démarrer après le passage en wheel.
   Le code utilise `find_dotenv(usecwd=True)`, et le `cd` fournit le
   `cwd` attendu ;
2. dérive `var/runtime.ini` depuis `production.ini` via
   `docker/apply_server_overrides.py`. PasteDeploy ne transmet **pas**
   `global_conf` à la section `[server:main]` — impasse prouvée ailleurs
   — donc `listen` est réécrit dans une copie plutôt que figé dans le
   fichier versionné, qui reste juste pour le bare metal ;
3. applique les étapes de schéma **avant** de servir. Paresseux, le
   premier visiteur d'un déploiement neuf recevrait une 500 ;
4. `exec pserve`, pour que waitress soit PID 1 et reçoive les signaux.

`tests/test_docker_conventions.py` verrouille tout cela : digest présent,
`--require-hashes` présent, verrous de test et de qualité **absents** de
l'image, `USER` après le dernier `chown`, ordre migration/service,
publication sur loopback, et surtout : **`.dockerignore` n'exclut pas
`docker/`**. C'est la panne latente exacte livrée par AlirPunkto — le
répertoire était ignoré, l'assistant appelé au démarrage n'était donc
jamais copié, et le conteneur mourait au premier lancement, longtemps
après que la construction eut été déclarée verte.

## Réseau

Le service est publié sur `127.0.0.1:5123` uniquement. Ce qui fait face
au réseau, c'est le reverse proxy.

Les en-têtes de proxy vont dans un fichier **inclus par chaque
emplacement**. Un `location = /` n'hérite pas des `proxy_set_header`
d'un `location /` voisin : nginx choisit un seul emplacement, et les
directives des autres n'existent pas pour lui. L'exemple précédent de
cette documentation avait ce défaut, et sa conséquence était exactement
la panne décrite plus haut — `client_addr` identique pour tous.

`/etc/nginx/urlshortener_proxy.conf` :

```nginx
proxy_pass         http://127.0.0.1:5123;
proxy_http_version 1.1;
proxy_set_header   Host              $http_host;
proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header   X-Forwarded-Proto $scheme;
proxy_redirect     off;
```

Le vhost :

```nginx
# Le corps d'une requête de raccourcissement tient largement dans 16 Ko.
client_max_body_size 16k;

limit_req_zone $binary_remote_addr zone=shorten:10m rate=10r/m;

# Les TROIS chemins qui créent un lien. Ne couvrir que `/` laisserait
# l'API entière hors de la limite.
location = / {
    limit_req zone=shorten burst=20 nodelay;
    include /etc/nginx/urlshortener_proxy.conf;
}
location = /api/v1/shorten {
    limit_req zone=shorten burst=20 nodelay;
    include /etc/nginx/urlshortener_proxy.conf;
}

# Tout le reste : redirections et lecture. Jamais limité — c'est la
# fonction du service.
location / {
    include /etc/nginx/urlshortener_proxy.conf;
}
```

### L'adresse du visiteur, en conteneur

`production.ini` porte `trusted_proxy = 127.0.0.1`, ce qui est juste sur
bare metal et **faux en conteneur** : nginx tourne sur l'hôte et arrive
par le pont Docker, donc waitress voit l'adresse de la passerelle,
conclut que le pair n'est pas le proxy de confiance, et **ignore
purement et simplement `X-Forwarded-For`**. `request.client_addr` devient
alors la même adresse pour tout le monde — le pont — et le limiteur de
créations, qui est indexé dessus, se transforme en un budget global
qu'un seul visiteur peut épuiser pour tous.

L'adresse de la passerelle n'est pas connue au moment où l'on écrit le
compose. L'entrée en service la lit donc dans la table de routage du
noyau au démarrage (`/proc/net/route`, route par défaut) et la
substitue **uniquement** si le fichier porte encore le défaut bare
metal. Une valeur écrite par l'exploitant n'est jamais écrasée, et
`URLSHORTENER_TRUSTED_PROXY=none` ne fait confiance à aucun proxy. La
ligne `[proxy] …` du journal de démarrage dit ce qui a été retenu et
pourquoi.

## Sauvegardes

L'état du service tient dans un fichier. Le perdre, c'est tuer tous les
liens jamais distribués.

```bash
./docker/backup.sh urlshortener ./backups
# restauration : service arrêté, on remet le fichier en place
sqlite3 backups/urlshortener-20260822T101500Z.sqlite \
        'PRAGMA integrity_check; SELECT count(*) FROM links;'
```

Le script passe par `sqlite3 .backup` et non par `cp` : copier un
fichier en cours d'écriture donne un instantané peut-être incohérent.
Il écrit sous `umask 077` dans un répertoire en 700 — la sauvegarde
contient **toutes les URL jamais raccourcies** — et il ne recopie plus
la base dans une connexion `:memory:` avant de la rendre, ce qui, sous
`mem_limit: 512m`, était une bombe à retardement proportionnelle à la
taille des données.
Et une sauvegarde que personne n'a restaurée n'est pas une sauvegarde —
la restauration se répète, hors incident.

## Superviser

```bash
curl -fsS http://127.0.0.1:5123/healthz
docker inspect --format '{{.State.Health.Status}}' urlshortener
docker compose -f docker/docker-compose.yaml logs --since 1h
```

Le journal applicatif est en INFO ; `sqlalchemy.engine` est en WARN
(le passer en INFO écrit chaque requête, y compris les URL raccourcies).

## Mettre à jour

```bash
git fetch && git reset --hard <sha>
docker compose --env-file docker/.env -f docker/docker-compose.yaml up -d --build
```

Le volume survit. Les étapes de schéma s'appliquent seules au démarrage.
Retour arrière : redémarrer sur le SHA précédent — mais **seulement** si
aucune étape de schéma n'a été franchie entre les deux, sinon restaurer
la sauvegarde.
