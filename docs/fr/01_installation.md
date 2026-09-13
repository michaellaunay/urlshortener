# 01 — Installation

## Prérequis

Python 3.11 ou 3.12. Rien d'autre : pas de compilateur, pas de
bibliothèque système, pas de serveur de base de données tant que SQLite
suffit.

## Développement

```bash
git clone https://github.com/michaellaunay/urlshortener.git
cd urlshortener
python3 -m venv .venv
. .venv/bin/activate          # AVANT le premier pip, voir ci-dessous

pip install --require-hashes -r requirements-test.lock
pip install --no-deps -e .

python -m urlshortener.upgrades development.ini   # crée la base
pserve development.ini --reload
```

Le service écoute sur <http://localhost:5123/>.

`development.ini` diffère de `production.ini` sur trois points, et
seulement trois : les gabarits sont rechargés à chaud, les journaux sont
en DEBUG, et le refus des cibles privées est **désactivé** pour pouvoir
raccourcir `http://localhost:8080/` pendant un développement.

Sur Debian et Ubuntu, un `pip install` lancé **avant** l'activation
répond `externally-managed-environment` (PEP 668) et suggère
`--break-system-packages`. Ne pas suivre cette suggestion : elle
installerait dans le python du système. Activer le venv est la bonne
réponse ; l'invite passe alors à `(.venv)`.


### Construire la liste blanche

La liste gouverne le formulaire : une cible **listée** reçoit son lien
court à l'écran, une cible hors liste passe par l'étape e-mail. L'API
et `GET /?url=` répondent `403` hors liste — une intégration a sa
place *sur* la liste. **Liste vide = tout est autorisé** : c'est la
position de compatibilité 2016, épinglée par un test ; le verrouillage
est opt-in.

Trois formes d'entrées, distinguées par leur forme :

| Entrée | S'applique à | Exemple qui matche | Qui ne matche pas |
|---|---|---|---|
| motif nu (`fnmatch`) | l'**hôte** canonique | `*.example.coop` → `https://api.example.coop/x` | `https://example.coop/` (l'apex nu) |
| motif avec `://` | l'**URL** canonique entière | `https://docs.example.org/*` → `…/guide` | `https://docs.example.org.evil.net/` |
| `re:` + expression | l'URL canonique, `fullmatch` | `re:^https://n\.org/\d+$` → `https://n.org/123` | `https://n.org/abc` |

Quatre règles qui mordent :

1. **`*.example.coop` ne couvre pas l'apex nu `example.coop`.** C'est
   le comportement `fnmatch`, pas un oubli : listez les deux,
   `example.coop *.example.coop`.
2. **Aucune espace dans une entrée.** Le séparateur est le blanc
   (espaces *ou* retours à la ligne, la valeur ini peut donc être
   multiligne). Dans une expression régulière, écrivez `\s`.
3. **L'appariement se fait sur la forme canonique** — celle que le
   service stocke : hôte en minuscules, IDN en punycode (train 0012).
   Pour un domaine internationalisé, écrivez l'entrée en punycode :
   `python3 -c "import idna; print(idna.encode('bücher.de').decode())"`
   → `xn--bcher-kva.de`.
4. **Liste non vide ⇒ relais obligatoire.** Sans `smtp_host` et
   `mail_sender`, le démarrage refuse (« could never deliver ») : une
   porte dont l'autre battant ne mène nulle part est un mur.

Exemple complet, celui du déploiement KuneAgi :

```ini
urlshortener.whitelist =
    publicpolicies.cosmopolitical.coop
    *.cosmopolitical.coop
urlshortener.smtp_host = localhost
urlshortener.smtp_port = 25
urlshortener.mail_sender = liens@cosmopolitical.coop
```

En variable d'environnement (Docker, systemd), même valeur sur une
ligne : `URLSHORTENER_WHITELIST="publicpolicies.cosmopolitical.coop
*.cosmopolitical.coop"`.

Vérifier la liste **avant** de déployer, depuis le venv :

```bash
python3 - <<'EOF'
from urlshortener.constants_and_globals import AppSettings
from urlshortener.whitelist import is_whitelisted

entries = "publicpolicies.cosmopolitical.coop *.cosmopolitical.coop"
settings = AppSettings(whitelist=tuple(entries.split()),
                       smtp_host="x", mail_sender="a@b.c")
for url in ("https://publicpolicies.cosmopolitical.coop/page",
            "https://cosmopolitical.coop/",
            "https://ailleurs.example.net/"):
    print("LISTÉE " if is_whitelisted(url, settings) else "e-mail ", url)
EOF
```

L'administration de ce que la liste laisse passer — voir tout, bloquer
le litigieux — est au chapitre [API](02_api.md), section
« Administration ».

### Après un correctif qui touche aux verrous

Un patch peut **ajouter une dépendance**. Les verrous changent alors, et
un environnement peuplé avant le patch ne l'a pas. Le symptôme est un
`ModuleNotFoundError` qui tue la collecte entière de pytest, bien avant
que le moindre test ne s'exécute.

Le réflexe, après tout patch dont le `git apply` a touché un
`requirements*.lock` :

```bash
pip install --require-hashes -r requirements-test.lock
python -m pytest -q
```

Un test vérifie qu'une dépendance nouvelle est bien déclarée **et**
verrouillée ; aucun test ne peut vérifier ce qui est installé dans ton
venv.

## Lancer les tests

```bash
pytest -q
pytest -q --cov=urlshortener --cov-report=term-missing
```

576 tests, 91 % de couverture. Les trois commandes exactes de la CI
qualité — à reproduire telles quelles avant toute livraison :

```bash
ruff check urlshortener tests docker
bandit -ll -r urlshortener docker
pip-audit --require-hashes -r requirements.lock
```

## Serveur, sans Docker

Un compte de service dédié, un clone épinglé sur un SHA, un venv à
l'intérieur, les données ailleurs :

```
/srv/urlshortener/
├── app/          # le clone, propriété de root, lu par le service
│   └── .venv/
├── var/          # la base SQLite — propriété exclusive du service
└── etc/          # production.ini et urlshortener.env, hors git, 0640
```

```bash
sudo useradd --system --home /srv/urlshortener --shell /usr/sbin/nologin urlshortener
sudo -u urlshortener python3 -m venv /srv/urlshortener/app/.venv
sudo -u urlshortener /srv/urlshortener/app/.venv/bin/pip \
     install --require-hashes -r /srv/urlshortener/app/requirements.lock
sudo -u urlshortener /srv/urlshortener/app/.venv/bin/pip \
     install --no-deps /srv/urlshortener/app
```

L'unité systemd est **livrée** dans le dépôt, à
`deploy/systemd/urlshortener.service` — plutôt que recopiée ici, où
elle divergerait. Elle a d'ailleurs divergé : la version en ligne dans
ce chapitre et le fichier livré ne disaient pas la même chose sur
`WorkingDirectory`, ce qui n'est pas cosmétique — c'est de là que
`find_dotenv(usecwd=True)` cherche le `.env`.

```bash
sudo install -m 0644 deploy/systemd/urlshortener.service /etc/systemd/system/
sudo install -m 0640 -o root -g urlshortener \
     deploy/systemd/urlshortener.env.example /srv/urlshortener/etc/urlshortener.env
$EDITOR /srv/urlshortener/etc/urlshortener.env     # base_url surtout
sudo systemctl daemon-reload
sudo systemctl enable --now urlshortener
```

**L'environnement est lu par systemd, pas par `python-dotenv`.**
`find_dotenv` remonte depuis le répertoire de travail ; il ne descend
jamais dans `etc/`, donc un `.env` posé là où cette documentation le
plaçait n'était **jamais chargé**. L'`EnvironmentFile` rend le contrat
d'exploitation explicite et supprime toute dépendance au répertoire
courant pour la configuration.

**Le chemin de la base doit être absolu.** `production.ini` dit
`sqlite:///%(here)s/var/urlshortener.sqlite`, et `%(here)s` est le
répertoire du **fichier .ini** — donc `etc/`, que `ProtectSystem=strict`
rend en lecture seule. Le fichier d'environnement livré pose déjà
`SQLALCHEMY_URL` en absolu sous `ReadWritePaths`. Un test vérifie que
les deux concordent.

Deux points à y lire plutôt qu'à les recopier ailleurs :

- `ExecStartPre` n'est pas décoratif : le schéma doit être prêt avant la
  première requête, sinon le premier visiteur d'un déploiement neuf
  reçoit une 500. C'est aussi la commande qui échouait sur toute
  installation neuve avant le train 0017.

- Attention à `ProtectHome=true` si le clone est sous `/home` : l'unité
  ne le verra pas. Suivre l'arborescence ci-dessus, ou adapter les
  directives `WorkingDirectory`, `ExecStart` et `ProtectHome` — dans le
  fichier livré, pas dans une copie.

## Configuration

Chaque clé `urlshortener.*` du fichier `.ini` est surchargeable par la
variable d'environnement correspondante. L'ordre est
`environnement > .ini > défaut`.

| Clé `.ini` | Variable | Défaut | Rôle |
| --- | --- | --- | --- |
| `urlshortener.base_url` | `URLSHORTENER_BASE_URL` | `http://localhost:5123/` | Préfixe **public** des liens, slash final compris |
| `sqlalchemy.url` | `SQLALCHEMY_URL` | fichier SQLite dans `var/` | Base de données |
| `urlshortener.code_length` | `URLSHORTENER_CODE_LENGTH` | `11` | Longueur d'un code neuf |
| `urlshortener.code_max_attempts` | `URLSHORTENER_CODE_MAX_ATTEMPTS` | `8` | Tirages avant d'abandonner sur collision |
| `urlshortener.max_url_length` | `URLSHORTENER_MAX_URL_LENGTH` | `2048` | Longueur maximale d'une cible |
| `urlshortener.max_body_bytes` | `URLSHORTENER_MAX_BODY_BYTES` | `16384` | Taille maximale du corps d'une requête (plafonne aussi waitress) |
| `urlshortener.default_scheme` | `URLSHORTENER_DEFAULT_SCHEME` | `http` | Schéma ajouté quand il manque |
| `urlshortener.allowed_schemes` | `URLSHORTENER_ALLOWED_SCHEMES` | `http https` | Schémas acceptés |
| `urlshortener.block_private_targets` | `URLSHORTENER_BLOCK_PRIVATE_TARGETS` | `true` | Refuser les adresses privées littérales |
| `urlshortener.blocked_hosts` | `URLSHORTENER_BLOCKED_HOSTS` | vide | Hôtes toujours refusés, sous-domaines compris |
| `urlshortener.count_hits` | `URLSHORTENER_COUNT_HITS` | `true` | Compter les redirections |
| `urlshortener.enable_legacy_get` | `URLSHORTENER_ENABLE_LEGACY_GET` | `true` | Servir `GET /?url=` (2016) |
| `urlshortener.whitelist` | `URLSHORTENER_WHITELIST` | *(vide)* | Cibles raccourcissables sans e-mail ; vide = tout |
| `urlshortener.smtp_host` | `URLSHORTENER_SMTP_HOST` | *(vide)* | Relais SMTP du flux e-mail |
| `urlshortener.smtp_port` | `URLSHORTENER_SMTP_PORT` | `25` | Port du relais |
| `urlshortener.smtp_starttls` | `URLSHORTENER_SMTP_STARTTLS` | `false` | STARTTLS vers le relais |
| `urlshortener.mail_sender` | `URLSHORTENER_MAIL_SENDER` | *(vide)* | Expéditeur des messages |
| `urlshortener.admin_password_hash` | `URLSHORTENER_ADMIN_PASSWORD_HASH` | *(vide)* | Empreinte PBKDF2 de l'admin ; vide = /admin en 404 |
| `urlshortener.throttle_max_creations` | `URLSHORTENER_THROTTLE_MAX` | `30` | Créations par fenêtre et par adresse |
| `urlshortener.throttle_window_seconds` | `URLSHORTENER_THROTTLE_WINDOW` | `300` | Durée de la fenêtre |
| `urlshortener.throttle_max_reads` | `URLSHORTENER_THROTTLE_MAX_READS` | `0` | Lectures de l'API par fenêtre (0 = illimité) |
| `urlshortener.cors_origins` | `URLSHORTENER_CORS_ORIGINS` | vide | Origines autorisées sur l'API |

### Le démarrage refuse une configuration impossible

Une configuration qui ne peut pas fonctionner **fait échouer le
démarrage**, avec la liste complète des problèmes d'un coup :

```
refusing to start, 2 problem(s) in the configuration:
  - code_length must be between 1 and 32 (got 0)
  - default_scheme 'ftp' is not in allowed_schemes ['http', 'https'] —
    a URL submitted without a scheme could never be accepted
```

Sont vérifiés : `base_url` absolue en http(s) et terminée par `/`, les
bornes de `code_length` et `code_max_attempts`, la cohérence
`max_body_bytes` ≥ `max_url_length` + enveloppe (deux valeurs chacune
correcte et conjointement impossibles), l'absence de schéma dangereux
dans `allowed_schemes`, l'appartenance de `default_scheme` à cette
liste, une fenêtre de limitation non nulle quand la limitation est
active, et la forme des entrées `cors_origins`.

Auparavant, `code_length = 0` démarrait proprement et échouait des
heures plus tard, au premier raccourcissement, sur une `ValueError`
parlant d'un alphabet — un message produit par une faute de frappe dans
un `.ini`, à un endroit qui ne dit rien de l'endroit où est la faute.

**`base_url` est le seul réglage qu'on ne peut pas corriger après coup
sans dégâts** : c'est lui qui est imprimé dans les liens distribués. Le
poser faux, c'est distribuer des liens morts.
