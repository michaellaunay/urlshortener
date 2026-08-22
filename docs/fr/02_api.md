# 02 — API et routes

Toutes les routes sont servies à la racine du service. Derrière un
préfixe de reverse proxy (`location /urlmetadata/` chez KuneAgi, qui
retire le préfixe avant de transmettre), l'application continue de voir
`/` et `/<code>` ; c'est `urlshortener.base_url` qui doit alors porter
le préfixe public.

## Ordre des routes

`/{code}` attrape presque tout, donc il est enregistré **en dernier**.
Chaque chemin de premier niveau (`api`, `healthz`, `static`, `locale`)
est aussi listé dans `codec.RESERVED_CODES`, sinon le jour où un tirage
produirait le code `api`, ce lien serait injoignable à vie.
`tests/test_routes.py` compare les deux listes.

## Points d'entrée hérités de 2016

Conservés au caractère près, et verrouillés par
`tests/test_legacy_compat.py`. Ce sont eux que lisent les clients déjà
écrits.

### `GET /?url=<cible>`

Crée le lien (ou retrouve celui qui existe) et répond en JSON.

```bash
curl 'https://exemple.org/?url=https://fr.wikipedia.org/wiki/Coop%C3%A9rative'
```

```json
{
  "short_url": "https://exemple.org/k3Bq7xZ",
  "code": "SUCCESS",
  "original_url": "https://fr.wikipedia.org/wiki/Coopérative"
}
```

En cas de refus, la forme de 2016 est conservée :

```json
{ "code": "ERROR", "error": "error_url_scheme", "original_url": "javascript:alert(1)" }
```

Deux écarts assumés : le statut HTTP est désormais `400` (au lieu de
`200`), et `error` porte un identifiant stable plutôt qu'un message de
langue anglaise — on branche sur l'identifiant, on affiche le message.

Ce point d'entrée est un **GET qui écrit**. C'est un défaut de
conception de 2016, conservé pour ne rien casser : les intégrations
neuves doivent utiliser `POST /api/v1/shorten`.

### `POST /` (formulaire)

Champ `url`. Répond la page HTML portant le lien court. C'est ce que
soumet le formulaire du service lui-même.

### `GET /<code>`

Répond `302` vers la cible, avec `Referrer-Policy: no-referrer` (le site
d'arrivée n'apprend pas par quel lien court on est venu) et
`Cache-Control: no-store` (un lien reste révocable).

Code inconnu : `404`. En 2016 c'était `200` avec une page d'erreur,
qu'aucune supervision ne pouvait distinguer d'un succès.

`HEAD` fonctionne aussi.

## API JSON v1

### `POST /api/v1/shorten`

```bash
curl -X POST https://exemple.org/api/v1/shorten \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://exemple.org/une/page/tres/longue"}'
```

```json
{
  "code": "k3Bq7xZ",
  "short_url": "https://exemple.org/k3Bq7xZ",
  "url": "https://exemple.org/une/page/tres/longue",
  "created_at": "2026-08-22T10:15:00+00:00",
  "hits": 0,
  "created": true
}
```

`201` si le lien vient d'être créé, `200` si la cible était déjà connue
(`created: false`). Un `POST` en `application/x-www-form-urlencoded`
avec un champ `url` est également accepté : `curl -d url=...` est le
premier geste de tout exploitant.

### `GET /api/v1/links/{code}`

Les faits publics d'un code. **Ne compte pas comme une visite** : on
peut superviser un lien sans fausser son compteur.

### `GET /healthz`

```json
{ "status": "ok", "links": 1428 }
```

Fait un vrai aller-retour en base (`SELECT 1`), donc une base
inaccessible se voit. C'est la sonde du `HEALTHCHECK` de l'image.

## Erreurs

| Identifiant | Statut | Cause |
| --- | --- | --- |
| `error_url_required` | 400 | Champ absent ou vide |
| `error_url_too_long` | 400 | Au-delà de `max_url_length` |
| `error_url_scheme` | 400 | Schéma hors liste (`javascript:`, `data:`, `file:`, `ftp:`…) |
| `error_url_host` | 400 | Hôte absent ou syntaxiquement invalide |
| `error_url_credentials` | 400 | Identifiants dans l'autorité (`https://banque@méchant.test/`) |
| `error_url_private` | 400 | Adresse littérale privée, loopback ou lien-local |
| `error_url_blocked` | 400 | Hôte de la liste noire |
| `error_url_control_characters` | 400 | Caractères de contrôle |
| `error_rate_limited` | 429 | Limite de créations atteinte |
| `error_code_exhausted` | 503 | Aucun code libre — augmenter `code_length` |
| `error_unknown_code` | 404 | Code inconnu (API v1) |

Ces identifiants sont aussi les `msgid` du catalogue de traduction :
l'interface les affiche traduits, l'API les rend bruts.

## CORS

Rien n'est envoyé par défaut. En 2016 le service répondait
`Access-Control-Allow-Origin: *` à tout le monde, systématiquement.
Renseigner `urlshortener.cors_origins` avec la liste des origines — ou
`*` si le service est réellement public. Chaque entrée doit être une
**origine** au sens du navigateur : `scheme://hôte[:port]`, sans chemin
ni barre oblique finale. Une entrée mal formée fait échouer le
démarrage plutôt que de rester inerte.

Le préflight (`OPTIONS`) est répondu sur `/`, `/api/v1/shorten` et
`/api/v1/links/{code}` : un navigateur qui envoie du JSON en `POST`
préflighte toujours, et sans réponse à `OPTIONS` l'appel n'est jamais
émis. La réponse est un **204** quelle que soit l'origine ; les en-têtes
d'autorisation ne sont ajoutés que pour une origine admise, et un
navigateur qui lit un 204 sans eux refuse l'appel de lui-même.
`Access-Control-Max-Age` évite un aller-retour par requête.

## Langue

`?_LOCALE_=fr` sur n'importe quelle page, ou `GET /locale/fr` qui pose
un cookie `_LOCALE_` d'un an. À défaut, `Accept-Language` est négocié,
puis l'anglais.
