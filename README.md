# TraficLab Factory

Fábrica de perfiles, políticas y bootstrap para onboarding de equipo Hermes.

## Estructura

```
policies/           ← reglas canónicas de operación
profiles/           ← plantillas de perfil Hermes
  ashley/           ← perfil para HERMES-ASHLEY-01
bootstrap/          ← scripts de setup (pendientes)
skills-manifest/   ← inventario y bundles de skills
```

## Propósito

Permite que nuevos miembros del equipo (como Ashley) se onboardeen de forma:
- Segura (sin copiar secrets de David)
- Reproducible (desde GitHub, no desde chat)
- Gobernada (con Work Orders y jerarquía de autoridad)

## Docs clave

- [ASHLEY-AGENT.md](./ASHLEY-AGENT.md) — blueprint completo del onboarding de Ashley
- [policies/authority-hierarchy.md](./policies/authority-hierarchy.md) — jerarquía GitHub > control-plane > Obsidian > chat

## Para nuevo miembro

1. Leer `ASHLEY-AGENT.md`
2. Ejecutar scripts de bootstrap en orden
3. Hacer CLAIM en `suini#29`
4. Seguir el piloto read-only
5. Publicar resultado en GitHub

## Autoridad

```
GitHub remote > control-plane > PROJECT_STATE > Obsidian > chat
```

Regla:
```
if target_product != assigned_product:
  STOP — PRODUCT_OWNERSHIP_MISMATCH
```
