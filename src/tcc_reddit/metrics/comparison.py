"""Compara a coleta atual com os indicadores publicados da coleta anterior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[3]
ANALYSIS_DIR = BASE_DIR / "data" / "analysis"


@dataclass(frozen=True)
class BaselineMetric:
    value: float
    unit: str
    comparability: str
    note: str


# A coleta anterior nao foi arquivada. Estes valores sao os indicadores
# registrados no relatorio produzido antes da nova extracao.
PREVIOUS_GLOBAL = {
    "posts": BaselineMetric(1189, "count", "high", "Mesmo conceito: posts unicos."),
    "comments": BaselineMetric(147428, "count", "partial", "A profundidade de comentarios foi ampliada na coleta atual."),
    "user_user_interactions": BaselineMetric(133902, "count", "partial", "A linha de base registrava linhas detalhadas de interacao."),
    "users_with_membership": BaselineMetric(68939, "count", "partial", "Depende diretamente da cobertura de comentarios."),
    "bridge_users": BaselineMetric(7331, "count", "partial", "Depende diretamente da cobertura de comentarios."),
    "bridge_user_share": BaselineMetric(0.10634, "ratio", "medium", "A proporcao e mais comparavel que o total absoluto."),
    "mean_jaccard_brazil": BaselineMetric(0.030806, "ratio", "medium", "Mesmos subreddits e definicao de Jaccard."),
    "mean_jaccard_international": BaselineMetric(0.032691, "ratio", "medium", "Mesmos subreddits e definicao de Jaccard."),
    "mean_jaccard_cross_group": BaselineMetric(0.0003407, "ratio", "medium", "Mesmos blocos linguistico-geograficos."),
    "weighted_degree_gini": BaselineMetric(0.6040, "index", "medium", "Sensivel a profundidade e agregacao das interacoes."),
    "top_1pct_weighted_degree_share": BaselineMetric(0.2651, "ratio", "medium", "Sensivel a profundidade dos comentarios."),
}

PREVIOUS_COVERAGE = {
    "news": (121551, 34237, 0.2817),
    "worldnews": (85656, 29141, 0.3402),
    "politics": (97787, 38931, 0.3981),
    "geopolitics": (8540, 7006, 0.8204),
    "brasil": (17679, 15582, 0.8814),
    "NoticiasBR": (15170, 13985, 0.9219),
    "brasilivre": (5600, 5364, 0.9579),
    "BrasildoB": (3255, 3182, 0.9776),
}

PREVIOUS_STRUCTURAL = {
    "news_nodes": BaselineMetric(21663, "count", "partial", "Nos do grafo de r/news."),
    "news_edges": BaselineMetric(30399, "count", "partial", "Arestas do grafo de r/news."),
    "news_comments_per_post": BaselineMetric(246.3, "ratio", "partial", "Intensidade media observada em r/news."),
    "worldnews_modularity": BaselineMetric(0.7768, "index", "medium", "Modularidade da rede de r/worldnews."),
    "BrasildoB_avg_clustering": BaselineMetric(0.1218, "index", "medium", "Clusterizacao media da rede de r/BrasildoB."),
    "geopolitics_reply_comment_share": BaselineMetric(0.822, "ratio", "medium", "Parcela de respostas a comentarios."),
}


def read_csv(name: str) -> pd.DataFrame:
    path = ANALYSIS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Arquivo analitico ausente: {path}")
    return pd.read_csv(path)


def delta_row(metric: str, previous: BaselineMetric, current: float) -> dict:
    absolute_change = current - previous.value
    relative_change = absolute_change / abs(previous.value) if previous.value else None
    return {
        "metric": metric,
        "previous": previous.value,
        "current": current,
        "absolute_change": absolute_change,
        "relative_change": relative_change,
        "unit": previous.unit,
        "comparability": previous.comparability,
        "note": previous.note,
    }


def build_global_comparison(global_indicators: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        [
            delta_row(metric, baseline, float(global_indicators[metric]))
            for metric, baseline in PREVIOUS_GLOBAL.items()
        ]
    )


def build_coverage_comparison(current_coverage: pd.DataFrame) -> pd.DataFrame:
    current_lookup = current_coverage.set_index("subreddit")
    rows = []
    for subreddit, (announced, stored, coverage) in PREVIOUS_COVERAGE.items():
        current = current_lookup.loc[subreddit]
        current_rate = float(current["comment_coverage_estimate"])
        rows.append(
            {
                "subreddit": subreddit,
                "previous_announced_comments": announced,
                "previous_stored_comments": stored,
                "previous_coverage": coverage,
                "current_announced_comments": int(current["announced_comments"]),
                "current_stored_comments": int(current["stored_comments"]),
                "current_coverage": current_rate,
                "coverage_change_pp": (current_rate - coverage) * 100,
                "stored_comments_relative_change": (int(current["stored_comments"]) - stored) / stored,
            }
        )
    return pd.DataFrame(rows).sort_values("coverage_change_pp", ascending=False)


def build_structural_comparison(
    subreddit_summary: pd.DataFrame,
    interaction_types: pd.DataFrame,
) -> pd.DataFrame:
    summary = subreddit_summary.set_index("subreddit")
    reply_share = interaction_types[
        interaction_types["interaction_type"] == "reply_comment"
    ].set_index("subreddit")["share"]
    current_values = {
        "news_nodes": float(summary.loc["news", "nodes"]),
        "news_edges": float(summary.loc["news", "edges"]),
        "news_comments_per_post": float(summary.loc["news", "comments_per_post"]),
        "worldnews_modularity": float(summary.loc["worldnews", "modularity"]),
        "BrasildoB_avg_clustering": float(summary.loc["BrasildoB", "avg_clustering"]),
        "geopolitics_reply_comment_share": float(reply_share.loc["geopolitics"]),
    }
    return pd.DataFrame(
        [
            delta_row(metric, baseline, current_values[metric])
            for metric, baseline in PREVIOUS_STRUCTURAL.items()
        ]
    )


def percent(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def build_report(
    global_comparison: pd.DataFrame,
    coverage: pd.DataFrame,
    structural: pd.DataFrame,
    robustness: pd.Series,
    variant: pd.DataFrame,
    overlap: pd.DataFrame,
) -> str:
    global_lookup = global_comparison.set_index("metric")
    structural_lookup = structural.set_index("metric")
    strongest_overlap = overlap.sort_values("jaccard", ascending=False).iloc[0]

    lines = [
        "# Comparacao entre a coleta anterior e o novo dataset",
        "",
        "## Conclusao executiva",
        "",
        "O novo dataset tem praticamente o mesmo numero de posts, mas recupera muito mais da conversa associada a eles. "
        "Por isso, o crescimento de usuarios e arestas deve ser interpretado principalmente como ganho de cobertura, e nao como crescimento temporal do Reddit.",
        "",
        f"- Posts: {int(global_lookup.loc['posts', 'previous']):,} -> {int(global_lookup.loc['posts', 'current']):,} "
        f"({percent(global_lookup.loc['posts', 'relative_change'])}).",
        f"- Comentarios: {int(global_lookup.loc['comments', 'previous']):,} -> {int(global_lookup.loc['comments', 'current']):,} "
        f"({percent(global_lookup.loc['comments', 'relative_change'])}).",
        f"- Interacoes usuario-usuario: {int(global_lookup.loc['user_user_interactions', 'previous']):,} -> "
        f"{int(global_lookup.loc['user_user_interactions', 'current']):,} "
        f"({percent(global_lookup.loc['user_user_interactions', 'relative_change'])}).",
        f"- Usuarios com vinculo a subreddit: {int(global_lookup.loc['users_with_membership', 'previous']):,} -> "
        f"{int(global_lookup.loc['users_with_membership', 'current']):,} ({percent(global_lookup.loc['users_with_membership', 'relative_change'])}).",
        f"- Usuarios-ponte: {percent(global_lookup.loc['bridge_user_share', 'previous'])} -> "
        f"{percent(global_lookup.loc['bridge_user_share', 'current'])} "
        f"({global_lookup.loc['bridge_user_share', 'absolute_change'] * 100:+.2f} pontos percentuais).",
        "",
        "## Cobertura de comentarios",
        "",
        "| Subreddit | Anterior | Atual | Diferenca |",
        "|---|---:|---:|---:|",
    ]
    for subreddit, row in coverage.sort_values("current_coverage").set_index("subreddit").iterrows():
        lines.append(
            f"| r/{subreddit} | {row['previous_coverage']:.2%} | {row['current_coverage']:.2%} | "
            f"{row['coverage_change_pp']:+.2f} p.p. |"
        )

    lines.extend(
        [
            "",
            "A melhora e particularmente forte em r/news, r/worldnews e r/politics. Mesmo assim, r/news e r/worldnews continuam com as menores coberturas do conjunto, perto de 72%; suas comparacoes absolutas permanecem mais sensiveis a comentarios nao recuperados.",
            "",
            "## Diferencas estruturais",
            "",
            f"- A sobreposicao media brasileira passou de {percent(global_lookup.loc['mean_jaccard_brazil', 'previous'], 2)} para "
            f"{percent(global_lookup.loc['mean_jaccard_brazil', 'current'], 2)}.",
            f"- A sobreposicao media internacional passou de {percent(global_lookup.loc['mean_jaccard_international', 'previous'], 2)} para "
            f"{percent(global_lookup.loc['mean_jaccard_international', 'current'], 2)}.",
            f"- O par de maior sobreposicao mudou de r/NoticiasBR + r/brasil (6.45%; 642 usuarios) para "
            f"r/{strongest_overlap['source']} + r/{strongest_overlap['target']} "
            f"({strongest_overlap['jaccard']:.2%}; {int(strongest_overlap['shared_users']):,} usuarios).",
            f"- A sobreposicao entre os dois blocos passou de {percent(global_lookup.loc['mean_jaccard_cross_group', 'previous'], 3)} para "
            f"{percent(global_lookup.loc['mean_jaccard_cross_group', 'current'], 3)}. Ela quase dobrou, mas continua extremamente baixa em termos absolutos.",
            f"- O Gini do grau ponderado aumentou de {global_lookup.loc['weighted_degree_gini', 'previous']:.3f} para "
            f"{global_lookup.loc['weighted_degree_gini', 'current']:.3f}; o 1% superior passou de "
            f"{percent(global_lookup.loc['top_1pct_weighted_degree_share', 'previous'])} para "
            f"{percent(global_lookup.loc['top_1pct_weighted_degree_share', 'current'])} das conexoes ponderadas.",
            f"- Em r/news, os comentarios por post passaram de {structural_lookup.loc['news_comments_per_post', 'previous']:.1f} para "
            f"{structural_lookup.loc['news_comments_per_post', 'current']:.1f}. Esse salto explica boa parte do aumento de escala da rede.",
            f"- A modularidade de r/worldnews caiu de {structural_lookup.loc['worldnews_modularity', 'previous']:.4f} para "
            f"{structural_lookup.loc['worldnews_modularity', 'current']:.4f}; ainda e alta e continua indicando subgrupos estruturais.",
            f"- A clusterizacao de r/BrasildoB subiu de {structural_lookup.loc['BrasildoB_avg_clustering', 'previous']:.4f} para "
            f"{structural_lookup.loc['BrasildoB_avg_clustering', 'current']:.4f}.",
            "",
            "## Teste de robustez da nova coleta",
            "",
            f"- Usuarios-ponte: {percent(robustness['bridge_user_share_observational'])} na rede observacional e "
            f"{percent(robustness['bridge_user_share_balanced'])} na balanceada.",
            f"- Gini: {robustness['weighted_degree_gini_observational']:.3f} na observacional e "
            f"{robustness['weighted_degree_gini_balanced']:.3f} na balanceada.",
            f"- Jaccard medio entre blocos: {percent(robustness['mean_jaccard_cross_group_observational'], 3)} na observacional e "
            f"{percent(robustness['mean_jaccard_cross_group_balanced'], 3)} na balanceada.",
            "",
        ]
    )

    english = variant[variant["subreddit"].isin(["news", "politics", "worldnews"])]
    brazil_stable = variant[variant["subreddit"].isin(["brasil", "brasilivre", "BrasildoB"])]
    lines.extend(
        [
            "Nos tres maiores subreddits em ingles, o balanceamento reduz entre "
            f"{abs(english['edges_per_post_relative_change']).min():.0%} e {abs(english['edges_per_post_relative_change']).max():.0%} "
            "as arestas por post. Isso confirma que a rede observacional e dominada por discussoes muito profundas. "
            "Nos subreddits brasileiros mais estaveis, a mudanca fica entre "
            f"{abs(brazil_stable['edges_per_post_relative_change']).min():.0%} e {abs(brazil_stable['edges_per_post_relative_change']).max():.0%}.",
            "",
            "## Avaliacao final",
            "",
            "1. A nova extracao e metodologicamente superior porque a cobertura de comentarios melhorou em todos os subreddits. As 32 listagens retornaram 100 candidatos; depois do recorte anual, houve entre 84 e 100 elegiveis por combinacao, e a selecao final preservou 150 posts por subreddit.",
            "2. A conclusao de baixa circulacao entre os blocos brasileiro e internacional permanece robusta: o valor muda pouco quando a nova coleta e balanceada.",
            "3. A concentracao em poucos usuarios e conectores ficou mais forte, mas parte do aumento vem das grandes arvores de comentarios em ingles. Use a rede balanceada para comparacoes entre subreddits e a observacional para descrever o volume efetivamente recuperado.",
            "4. Modularidade alta descreve segmentacao relacional, nao polarizacao ideologica. Para afirmar polarizacao, ainda seria necessario classificar conteudo ou posicionamento politico.",
            "",
            "## Limites da comparacao",
            "",
            "- Os arquivos brutos da coleta anterior nao estao em `data/pilots`; a linha de base foi reconstruida a partir dos indicadores publicados anteriormente.",
            "- O metodo de coleta mudou. Deltas absolutos de comentarios, usuarios e arestas nao representam crescimento temporal da plataforma.",
            "- A cobertura e uma estimativa: `num_comments` pode incluir conteudo apagado, removido ou indisponivel pela API.",
            "- As diferencas apresentadas sao descritivas e nao constituem, por si so, testes de significancia estatistica.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    global_indicators = read_csv("global_indicators.csv").iloc[0]
    coverage = read_csv("comment_coverage_estimate.csv")
    summary = read_csv("subreddit_summary.csv")
    interactions = read_csv("interaction_types.csv")
    robustness = read_csv("robustness_indicators.csv").iloc[0]
    variant = read_csv("variant_comparison.csv")
    overlap = read_csv("subreddit_overlap.csv")

    global_comparison = build_global_comparison(global_indicators)
    coverage_comparison = build_coverage_comparison(coverage)
    structural_comparison = build_structural_comparison(summary, interactions)

    global_comparison.to_csv(ANALYSIS_DIR / "previous_vs_current_global.csv", index=False)
    coverage_comparison.to_csv(ANALYSIS_DIR / "previous_vs_current_coverage.csv", index=False)
    structural_comparison.to_csv(ANALYSIS_DIR / "previous_vs_current_structure.csv", index=False)
    report = build_report(
        global_comparison,
        coverage_comparison,
        structural_comparison,
        robustness,
        variant,
        overlap,
    )
    (ANALYSIS_DIR / "dataset_comparison_report.md").write_text(report, encoding="utf-8")

    print(report)


if __name__ == "__main__":
    main()
