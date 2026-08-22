# Audits

Un fichier par passage, nommé `AAAAMMJJ_<sujet>.md`, **autoportant** :
il porte son chapeau (qui, comment, quel périmètre, quelles limites),
ses découvertes avec leurs preuves, l'état de chaque correctif, et les
décisions qui restent au mainteneur.

Un audit n'est jamais réécrit après coup. Une découverte revue plus tard
donne lieu à un nouveau passage qui cite le précédent.

| Date | Passage | Verdict |
| --- | --- | --- |
| 2026-08-22 | [Audit interne de sécurité](20260822_audit_securite_interne.md) | 1 haute, 3 moyennes, 6 basses, 4 risques assumés — toutes les découvertes corrigeables corrigées |
| 2026-08-22 | [Audit externe (ChatGPT)](20260822_audit_externe_chatgpt.md) | 4 P0, 4 P1, 5 P2, 1 P3 — trains 0002 à 0010, un risque accepté |

## Parité linguistique

La convention du projet veut des documents miroirs `docs/fr` ↔
`docs/en`. Les deux rapports ci-dessus sont **rédigés en français
seulement** ; leur traduction intégrale est en attente. C'est un écart
assumé et signalé plutôt que masqué : `docs/en/audits/README.md` le dit
aussi.
