"""Analise reproduzivel dos resultados coletados do Reddit."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"
BRAZILIAN_SUBREDDITS = {"brasil", "brasilivre", "BrasildoB", "NoticiasBR"}
INTERNATIONAL_SUBREDDITS = {"politics", "worldnews", "geopolitics", "news"}
EXPECTED_POSTS_PER_SORT = 50


def read_csv(relative_path: str) -> pd.DataFrame:
    path = DATA_DIR / relative_path
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def safe_number(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def dataframe_records(frame: pd.DataFrame) -> list[dict]:
    return [
        {str(key): safe_number(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def gini(values: pd.Series) -> float:
    array = np.sort(values.fillna(0).astype(float).to_numpy())
    if len(array) == 0 or array.sum() == 0:
        return 0.0
    index = np.arange(1, len(array) + 1)
    return float((2 * np.sum(index * array) / (len(array) * array.sum())) - ((len(array) + 1) / len(array)))


def subreddit_group(name: str) -> str:
    if name in BRAZILIAN_SUBREDDITS:
        return "Brasil"
    if name in INTERNATIONAL_SUBREDDITS:
        return "Internacional"
    return "Outro"


def build_subreddit_summary(
    posts: pd.DataFrame,
    comments: pd.DataFrame,
    user_subreddit: pd.DataFrame,
    metrics: pd.DataFrame,
) -> pd.DataFrame:
    names = sorted(set(posts.get("subreddit", [])) | set(comments.get("subreddit", [])))
    rows = []
    for name in names:
        subreddit_posts = posts[posts["subreddit"] == name]
        subreddit_comments = comments[comments["subreddit"] == name]
        post_users = set(subreddit_posts.get("author_hash", pd.Series(dtype=str)).dropna().astype(str))
        comment_users = set(subreddit_comments.get("author_hash", pd.Series(dtype=str)).dropna().astype(str))
        users = post_users | comment_users
        rows.append(
            {
                "subreddit": name,
                "group": subreddit_group(name),
                "posts": len(subreddit_posts),
                "comments": len(subreddit_comments),
                "unique_users": len(users),
                "comments_per_post": len(subreddit_comments) / max(1, len(subreddit_posts)),
                "median_post_score": float(subreddit_posts["score"].median()) if not subreddit_posts.empty else 0,
                "mean_post_score": float(subreddit_posts["score"].mean()) if not subreddit_posts.empty else 0,
                "median_upvote_ratio": float(subreddit_posts["upvote_ratio"].median()) if not subreddit_posts.empty else 0,
                "median_comment_score": float(subreddit_comments["score"].median()) if not subreddit_comments.empty else 0,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "subreddit",
                "group",
                "posts",
                "comments",
                "unique_users",
                "comments_per_post",
            ]
        )
    summary = pd.DataFrame(rows)
    if not metrics.empty:
        summary = summary.merge(metrics, on="subreddit", how="left", suffixes=("", "_graph"))
    memberships = user_subreddit.groupby("target")["source"].nunique() if not user_subreddit.empty else pd.Series(dtype=int)
    summary["membership_users"] = summary["subreddit"].map(memberships).fillna(0).astype(int)
    summary["users_per_post"] = summary["unique_users"] / summary["posts"].clip(lower=1)
    if "edges" in summary.columns:
        summary["edges_per_post"] = summary["edges"] / summary["posts"].clip(lower=1)
        summary["edges_per_comment"] = summary["edges"] / summary["comments"].clip(lower=1)
    if "interaction_weight" in summary.columns:
        summary["interactions_per_comment"] = (
            summary["interaction_weight"] / summary["comments"].clip(lower=1)
        )
    announced = posts.groupby("subreddit")["num_comments"].sum()
    summary["announced_comments"] = summary["subreddit"].map(announced).fillna(0).astype(int)
    summary["comment_coverage_estimate"] = np.where(
        summary["announced_comments"] > 0,
        summary["comments"] / summary["announced_comments"],
        np.nan,
    )
    return summary.sort_values("comments", ascending=False).reset_index(drop=True)


def build_completeness(collections: pd.DataFrame) -> pd.DataFrame:
    if collections.empty:
        return pd.DataFrame()
    frame = collections.copy()
    frame["eligible"] = frame.get("eligible", True)
    frame["selected"] = frame.get("selected", True)
    frame["stickied"] = frame.get("stickied", False)
    group_columns = ["subreddit", "sort_origin", "time_filter"]
    rows = []
    for keys, group in frame.groupby(group_columns, dropna=False):
        subreddit, sort_origin, time_filter = keys
        eligible = group[group["eligible"].fillna(False).astype(bool)]
        selected = group[group["selected"].fillna(False).astype(bool)]
        expected = (
            int(pd.to_numeric(group["sort_rank"], errors="coerce").max())
            if "sort_rank" in group.columns
            else EXPECTED_POSTS_PER_SORT
        )
        rows.append(
            {
                "subreddit": subreddit,
                "sort_origin": sort_origin,
                "time_filter": time_filter,
                "returned_posts": int(group["submission_id"].nunique()),
                "unique_posts": int(eligible["submission_id"].nunique()),
                "selected_posts": int(selected["submission_id"].nunique()),
                "excluded_stickied": int(group["stickied"].fillna(False).astype(bool).sum()),
                "expected_posts": max(1, expected),
            }
        )
    completeness = pd.DataFrame(rows)
    completeness["completion_rate"] = (
        completeness["returned_posts"] / completeness["expected_posts"]
    )
    if "absolute_window_applied" in frame.columns and frame["absolute_window_applied"].fillna(False).all():
        completeness["temporal_scope"] = "absolute_window"
    else:
        completeness["temporal_scope"] = completeness["sort_origin"].map(
            {"top": "time_filter", "controversial": "time_filter", "hot": "current", "new": "current"}
        )
    return completeness.sort_values(["subreddit", "sort_origin"]).reset_index(drop=True)


def build_overlap(user_subreddit: pd.DataFrame, subreddit_edges: pd.DataFrame) -> pd.DataFrame:
    if user_subreddit.empty:
        return pd.DataFrame()
    memberships = user_subreddit.groupby("target")["source"].apply(lambda values: set(values.astype(str))).to_dict()
    rows = []
    names = sorted(memberships)
    shared_lookup = {}
    if not subreddit_edges.empty:
        for row in subreddit_edges.itertuples(index=False):
            shared_lookup[frozenset((str(row.source), str(row.target)))] = int(row.weight)
    for index, source in enumerate(names):
        for target in names[index + 1 :]:
            source_users = memberships[source]
            target_users = memberships[target]
            shared = shared_lookup.get(frozenset((source, target)), len(source_users & target_users))
            union = len(source_users | target_users)
            minimum = min(len(source_users), len(target_users))
            source_group = subreddit_group(source)
            target_group = subreddit_group(target)
            rows.append(
                {
                    "source": source,
                    "target": target,
                    "source_group": source_group,
                    "target_group": target_group,
                    "pair_group": source_group if source_group == target_group else "Entre grupos",
                    "shared_users": shared,
                    "jaccard": shared / union if union else 0,
                    "overlap_coefficient": shared / minimum if minimum else 0,
                }
            )
    return pd.DataFrame(rows).sort_values("jaccard", ascending=False).reset_index(drop=True)


def build_participation(user_subreddit: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if user_subreddit.empty:
        return pd.DataFrame(), {}
    counts = user_subreddit.groupby("source")["target"].nunique()
    labels = counts.map(lambda value: "4+" if value >= 4 else str(value))
    distribution = labels.value_counts().reindex(["1", "2", "3", "4+"], fill_value=0).rename_axis("subreddits_joined").reset_index(name="users")
    distribution["share"] = distribution["users"] / distribution["users"].sum()
    bridge_users = counts[counts > 1]
    indicators = {
        "users_with_membership": int(len(counts)),
        "single_subreddit_users": int((counts == 1).sum()),
        "bridge_users": int(len(bridge_users)),
        "bridge_user_share": float(len(bridge_users) / len(counts)),
        "users_in_four_or_more": int((counts >= 4).sum()),
        "max_subreddits_per_user": int(counts.max()),
    }
    return distribution, indicators


def build_monthly_activity(posts: pd.DataFrame, comments: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for frame, kind in ((posts, "posts"), (comments, "comments")):
        if frame.empty:
            continue
        dates = pd.to_datetime(frame["created_utc"], unit="s", errors="coerce", utc=True)
        activity = frame.assign(month=dates.dt.strftime("%Y-%m")).dropna(subset=["month"])
        grouped = activity.groupby(["month", "subreddit"]).size().reset_index(name="count")
        grouped["content_type"] = kind
        frames.append(grouped)
    if not frames:
        return pd.DataFrame(columns=["month", "subreddit", "count", "content_type"])
    return pd.concat(frames, ignore_index=True).sort_values(["month", "subreddit", "content_type"])


def build_interaction_types(user_edges: pd.DataFrame) -> pd.DataFrame:
    if user_edges.empty:
        return pd.DataFrame()
    grouped = user_edges.groupby(["subreddit", "interaction_type"], as_index=False)["weight"].sum()
    totals = grouped.groupby("subreddit")["weight"].transform("sum")
    grouped["share"] = grouped["weight"] / totals
    return grouped.sort_values(["subreddit", "weight"], ascending=[True, False]).reset_index(drop=True)


def build_global_indicators(
    posts: pd.DataFrame,
    comments: pd.DataFrame,
    user_edges: pd.DataFrame,
    centrality: pd.DataFrame,
    overlap: pd.DataFrame,
    participation: dict,
) -> dict:
    weighted = centrality.get("weighted_degree", pd.Series(dtype=float)).astype(float)
    top_one_count = max(1, math.ceil(len(weighted) * 0.01)) if len(weighted) else 0
    weighted_total = weighted.sum()
    top_pair = overlap.iloc[0] if not overlap.empty else None
    group_overlap = overlap.groupby("pair_group")["jaccard"].mean().to_dict() if not overlap.empty else {}
    return {
        "posts": int(len(posts)),
        "comments": int(len(comments)),
        "user_user_edges": int(len(user_edges)),
        "user_user_interactions": int(user_edges.get("weight", pd.Series(dtype=float)).sum()),
        "unique_post_authors": int(posts.get("author_hash", pd.Series(dtype=str)).nunique()),
        "unique_comment_authors": int(comments.get("author_hash", pd.Series(dtype=str)).nunique()),
        "weighted_degree_gini": gini(weighted),
        "top_1pct_weighted_degree_share": float(weighted.nlargest(top_one_count).sum() / weighted_total) if weighted_total else 0,
        "top_10_weighted_degree_share": float(weighted.nlargest(10).sum() / weighted_total) if weighted_total else 0,
        "strongest_overlap_pair": f"{top_pair['source']} + {top_pair['target']}" if top_pair is not None else None,
        "strongest_overlap_jaccard": float(top_pair["jaccard"]) if top_pair is not None else 0,
        "mean_jaccard_brazil": float(group_overlap.get("Brasil", 0)),
        "mean_jaccard_international": float(group_overlap.get("Internacional", 0)),
        "mean_jaccard_cross_group": float(group_overlap.get("Entre grupos", 0)),
        "users_with_membership": 0,
        "single_subreddit_users": 0,
        "bridge_users": 0,
        "bridge_user_share": 0.0,
        "users_in_four_or_more": 0,
        "max_subreddits_per_user": 0,
        **participation,
    }


def build_variant_comparison(
    observational_summary: pd.DataFrame,
    observational_indicators: dict,
) -> tuple[pd.DataFrame, dict | None]:
    balanced_posts = read_csv("balanced/processed/posts_balanced_clean.csv")
    balanced_comments = read_csv("balanced/processed/comments_balanced_clean.csv")
    balanced_edges = read_csv("balanced/graphs/edges_user_user.csv")
    balanced_user_subreddit = read_csv("balanced/graphs/edges_user_subreddit.csv")
    balanced_subreddit_edges = read_csv("balanced/graphs/edges_subreddit_subreddit.csv")
    balanced_metrics = read_csv("balanced/metrics/metrics_by_subreddit.csv")
    balanced_centrality = read_csv("balanced/metrics/centrality_users.csv")
    if balanced_posts.empty or balanced_metrics.empty:
        return pd.DataFrame(), None

    balanced_summary = build_subreddit_summary(
        balanced_posts,
        balanced_comments,
        balanced_user_subreddit,
        balanced_metrics,
    )
    comparison_columns = [
        "subreddit",
        "posts",
        "comments",
        "unique_users",
        "comments_per_post",
        "users_per_post",
        "edges_per_post",
        "edges_per_comment",
        "density",
        "avg_clustering",
        "modularity",
        "degree_assortativity",
    ]
    available = [
        column
        for column in comparison_columns
        if column in observational_summary.columns and column in balanced_summary.columns
    ]
    comparison = observational_summary[available].merge(
        balanced_summary[available],
        on="subreddit",
        suffixes=("_observational", "_balanced"),
    )
    for metric in ["density", "avg_clustering", "modularity", "users_per_post", "edges_per_post"]:
        observed = f"{metric}_observational"
        balanced = f"{metric}_balanced"
        if observed in comparison.columns and balanced in comparison.columns:
            comparison[f"{metric}_relative_change"] = np.where(
                comparison[observed].abs() > 0,
                (comparison[balanced] - comparison[observed]) / comparison[observed].abs(),
                np.nan,
            )

    balanced_overlap = build_overlap(
        balanced_user_subreddit,
        balanced_subreddit_edges,
    )
    _, balanced_participation = build_participation(balanced_user_subreddit)
    balanced_indicators = build_global_indicators(
        balanced_posts,
        balanced_comments,
        balanced_edges,
        balanced_centrality,
        balanced_overlap,
        balanced_participation,
    )
    robustness = {
        "bridge_user_share_observational": observational_indicators.get("bridge_user_share", 0),
        "bridge_user_share_balanced": balanced_indicators.get("bridge_user_share", 0),
        "mean_jaccard_cross_group_observational": observational_indicators.get("mean_jaccard_cross_group", 0),
        "mean_jaccard_cross_group_balanced": balanced_indicators.get("mean_jaccard_cross_group", 0),
        "weighted_degree_gini_observational": observational_indicators.get("weighted_degree_gini", 0),
        "weighted_degree_gini_balanced": balanced_indicators.get("weighted_degree_gini", 0),
    }
    return comparison, robustness


def build_findings(
    summary: pd.DataFrame,
    completeness: pd.DataFrame,
    overlap: pd.DataFrame,
    interactions: pd.DataFrame,
    indicators: dict,
) -> list[dict]:
    findings = []
    if not summary.empty:
        largest = summary.sort_values("nodes", ascending=False).iloc[0]
        most_modular = summary.sort_values("modularity", ascending=False).iloc[0]
        most_clustered = summary.sort_values("avg_clustering", ascending=False).iloc[0]
        most_engaged = summary.sort_values("comments_per_post", ascending=False).iloc[0]
        findings.extend(
            [
                {
                    "title": "Escala da rede",
                    "value": f"r/{largest['subreddit']}",
                    "interpretation": f"Maior rede observada, com {int(largest['nodes']):,} nós e {int(largest['edges']):,} arestas. O tamanho aumenta a diversidade de interações, mas reduz a densidade relativa.",
                },
                {
                    "title": "Segmentação interna",
                    "value": f"{most_modular['modularity']:.3f}",
                    "interpretation": f"r/{most_modular['subreddit']} tem a maior modularidade. Isso evidencia subgrupos estruturais, sem provar polarização ideológica por si só.",
                },
                {
                    "title": "Coesão local",
                    "value": f"r/{most_clustered['subreddit']}",
                    "interpretation": f"Maior coeficiente de clusterização ({most_clustered['avg_clustering']:.3f}), indicando mais triângulos e vizinhanças localmente conectadas.",
                },
                {
                    "title": "Intensidade de discussão",
                    "value": f"{most_engaged['comments_per_post']:.1f}",
                    "interpretation": f"r/{most_engaged['subreddit']} registra mais comentários por post na amostra, uma medida de intensidade, não necessariamente de qualidade ou consenso.",
                },
            ]
        )
    if not overlap.empty:
        pair = overlap.iloc[0]
        findings.append(
            {
                "title": "Maior sobreposição",
                "value": f"{pair['jaccard']:.1%}",
                "interpretation": f"r/{pair['source']} e r/{pair['target']} formam o par mais semelhante por Jaccard, com {int(pair['shared_users']):,} usuários compartilhados.",
            }
        )
    if indicators.get("users_with_membership", 0) > 0:
        findings.append(
            {
                "title": "Usuários-ponte",
                "value": f"{indicators.get('bridge_user_share', 0):.1%}",
                "interpretation": "Parcela dos usuários presentes em mais de um subreddit. Eles conectam comunidades, mas a métrica não informa concordância política.",
            }
        )
        findings.append(
            {
                "title": "Concentração de conectividade",
                "value": f"Gini {indicators.get('weighted_degree_gini', 0):.3f}",
                "interpretation": f"O 1% superior concentra {indicators.get('top_1pct_weighted_degree_share', 0):.1%} do grau ponderado. A rede depende de poucos conectores muito ativos.",
            }
        )
    if not interactions.empty:
        comment_rows = interactions[interactions["interaction_type"] == "reply_comment"]
        if not comment_rows.empty:
            threaded = comment_rows.sort_values("share", ascending=False).iloc[0]
            findings.append(
                {
                    "title": "Discussão encadeada",
                    "value": f"{threaded['share']:.1%}",
                    "interpretation": f"r/{threaded['subreddit']} tem a maior parcela de respostas a comentários, sinal de conversas mais encadeadas na amostra.",
                }
            )
    if not completeness.empty:
        incomplete = completeness[completeness["completion_rate"] < 1]
        findings.append(
            {
                "title": "Completude da coleta",
                "value": f"{len(incomplete)} de {len(completeness)}",
                "interpretation": "Combinações subreddit–ordenação abaixo do limite solicitado. Comparações por ordenação devem considerar essas diferenças de cobertura.",
            }
        )
    return findings


def build_markdown_report(snapshot: dict) -> str:
    global_data = snapshot["global"]
    lines = [
        "# Relatório de análise das redes do Reddit",
        "",
        "## Escopo da amostra",
        "",
        f"- Posts únicos: {global_data['posts']:,}",
        f"- Comentários: {global_data['comments']:,}",
        f"- Arestas usuário–usuário: {global_data['user_user_edges']:,}",
        f"- Usuários com vínculo a subreddit: {global_data['users_with_membership']:,}",
        f"- Usuários presentes em mais de um subreddit: {global_data['bridge_users']:,} ({global_data['bridge_user_share']:.1%})",
        "",
        "## Principais resultados",
        "",
    ]
    for finding in snapshot["findings"]:
        lines.append(f"### {finding['title']}: {finding['value']}")
        lines.append("")
        lines.append(finding["interpretation"])
        lines.append("")
    lines.extend(
        [
            "## Comparação por subreddit",
            "",
            "| Subreddit | Posts | Comentários | Usuários | Comentários/post | Grau médio | Clusterização | Modularidade |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in snapshot["subreddits"]:
        lines.append(
            f"| r/{row['subreddit']} | {row['posts']:,} | {row['comments']:,} | {row['unique_users']:,} | "
            f"{row['comments_per_post']:.1f} | {row['avg_degree']:.3f} | {row['avg_clustering']:.3f} | {row['modularity']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Maiores sobreposições de audiência",
            "",
            "| Par | Usuários compartilhados | Jaccard | Coeficiente de sobreposição |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in snapshot["overlap"][:10]:
        lines.append(
            f"| r/{row['source']} + r/{row['target']} | {row['shared_users']:,} | {row['jaccard']:.2%} | {row['overlap_coefficient']:.2%} |"
        )
    if snapshot.get("comment_coverage"):
        lines.extend(
            [
                "",
                "## Cobertura estimada dos comentários",
                "",
                "| Subreddit | Anunciados | Armazenados | Cobertura estimada |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in snapshot["comment_coverage"]:
            lines.append(
                f"| r/{row['subreddit']} | {row['announced_comments']:,} | {row['stored_comments']:,} | {row['comment_coverage_estimate']:.2%} |"
            )
    if snapshot.get("robustness"):
        robustness = snapshot["robustness"]
        lines.extend(
            [
                "",
                "## Robustez: rede observacional × balanceada",
                "",
                f"- Usuários-ponte: {robustness['bridge_user_share_observational']:.2%} na observacional e {robustness['bridge_user_share_balanced']:.2%} na balanceada.",
                f"- Jaccard médio entre blocos: {robustness['mean_jaccard_cross_group_observational']:.3%} na observacional e {robustness['mean_jaccard_cross_group_balanced']:.3%} na balanceada.",
                f"- Gini do grau ponderado: {robustness['weighted_degree_gini_observational']:.3f} na observacional e {robustness['weighted_degree_gini_balanced']:.3f} na balanceada.",
            ]
        )
    lines.extend(["", "## Limites metodológicos", ""])
    lines.extend(f"- {note}" for note in snapshot["methodological_notes"])
    lines.extend(
        [
            "",
            "## Interpretação sintética",
            "",
            "Os resultados descrevem uma rede desigual, com poucos usuários altamente conectados e a maioria restrita a uma única comunidade. "
            "A separação quase total entre subreddits brasileiros e internacionais é consistente com barreiras linguísticas e de contexto, "
            "mas não constitui evidência suficiente de polarização ideológica. Modularidade elevada indica subgrupos estruturais; para atribuir "
            "sentido político a esses grupos seria necessário complementar a rede com classificação de conteúdo, enquadramento temático ou sentimento.",
            "",
        ]
    )
    return "\n".join(lines)


def run_analysis(export: bool = True) -> dict:
    posts = read_csv("processed/posts_clean.csv")
    comments = read_csv("processed/comments_clean.csv")
    collections = read_csv("raw/post_collections.csv")
    user_edges = read_csv("graphs/edges_user_user.csv")
    user_subreddit = read_csv("graphs/edges_user_subreddit.csv")
    subreddit_edges = read_csv("graphs/edges_subreddit_subreddit.csv")
    metrics = read_csv("metrics/metrics_by_subreddit.csv")
    centrality = read_csv("metrics/centrality_users.csv")

    summary = build_subreddit_summary(posts, comments, user_subreddit, metrics)
    completeness = build_completeness(collections)
    overlap = build_overlap(user_subreddit, subreddit_edges)
    participation, participation_indicators = build_participation(user_subreddit)
    monthly = build_monthly_activity(posts, comments)
    interactions = build_interaction_types(user_edges)
    indicators = build_global_indicators(posts, comments, user_edges, centrality, overlap, participation_indicators)
    findings = build_findings(summary, completeness, overlap, interactions, indicators)
    coverage = (
        summary[
            [
                "subreddit",
                "announced_comments",
                "comments",
                "comment_coverage_estimate",
            ]
        ].rename(columns={"comments": "stored_comments"})
        if "comment_coverage_estimate" in summary.columns
        else pd.DataFrame()
    )
    if not coverage.empty:
        lowest = coverage.sort_values("comment_coverage_estimate").iloc[0]
        findings.append(
            {
                "title": "Cobertura estimada de comentários",
                "value": f"{lowest['comment_coverage_estimate']:.1%}",
                "interpretation": f"r/{lowest['subreddit']} tem a menor razão entre comentários armazenados e anunciados. A taxa é aproximada, mas evidencia cobertura desigual na coleta piloto.",
            }
        )
    variant_comparison, robustness = build_variant_comparison(summary, indicators)
    if robustness:
        findings.append(
            {
                "title": "Robustez observacional × balanceada",
                "value": f"{robustness['bridge_user_share_observational']:.1%} × {robustness['bridge_user_share_balanced']:.1%}",
                "interpretation": "Comparação da proporção de usuários-ponte. Conclusões são mais robustas quando direção e magnitude permanecem semelhantes nas duas redes.",
            }
        )

    uniform_window = (
        not collections.empty
        and "absolute_window_applied" in collections.columns
        and collections["absolute_window_applied"].fillna(False).all()
    )
    temporal_note = (
        "Todas as ordenações foram filtradas pela mesma janela absoluta; top e controversial também usam time_filter=year."
        if uniform_window
        else "Na coleta piloto, top e controversial usam time_filter; hot e new são snapshots e não têm o mesmo recorte temporal."
    )

    snapshot = {
        "global": indicators,
        "subreddits": dataframe_records(summary),
        "completeness": dataframe_records(completeness),
        "overlap": dataframe_records(overlap),
        "participation": dataframe_records(participation),
        "monthly_activity": dataframe_records(monthly),
        "interaction_types": dataframe_records(interactions),
        "comment_coverage": dataframe_records(coverage),
        "variant_comparison": dataframe_records(variant_comparison),
        "robustness": robustness,
        "findings": findings,
        "methodological_notes": [
            temporal_note,
            "A cobertura de comentários é estimada porque num_comments pode incluir itens apagados, removidos ou indisponíveis à API.",
            "Modularidade e sobreposição descrevem estrutura relacional; não demonstram causalidade, ideologia ou sentimento.",
            "Usuários foram anonimizados por hash e as métricas representam apenas atividade observada na amostra.",
            "O grafo visual filtrado tem no máximo 400 nós; os indicadores por subreddit usam a rede completa agregada.",
            "Peso representa frequência de interação. Ele não é usado diretamente como distância em caminhos mínimos.",
        ],
    }

    if export:
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        summary.to_csv(ANALYSIS_DIR / "subreddit_summary.csv", index=False)
        completeness.to_csv(ANALYSIS_DIR / "collection_completeness.csv", index=False)
        overlap.to_csv(ANALYSIS_DIR / "subreddit_overlap.csv", index=False)
        participation.to_csv(ANALYSIS_DIR / "user_participation.csv", index=False)
        monthly.to_csv(ANALYSIS_DIR / "monthly_activity.csv", index=False)
        interactions.to_csv(ANALYSIS_DIR / "interaction_types.csv", index=False)
        coverage.to_csv(ANALYSIS_DIR / "comment_coverage_estimate.csv", index=False)
        variant_comparison.to_csv(ANALYSIS_DIR / "variant_comparison.csv", index=False)
        if robustness:
            pd.DataFrame([robustness]).to_csv(
                ANALYSIS_DIR / "robustness_indicators.csv", index=False
            )
        pd.DataFrame([indicators]).to_csv(ANALYSIS_DIR / "global_indicators.csv", index=False)
        (ANALYSIS_DIR / "analysis_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (ANALYSIS_DIR / "interpretation_report.md").write_text(
            build_markdown_report(snapshot), encoding="utf-8"
        )
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Analisa os dados coletados do Reddit")
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()
    snapshot = run_analysis(export=not args.no_export)
    print(json.dumps(snapshot["global"], ensure_ascii=False, indent=2))
    print("\nPrincipais achados:")
    for finding in snapshot["findings"]:
        print(f"- {finding['title']}: {finding['value']} - {finding['interpretation']}")


if __name__ == "__main__":
    main()
