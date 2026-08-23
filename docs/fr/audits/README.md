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
| 2026-08-22 | [Audit externe, seconde passe](20260822_audit_externe_chatgpt_2.md) | « Globalement solide » — 3 corrections (trains 0012 à 0014), 2 risques acceptés, 3 décisions en attente |
| 2026-08-23 | [Audit externe, troisième passe](20260823_audit_externe_chatgpt_3.md) | 1 P1 nouveau (systemd), 1 régression de version, points antérieurs ouverts — trains 0018 à 0019, réserve CI élucidée par l'audit croisé |
| 2026-08-23 | [Audit externe croisé (Claude)](20260823_audit_externe_claude.md) | Constats ChatGPT confirmés ; N-01 (Smoke jamais exécuté), N-02, N-03, N-05 — trains 0020 à 0024, 1 décision restante |

## Parité linguistique

La convention du projet veut des documents miroirs `docs/fr` ↔
`docs/en`. Les deux rapports ci-dessus sont **rédigés en français
seulement** ; leur traduction intégrale est en attente. C'est un écart
assumé et signalé plutôt que masqué : `docs/en/audits/README.md` le dit
aussi.
