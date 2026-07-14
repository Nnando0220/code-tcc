# Arquitetura do pipeline

## Fluxo canonico

```text
config/*.yaml
    -> data/raw/<run_id> (imutavel)
    -> data/interim/<run_id>
    -> data/processed/<run_id>/{observational,balanced}
    -> results/<run_id>/{observational,balanced,comparison,reports}
```

## Responsabilidades

- `collection`: cliente Reddit, submissions e comentarios. Nao calcula metricas.
- `processing`: limpeza, pseudonimizacao, recorte temporal e amostragem.
- `networks`: construcao, agregacao e exportacao das redes.
- `metrics`: estrutura, centralidade, comunidades, segregacao e robustez.
- `validation`: qualidade tabular, privacidade e equivalencia CSV/GEXF.
- `reporting`: manifests, tabelas, snapshots e relatorios academicos.

## Compatibilidade da migracao

`src/tcc_reddit/legacy_pipeline.py` preserva o comportamento estatistico que ja
foi testado. Os modulos especializados sao a API oficial e assumirao a
implementacao gradualmente. Os arquivos legados permanecem somente ate uma
execucao completa passar por `scripts/validate_all.py`.

Depois de uma validacao bem-sucedida, o pipeline remove as copias antigas em
`data/raw`, `data/processed`, `data/graphs`, `data/metrics`, `data/balanced` e
`data/analysis`. Permanecem como fontes definitivas apenas os caminhos por
`run_id` mostrados no fluxo canonico.

## Workspaces do Gephi

- `observational`: `results/<run_id>/observational/gephi`, para descrever todo
  o volume recuperado.
- `balanced`: `results/<run_id>/balanced/gephi`, para comparacoes mais justas
  entre subreddits.
- `legacy`: nome reservado para projetos antigos baseados em `data/graphs`.
  Esses arquivos nao sao canonicos e sao removidos depois da validacao.

## Imutabilidade

Ao registrar um `run_id`, cada bruto recebe SHA-256 em
`data/raw/<run_id>/manifest.json`. Uma tentativa posterior de publicar conteudo
diferente sob o mesmo identificador interrompe o pipeline.

## Nomes canonicos

- `user_user_edges_detailed.csv`
- `user_user_edges_directed.csv`
- `user_user_edges_undirected.csv`
- `user_user_directed.gexf`
- `user_user_undirected.gexf`
- `user_user_visualization.gexf`
- `user_subreddit_edges.csv`
- `subreddit_subreddit_edges.csv`
- `subreddit_subreddit.gexf`
