---
type: test
created: 2026-09-12T15:08Z
owner: Nafron/David
project: nafron/codebase-QA-stack
refs: []
evidence_strength: A (live install + version captured)
---

# Test instalación ast-grep + pyright + mypy

## Comando ejecutado
```bash
# 1. ast-grep via npm
npm install -g @ast-grep/cli
# result: added 3 packages in 13s
# warn: install-scripts blocked (postinstall.js) — no break

# 2. pyright via pip
pip install pyright
# result: Successfully installed nodeenv-1.10.0 pyright-1.1.414

# 3. mypy via pip (fallback)
pip install mypy
# result: Successfully installed ast-serialize-0.11.1 librt-0.15.0 mypy-2.3.1
#              mypy_extensions-1.1.0
```

## Versions verificadas
| Tool | Versión | Path |
|---|---|---|
| ast-grep | 0.45.3 | `/c/Users/david/AppData/Local/hermes/node/ast-grep` |
| sg | (alias) | `/c/Users/david/AppData/Local/hermes/node/sg` |
| pyright | 1.1.414 | `/c/.../hermes-agent/venv/Scripts/pyright` |
| mypy | 2.3.1 (compiled: yes) | en el venv |

## ¿Funciona?
- ✅ `ast-grep --version` returns `ast-grep 0.45.3`
- ✅ `pyright --version` returns `pyright 1.1.414`
- ✅ `mypy --version` returns `mypy 2.3.1 (compiled: yes)`

## Riesgos identificables
- **ast-grep postinstall.js blocked by npm** — puede significar el binario funciona pero los `language parsers` opcionales no se compilaron. Si pasa, re-run con `npm config set allow-scripts=@ast-grep/cli --location=user`
- **mypy 2.3.1 necesita Python 3.7+** — ya verifico antes que sea compatible

## Próximo test
Validar ast-grep contra código real (ejemplo: el archivo `06_scene_digital_model/replay/builder.py` para ver la estructura AST).
