# Reproducibilidade

1. Crie a venv e instale `requirements.txt`.
2. Configure `TCC_HASH_SALT` em `.env`.
3. Revise `config/collection.yaml`, `sampling.yaml` e `networks.yaml`.
4. Para reutilizar os brutos, execute `python scripts/reprocess.py`.
5. Execute `python scripts/validate_all.py`.
6. Consulte `results/<run_id>/manifest.json` e `validation_report.json`.

Uma nova coleta exige tambem as tres variaveis `REDDIT_*`. O reprocessamento
nao cria cliente Reddit e nao depende de rede externa.
