# TCC Reddit

Pipeline reproduzivel para coleta, construcao e analise de redes entre usuarios
e comunidades do Reddit.

## Comandos

```powershell
.\.venv\Scripts\python.exe scripts\reprocess.py
.\.venv\Scripts\python.exe scripts\analyze.py
.\.venv\Scripts\python.exe scripts\export_gephi.py
.\.venv\Scripts\python.exe scripts\validate_all.py
```

Testes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Compatibilidade mantida:

```powershell
.\.venv\Scripts\python.exe main.py --reprocess-existing
```

Os parametros academicos ficam em `config/`. Cada execucao usa um `run_id`,
mantem brutos imutaveis em `data/raw/<run_id>` e publica derivados em
`results/<run_id>` com nomes canonicos.

Consulte [ARCHITECTURE.md](docs/ARCHITECTURE.md) e
[REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).
