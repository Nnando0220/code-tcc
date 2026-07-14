import argparse
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from itertools import combinations
from collections import defaultdict
from pathlib import Path

import praw
import pandas as pd
import networkx as nx
from tqdm import tqdm
from dotenv import load_dotenv

from .validation.data_quality import (
    anonymize_user,
    clean_text,
    validate_final_dataset,
    validate_hashes,
    validate_weight_preservation,
)
from .networks.pipeline import (
    aggregate_directed_edges,
    aggregate_undirected_edges,
    build_balanced_datasets,
    comment_coverage_by_subreddit,
    select_posts_round_robin,
)
from .settings import PROJECT_ROOT, load_config
from .collection.comments import iter_submission_comments
from .collection.reddit_client import create_reddit_client
from .collection.submissions import get_submissions
from .processing.temporal_filter import submission_exclusion_reason


# ============================================================
# 1. CONFIGURAÇÕES GERAIS
# ============================================================

load_dotenv()

CONFIG = load_config()

SUBREDDITS = list(CONFIG.subreddits)
SORTS = list(CONFIG.sorts)

# Configuração da coleta definitiva: mesma janela real para todas as ordenações.
TIME_FILTER = CONFIG.time_filter
WINDOW_DAYS = CONFIG.window_days
CANDIDATE_LIMIT_PER_SORT = CONFIG.candidates_per_sort
LIMIT_UNIQUE_POSTS_PER_SUBREDDIT = CONFIG.posts_per_subreddit

# Dataset balanceado, derivado da coleta observacional completa.
MAX_COMMENTS_PER_POST = CONFIG.balanced_comments_per_post
RANDOM_SEED = CONFIG.random_seed
COMMENT_REPLACE_MORE_LIMIT = CONFIG.replace_more_limit

RAW_DIR = str(PROJECT_ROOT / "data" / "raw" / CONFIG.run_id)
PROCESSED_DIR = str(
    PROJECT_ROOT / "data" / "processed" / CONFIG.run_id / "observational"
)
GRAPH_DIR = "data/graphs"
METRICS_DIR = "data/metrics"
BALANCED_DIR = "data/balanced"
BALANCED_PROCESSED_DIR = str(
    PROJECT_ROOT / "data" / "processed" / CONFIG.run_id / "balanced"
)
BALANCED_GRAPH_DIR = f"{BALANCED_DIR}/graphs"
BALANCED_METRICS_DIR = f"{BALANCED_DIR}/metrics"
PILOT_ARCHIVE_DIR = "data/pilots/coleta_piloto_v1"


# ============================================================
# 2. CONFIGURAÇÕES PARA VISUALIZAÇÃO NO GEPHI
# ============================================================

# Remove conexões fracas.
GEPHI_MIN_WEIGHT = CONFIG.gephi_minimum_weight

# Remove usuários com poucas conexões.
GEPHI_MIN_DEGREE = CONFIG.gephi_minimum_degree

# Mantém apenas o maior componente conectado.
GEPHI_KEEP_LARGEST_COMPONENT = CONFIG.gephi_keep_largest_component

# Limita a quantidade máxima de nós no grafo filtrado.
GEPHI_MAX_NODES = CONFIG.gephi_visualization_max_nodes

# Gera também grafos filtrados separados por subreddit.
EXPORT_BY_SUBREDDIT = CONFIG.export_by_subreddit


def configure(config):
    """Aplica a configuracao externa durante a migracao do pipeline legado."""
    global CONFIG
    global SUBREDDITS, SORTS, TIME_FILTER, WINDOW_DAYS
    global CANDIDATE_LIMIT_PER_SORT, LIMIT_UNIQUE_POSTS_PER_SUBREDDIT
    global MAX_COMMENTS_PER_POST, RANDOM_SEED, COMMENT_REPLACE_MORE_LIMIT
    global GEPHI_MIN_WEIGHT, GEPHI_MIN_DEGREE, GEPHI_KEEP_LARGEST_COMPONENT
    global GEPHI_MAX_NODES, EXPORT_BY_SUBREDDIT
    global RAW_DIR, PROCESSED_DIR, BALANCED_PROCESSED_DIR

    CONFIG = config
    SUBREDDITS = list(config.subreddits)
    SORTS = list(config.sorts)
    TIME_FILTER = config.time_filter
    WINDOW_DAYS = config.window_days
    CANDIDATE_LIMIT_PER_SORT = config.candidates_per_sort
    LIMIT_UNIQUE_POSTS_PER_SUBREDDIT = config.posts_per_subreddit
    MAX_COMMENTS_PER_POST = config.balanced_comments_per_post
    RANDOM_SEED = config.random_seed
    COMMENT_REPLACE_MORE_LIMIT = config.replace_more_limit
    GEPHI_MIN_WEIGHT = config.gephi_minimum_weight
    GEPHI_MIN_DEGREE = config.gephi_minimum_degree
    GEPHI_KEEP_LARGEST_COMPONENT = config.gephi_keep_largest_component
    GEPHI_MAX_NODES = config.gephi_visualization_max_nodes
    EXPORT_BY_SUBREDDIT = config.export_by_subreddit
    RAW_DIR = str(PROJECT_ROOT / "data" / "raw" / config.run_id)
    PROCESSED_DIR = str(
        PROJECT_ROOT / "data" / "processed" / config.run_id / "observational"
    )
    BALANCED_PROCESSED_DIR = str(
        PROJECT_ROOT / "data" / "processed" / config.run_id / "balanced"
    )


# ============================================================
# 3. FUNÇÕES AUXILIARES
# ============================================================

def create_directories():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(GRAPH_DIR, exist_ok=True)
    os.makedirs(METRICS_DIR, exist_ok=True)
    os.makedirs(f"{GRAPH_DIR}/by_subreddit", exist_ok=True)
    os.makedirs(BALANCED_PROCESSED_DIR, exist_ok=True)
    os.makedirs(BALANCED_GRAPH_DIR, exist_ok=True)
    os.makedirs(BALANCED_METRICS_DIR, exist_ok=True)
    os.makedirs(f"{BALANCED_GRAPH_DIR}/by_subreddit", exist_ok=True)


def archive_existing_pilot():
    raw_path = Path(RAW_DIR)
    archive_path = Path(PILOT_ARCHIVE_DIR)
    source_files = list(raw_path.glob("*")) if raw_path.exists() else []
    if not source_files or archive_path.exists():
        return False
    archive_path.mkdir(parents=True, exist_ok=False)
    for source in source_files:
        if source.is_file():
            shutil.copy2(source, archive_path / source.name)
    manifest = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "source": str(raw_path),
        "purpose": "Preservação imutável da coleta piloto antes da coleta definitiva.",
        "files": sorted(path.name for path in source_files if path.is_file()),
    }
    (archive_path / "archive_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Coleta anterior preservada em {archive_path}")
    return True


def safe_filename(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))


def normalize_gexf_value(value):
    if pd.isna(value):
        return ""

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def export_gexf_from_gephi_tables(
    df_nodes,
    df_edges,
    output_path,
    directed=False
):
    graph = nx.DiGraph() if directed else nx.Graph()

    for _, row in df_nodes.iterrows():
        node_id = str(row["Id"])
        attributes = {
            column: normalize_gexf_value(row[column])
            for column in df_nodes.columns
            if column != "Id"
        }
        graph.add_node(node_id, **attributes)

    for index, row in df_edges.iterrows():
        source = str(row["Source"])
        target = str(row["Target"])
        attributes = {
            column: normalize_gexf_value(row[column])
            for column in df_edges.columns
            if column not in {"Source", "Target", "Type"}
        }

        if "Weight" in attributes:
            attributes["weight"] = attributes["Weight"]

        graph.add_edge(source, target, id=str(index), **attributes)

    nx.write_gexf(graph, output_path)
    graph_check = nx.read_gexf(output_path)
    if graph_check.number_of_edges() != len(df_edges):
        raise ValueError(
            f"GEXF inválido em {output_path}: "
            f"{graph_check.number_of_edges()} arestas gravadas para "
            f"{len(df_edges)} linhas agregadas."
        )
    print(output_path)

    return output_path


# ============================================================
# 4. COLETA DOS DADOS
# ============================================================

def collect_reddit_data():
    reddit = create_reddit_client()
    posts_by_id = {}
    comments = []
    post_collections = []

    collection_end = datetime.now(timezone.utc)
    collection_start = collection_end - timedelta(days=WINDOW_DAYS)
    collected_at = collection_end.isoformat()
    seen_comments = set()

    for subreddit_name in SUBREDDITS:
        print(f"\nColetando subreddit: r/{subreddit_name}")
        subreddit = reddit.subreddit(subreddit_name)
        candidates = {}

        for sort_origin in SORTS:
            print(f"Ordenação: {sort_origin}")
            try:
                submissions = get_submissions(
                    subreddit=subreddit,
                    sort_origin=sort_origin,
                    limit=CANDIDATE_LIMIT_PER_SORT,
                    time_filter=TIME_FILTER
                )

                for rank, submission in enumerate(tqdm(
                    submissions,
                    desc=f"{subreddit_name} - {sort_origin}"
                ), start=1):
                    submission_id = submission.id
                    created_at = datetime.fromtimestamp(
                        submission.created_utc,
                        tz=timezone.utc,
                    )
                    exclusion_reason = submission_exclusion_reason(
                        created_at=created_at,
                        window_start=collection_start,
                        window_end=collection_end,
                        stickied=bool(submission.stickied),
                    )
                    eligible = exclusion_reason is None

                    post_collections.append({
                        "submission_id": submission_id,
                        "subreddit": subreddit_name,
                        "sort_origin": sort_origin,
                        "sort_rank": rank,
                        "time_filter": TIME_FILTER if sort_origin in {"top", "controversial"} else None,
                        "time_filter_applied": sort_origin in {"top", "controversial"},
                        "absolute_window_applied": True,
                        "window_start": collection_start.isoformat(),
                        "window_end": collection_end.isoformat(),
                        "created_utc": submission.created_utc,
                        "stickied": bool(submission.stickied),
                        "eligible": eligible,
                        "selected": False,
                        "exclusion_reason": exclusion_reason,
                        "collected_at": collected_at,
                    })

                    if eligible and submission_id not in candidates:
                        candidates[submission_id] = {
                            "submission": submission,
                            "post": {
                            "submission_id": submission_id,
                            "subreddit": subreddit_name,
                            "title": submission.title,
                            "selftext": submission.selftext,
                            "author": str(submission.author) if submission.author else None,
                            "score": submission.score,
                            "upvote_ratio": submission.upvote_ratio,
                            "num_comments": submission.num_comments,
                            "created_utc": submission.created_utc,
                            "permalink": submission.permalink,
                            "url": submission.url,
                            "is_self": submission.is_self,
                            "stickied": submission.stickied,
                            "locked": submission.locked,
                            "over_18": submission.over_18,
                            "window_start": collection_start.isoformat(),
                            "window_end": collection_end.isoformat(),
                            },
                        }

            except Exception as error:
                print(f"Erro ao coletar r/{subreddit_name} em {sort_origin}: {error}")

        candidate_posts = pd.DataFrame(
            [item["post"] for item in candidates.values()]
        )
        subreddit_collections = pd.DataFrame(
            [
                row
                for row in post_collections
                if row["subreddit"] == subreddit_name
            ]
        )
        if candidate_posts.empty:
            print(f"Nenhum post elegível encontrado em r/{subreddit_name}.")
            continue

        selected_ids = select_posts_round_robin(
            subreddit_posts=candidate_posts,
            subreddit_collections=subreddit_collections,
            target=LIMIT_UNIQUE_POSTS_PER_SUBREDDIT,
            sorts=SORTS,
        )
        selected_set = set(selected_ids)
        for row in post_collections:
            if row["subreddit"] == subreddit_name:
                row["selected"] = row["submission_id"] in selected_set

        print(
            f"Posts únicos elegíveis: {len(candidate_posts)}; "
            f"selecionados: {len(selected_ids)}/{LIMIT_UNIQUE_POSTS_PER_SUBREDDIT}"
        )

        for submission_id in tqdm(
            selected_ids,
            desc=f"{subreddit_name} - comentários",
        ):
            candidate = candidates[submission_id]
            submission = candidate["submission"]
            post_data = candidate["post"].copy()
            origins = sorted(
                {
                    row["sort_origin"]
                    for row in post_collections
                    if row["submission_id"] == submission_id and row["eligible"]
                }
            )
            post_data["sort_origins"] = "|".join(origins)
            post_data["comments_announced"] = int(submission.num_comments)
            retrieved_comments = 0

            try:
                for comment in iter_submission_comments(
                    submission,
                    replace_more_limit=COMMENT_REPLACE_MORE_LIMIT,
                ):
                    if comment.id in seen_comments:
                        continue
                    seen_comments.add(comment.id)
                    retrieved_comments += 1
                    comments.append({
                        "comment_id": comment.id,
                        "submission_id": submission_id,
                        "parent_id": comment.parent_id,
                        "link_id": comment.link_id,
                        "subreddit": subreddit_name,
                        "body": comment.body,
                        "author": str(comment.author) if comment.author else None,
                        "score": comment.score,
                        "created_utc": comment.created_utc,
                        "depth": getattr(comment, "depth", None),
                        "is_submitter": comment.is_submitter,
                    })
            except Exception as error:
                print(f"Erro ao coletar comentários do post {submission_id}: {error}")

            post_data["comments_retrieved"] = retrieved_comments
            post_data["comment_coverage_estimate"] = (
                retrieved_comments / submission.num_comments
                if submission.num_comments
                else None
            )
            posts_by_id[submission_id] = post_data

    df_posts = pd.DataFrame(list(posts_by_id.values()))
    df_comments = pd.DataFrame(comments)
    df_collections = pd.DataFrame(post_collections)

    return df_posts, df_comments, df_collections


def save_raw_data(df_posts, df_comments, df_collections):
    df_posts.to_parquet(f"{RAW_DIR}/posts_raw.parquet", index=False)
    df_comments.to_parquet(f"{RAW_DIR}/comments_raw.parquet", index=False)
    df_collections.to_parquet(f"{RAW_DIR}/post_collections.parquet", index=False)

    print(f"\nDados brutos salvos em {RAW_DIR}/")


def read_table_with_fallback(stem):
    parquet_path = f"{stem}.parquet"
    csv_path = f"{stem}.csv"
    if os.path.exists(parquet_path):
        return pd.read_parquet(parquet_path)
    if os.path.exists(csv_path):
        return pd.read_csv(csv_path, low_memory=False)
    raise FileNotFoundError(
        f"Nenhum arquivo encontrado para {stem} (.parquet ou .csv)."
    )


# ============================================================
# 5. LIMPEZA E ANONIMIZAÇÃO
# ============================================================

def clean_and_process_data():
    df_posts = read_table_with_fallback(f"{RAW_DIR}/posts_raw")
    df_comments = read_table_with_fallback(f"{RAW_DIR}/comments_raw")

    df_posts = df_posts.drop_duplicates(subset=["submission_id"])
    df_comments = df_comments.drop_duplicates(subset=["comment_id"])

    valid_posts = set(df_posts["submission_id"])
    df_comments = df_comments[df_comments["submission_id"].isin(valid_posts)]

    df_posts["title_clean"] = df_posts["title"].apply(clean_text)
    df_posts["selftext_clean"] = df_posts["selftext"].apply(clean_text)
    df_comments["body_clean"] = df_comments["body"].apply(clean_text)

    df_posts["author_hash"] = df_posts["author"].apply(anonymize_user)
    df_comments["author_hash"] = df_comments["author"].apply(anonymize_user)

    validate_hashes("posts", df_posts)
    validate_hashes("comments", df_comments)

    # Remove autores reais do dataset tratado.
    df_posts = df_posts.drop(columns=["author"])
    df_comments = df_comments.drop(columns=["author"])

    df_posts.to_parquet(f"{PROCESSED_DIR}/posts.parquet", index=False)
    df_comments.to_parquet(f"{PROCESSED_DIR}/comments.parquet", index=False)

    print("\nDados tratados salvos em data/processed/")

    return df_posts, df_comments


def create_balanced_dataset(df_posts, df_comments, df_collections):
    balanced_posts, balanced_comments, manifest = build_balanced_datasets(
        df_posts=df_posts,
        df_comments=df_comments,
        df_collections=df_collections,
        target_posts_per_subreddit=LIMIT_UNIQUE_POSTS_PER_SUBREDDIT,
        max_comments_per_post=MAX_COMMENTS_PER_POST,
        seed=RANDOM_SEED,
        sorts=SORTS,
    )
    balanced_posts.to_parquet(
        f"{BALANCED_PROCESSED_DIR}/posts.parquet", index=False
    )
    balanced_comments.to_parquet(
        f"{BALANCED_PROCESSED_DIR}/comments.parquet", index=False
    )
    manifest.to_csv(
        f"{BALANCED_PROCESSED_DIR}/sampling_manifest.csv", index=False
    )
    coverage = comment_coverage_by_subreddit(df_posts, df_comments)
    coverage.to_csv(f"{METRICS_DIR}/comment_coverage_estimate.csv", index=False)
    print(
        "Dataset balanceado salvo em data/balanced/processed/ "
        f"({len(balanced_posts)} posts; {len(balanced_comments)} comentários)."
    )
    return balanced_posts, balanced_comments, manifest


# ============================================================
# 6. CRIAÇÃO DAS REDES COMPLETAS
# ============================================================

def build_user_user_edges(df_posts, df_comments, output_dir=GRAPH_DIR):
    comment_to_author = dict(
        zip(df_comments["comment_id"], df_comments["author_hash"])
    )

    post_to_author = dict(
        zip(df_posts["submission_id"], df_posts["author_hash"])
    )

    edges = []

    for _, row in df_comments.iterrows():
        source_user = row["author_hash"]

        if source_user is None:
            continue

        parent_id = str(row["parent_id"])

        # Caso 1: comentário respondeu outro comentário.
        if parent_id.startswith("t1_"):
            parent_comment_id = parent_id.replace("t1_", "")
            target_user = comment_to_author.get(parent_comment_id)
            interaction_type = "reply_comment"

        # Caso 2: comentário respondeu diretamente ao post.
        elif parent_id.startswith("t3_"):
            parent_post_id = parent_id.replace("t3_", "")
            target_user = post_to_author.get(parent_post_id)
            interaction_type = "reply_post"

        else:
            continue

        if target_user and target_user != source_user:
            edges.append({
                "source": source_user,
                "target": target_user,
                "subreddit": row["subreddit"],
                "submission_id": row["submission_id"],
                "interaction_type": interaction_type,
                "weight": 1
            })

    df_edges = pd.DataFrame(edges)

    if df_edges.empty:
        df_edges = pd.DataFrame(
            columns=[
                "source",
                "target",
                "subreddit",
                "submission_id",
                "interaction_type",
                "weight"
            ]
        )
    else:
        df_edges = df_edges.groupby(
            [
                "source",
                "target",
                "subreddit",
                "submission_id",
                "interaction_type",
            ],
            as_index=False
        )["weight"].sum()

    os.makedirs(output_dir, exist_ok=True)
    df_directed = aggregate_directed_edges(df_edges)
    df_undirected = aggregate_undirected_edges(df_edges)
    validate_weight_preservation(df_edges, df_directed, df_undirected)
    df_edges.to_csv(f"{output_dir}/edges_user_user_detailed.csv", index=False)
    # Compatibilidade: este arquivo continua detalhado e auditável.
    df_edges.to_csv(f"{output_dir}/edges_user_user.csv", index=False)
    df_directed.to_csv(f"{output_dir}/edges_user_user_directed.csv", index=False)
    df_undirected.to_csv(f"{output_dir}/edges_user_user_undirected.csv", index=False)

    print(
        f"Rede usuário-usuário salva em {output_dir}: "
        f"{len(df_edges)} linhas detalhadas, "
        f"{len(df_directed)} arestas dirigidas e "
        f"{len(df_undirected)} arestas não dirigidas."
    )

    return df_edges


def build_user_subreddit_edges(df_posts, df_comments, output_dir=GRAPH_DIR):
    post_participation = df_posts.dropna(subset=["author_hash"])[
        ["author_hash", "subreddit", "submission_id"]
    ].copy()

    post_participation["interaction_type"] = "post"
    post_participation["interaction_id"] = post_participation["submission_id"]

    comment_participation = df_comments.dropna(subset=["author_hash"])[
        ["author_hash", "subreddit", "comment_id"]
    ].copy()

    comment_participation["interaction_type"] = "comment"
    comment_participation["interaction_id"] = comment_participation["comment_id"]

    post_participation = post_participation[
        ["author_hash", "subreddit", "interaction_type", "interaction_id"]
    ]

    comment_participation = comment_participation[
        ["author_hash", "subreddit", "interaction_type", "interaction_id"]
    ]

    df_participation = pd.concat(
        [post_participation, comment_participation],
        ignore_index=True
    )

    df_user_subreddit = df_participation.groupby(
        ["author_hash", "subreddit"],
        as_index=False
    ).agg(
        weight=("interaction_id", "count")
    )

    df_user_subreddit = df_user_subreddit.rename(columns={
        "author_hash": "source",
        "subreddit": "target"
    })

    os.makedirs(output_dir, exist_ok=True)
    df_user_subreddit.to_csv(
        f"{output_dir}/edges_user_subreddit.csv",
        index=False
    )

    print("Rede usuário-subreddit salva em data/graphs/edges_user_subreddit.csv")

    return df_user_subreddit


def build_subreddit_subreddit_edges(df_user_subreddit, output_dir=GRAPH_DIR):
    user_to_subreddits = df_user_subreddit.groupby("source")["target"].apply(set)

    subreddit_edges = defaultdict(int)

    for _, subreddits in user_to_subreddits.items():
        if len(subreddits) < 2:
            continue

        for sub_a, sub_b in combinations(sorted(subreddits), 2):
            subreddit_edges[(sub_a, sub_b)] += 1

    rows = []

    for (source, target), weight in subreddit_edges.items():
        rows.append({
            "source": source,
            "target": target,
            "weight": weight
        })

    df_edges_subreddit = pd.DataFrame(rows)

    if df_edges_subreddit.empty:
        df_edges_subreddit = pd.DataFrame(
            columns=["source", "target", "weight"]
        )

    os.makedirs(output_dir, exist_ok=True)
    df_edges_subreddit.to_csv(
        f"{output_dir}/edges_subreddit_subreddit.csv",
        index=False
    )

    print("Rede subreddit-subreddit salva em data/graphs/edges_subreddit_subreddit.csv")

    return df_edges_subreddit


# ============================================================
# 7. EXPORTAÇÃO PARA GEPHI
# ============================================================

def export_gephi_complete_user_user(
    df_edges_user_user,
    output_dir=GRAPH_DIR,
):
    """
    Exporta a rede completa usuário-usuário para Gephi.
    Essa versão pode ficar grande, mas serve como base completa.
    """

    if df_edges_user_user.empty:
        print("Não há arestas usuário-usuário para exportar ao Gephi.")
        return None, None

    df_directed = aggregate_directed_edges(df_edges_user_user)
    df_undirected = aggregate_undirected_edges(df_edges_user_user)
    if df_directed.empty:
        print("Após limpeza, não restaram arestas para exportação completa.")
        return None, None

    df_edges_gephi = df_directed.rename(columns={
        "source": "Source",
        "target": "Target",
        "weight": "Weight",
        "subreddits": "Subreddits",
        "interaction_types": "InteractionTypes",
    })
    df_edges_gephi["Type"] = "Directed"
    df_edges_gephi = df_edges_gephi[
        ["Source", "Target", "Type", "Weight", "Subreddits", "InteractionTypes"]
    ]

    users = sorted(
        set(df_edges_gephi["Source"].dropna())
        | set(df_edges_gephi["Target"].dropna())
    )

    df_nodes_gephi = pd.DataFrame({
        "Id": users,
        "Label": [f"User_{i + 1}" for i in range(len(users))],
        "NodeType": "user"
    })

    os.makedirs(output_dir, exist_ok=True)
    nodes_path = f"{output_dir}/gephi_nodes_user_user_complete.csv"
    edges_path = f"{output_dir}/gephi_edges_user_user_complete.csv"
    gexf_path = f"{output_dir}/gephi_user_user_complete.gexf"
    corrected_path = f"{output_dir}/gephi_user_user_complete_corrected.gexf"

    df_nodes_gephi.to_csv(nodes_path, index=False)
    df_edges_gephi.to_csv(edges_path, index=False)
    export_gexf_from_gephi_tables(
        df_nodes=df_nodes_gephi,
        df_edges=df_edges_gephi,
        output_path=gexf_path,
        directed=True
    )
    shutil.copyfile(gexf_path, corrected_path)

    df_undirected_gephi = df_undirected.rename(columns={
        "node_a": "Source",
        "node_b": "Target",
        "weight": "Weight",
        "subreddits": "Subreddits",
        "interaction_types": "InteractionTypes",
    })
    df_undirected_gephi["Type"] = "Undirected"
    df_undirected_gephi = df_undirected_gephi[
        ["Source", "Target", "Type", "Weight", "Subreddits", "InteractionTypes"]
    ]
    undirected_edges_path = f"{output_dir}/gephi_edges_user_user_undirected.csv"
    undirected_gexf_path = f"{output_dir}/gephi_user_user_undirected_corrected.gexf"
    df_undirected_gephi.to_csv(undirected_edges_path, index=False)
    export_gexf_from_gephi_tables(
        df_nodes=df_nodes_gephi,
        df_edges=df_undirected_gephi,
        output_path=undirected_gexf_path,
        directed=False,
    )

    print("\nArquivos completos para Gephi gerados:")
    print(nodes_path)
    print(edges_path)
    print(gexf_path)
    print(corrected_path)
    print(undirected_gexf_path)

    return df_nodes_gephi, df_edges_gephi


def export_gephi_user_user_filtered(
    df_edges_user_user,
    prefix="user_user_filtered",
    min_weight=2,
    min_degree=2,
    keep_largest_component=True,
    max_nodes=400,
    subreddit=None,
    output_dir=GRAPH_DIR
):
    """
    Gera arquivos CSV de nós e arestas filtrados para visualização no Gephi.
    Mantém os dados completos intactos e cria uma versão menor para visualização.
    """

    if df_edges_user_user.empty:
        print("Não há arestas usuário-usuário para exportar ao Gephi.")
        return None, None

    df = df_edges_user_user.copy()

    if subreddit is not None:
        df = df[df["subreddit"] == subreddit].copy()

    if df.empty:
        print(f"Nenhum dado encontrado para o filtro: {subreddit}")
        return None, None

    df = df.dropna(subset=["source", "target"])
    df = df[df["source"] != df["target"]]

    if df.empty:
        print("Após remover dados inválidos, não restaram arestas.")
        return None, None

    # Para visualização de grupos, converte para grafo não direcionado.
    # Assim A-B e B-A viram a mesma conexão visual.
    df["Source"] = df.apply(
        lambda row: min(row["source"], row["target"]),
        axis=1
    )

    df["Target"] = df.apply(
        lambda row: max(row["source"], row["target"]),
        axis=1
    )

    df_gephi = df.groupby(
        ["Source", "Target"],
        as_index=False
    ).agg(
        Weight=("weight", "sum"),
        Subreddits=("subreddit", lambda values: "|".join(sorted(set(map(str, values))))),
        InteractionTypes=("interaction_type", lambda values: "|".join(sorted(set(map(str, values)))))
    )

    df_gephi = df_gephi[df_gephi["Weight"] >= min_weight].copy()

    if df_gephi.empty:
        print(
            f"Nenhuma aresta restou após aplicar min_weight={min_weight}. "
            "Reduza GEPHI_MIN_WEIGHT."
        )
        return None, None

    G = nx.from_pandas_edgelist(
        df_gephi,
        source="Source",
        target="Target",
        edge_attr=["Weight", "Subreddits", "InteractionTypes"],
        create_using=nx.Graph()
    )

    low_degree_nodes = [
        node for node, degree in dict(G.degree()).items()
        if degree < min_degree
    ]

    G.remove_nodes_from(low_degree_nodes)

    if G.number_of_nodes() == 0:
        print(
            f"Nenhum nó restou após aplicar min_degree={min_degree}. "
            "Reduza GEPHI_MIN_DEGREE."
        )
        return None, None

    if keep_largest_component and G.number_of_nodes() > 0:
        largest_component = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_component).copy()

    if max_nodes is not None and G.number_of_nodes() > max_nodes:
        top_nodes = sorted(
            G.degree(weight="Weight"),
            key=lambda item: item[1],
            reverse=True
        )[:max_nodes]

        selected_nodes = [node for node, _ in top_nodes]
        G = G.subgraph(selected_nodes).copy()

    selected_nodes = set(G.nodes())

    df_edges_filtered = df_gephi[
        df_gephi["Source"].isin(selected_nodes)
        & df_gephi["Target"].isin(selected_nodes)
    ].copy()

    df_edges_filtered["Type"] = "Undirected"

    df_edges_filtered = df_edges_filtered[
        ["Source", "Target", "Type", "Weight", "Subreddits", "InteractionTypes"]
    ]

    degree = dict(G.degree())
    weighted_degree = dict(G.degree(weight="Weight"))

    nodes_sorted = sorted(
        G.nodes(),
        key=lambda node: weighted_degree.get(node, 0),
        reverse=True
    )

    df_nodes_filtered = pd.DataFrame({
        "Id": nodes_sorted,
        "Label": [f"User_{i + 1}" for i in range(len(nodes_sorted))],
        "NodeType": "user",
        "Degree": [degree.get(node, 0) for node in nodes_sorted],
        "WeightedDegree": [weighted_degree.get(node, 0) for node in nodes_sorted]
    })

    os.makedirs(output_dir, exist_ok=True)

    nodes_path = f"{output_dir}/gephi_nodes_{prefix}.csv"
    edges_path = f"{output_dir}/gephi_edges_{prefix}.csv"
    gexf_path = f"{output_dir}/gephi_{prefix}.gexf"

    df_nodes_filtered.to_csv(nodes_path, index=False)
    df_edges_filtered.to_csv(edges_path, index=False)
    export_gexf_from_gephi_tables(
        df_nodes=df_nodes_filtered,
        df_edges=df_edges_filtered,
        output_path=gexf_path,
        directed=False
    )

    print("\nArquivos filtrados para Gephi gerados:")
    print(nodes_path)
    print(edges_path)
    print(gexf_path)
    print(f"Nós filtrados: {len(df_nodes_filtered)}")
    print(f"Arestas filtradas: {len(df_edges_filtered)}")

    return df_nodes_filtered, df_edges_filtered


def export_gephi_by_subreddit(df_edges_user_user, output_dir=GRAPH_DIR):
    """
    Gera um grafo filtrado separado para cada subreddit.
    Ajuda quando o grafo geral fica visualmente poluído.
    """

    if df_edges_user_user.empty:
        print("Não há dados para gerar grafos por subreddit.")
        return

    for subreddit in sorted(df_edges_user_user["subreddit"].dropna().unique()):
        safe_name = safe_filename(subreddit)

        print(f"\nGerando grafo filtrado para r/{subreddit}...")

        export_gephi_user_user_filtered(
            df_edges_user_user=df_edges_user_user,
            prefix=f"user_user_{safe_name}",
            min_weight=1,
            min_degree=2,
            keep_largest_component=True,
            max_nodes=300,
            subreddit=subreddit,
            output_dir=f"{output_dir}/by_subreddit"
        )


def export_gephi_subreddit_graph(df_edges_subreddit, output_dir=GRAPH_DIR):
    """
    Exporta o grafo subreddit-subreddit para Gephi.
    Esse grafo é ótimo para visualização geral entre comunidades.
    """

    if df_edges_subreddit.empty:
        print("Não há arestas subreddit-subreddit para exportar.")
        return None, None

    df_edges = df_edges_subreddit.copy()

    df_edges_gephi = df_edges.rename(columns={
        "source": "Source",
        "target": "Target",
        "weight": "Weight"
    })

    df_edges_gephi["Type"] = "Undirected"

    df_edges_gephi = df_edges_gephi[
        ["Source", "Target", "Type", "Weight"]
    ]

    subreddits = sorted(
        set(df_edges_gephi["Source"].dropna())
        | set(df_edges_gephi["Target"].dropna())
    )

    df_nodes_gephi = pd.DataFrame({
        "Id": subreddits,
        "Label": subreddits,
        "NodeType": "subreddit"
    })

    os.makedirs(output_dir, exist_ok=True)
    nodes_path = f"{output_dir}/gephi_nodes_subreddit_subreddit.csv"
    edges_path = f"{output_dir}/gephi_edges_subreddit_subreddit.csv"
    gexf_path = f"{output_dir}/gephi_subreddit_subreddit.gexf"

    df_nodes_gephi.to_csv(nodes_path, index=False)
    df_edges_gephi.to_csv(edges_path, index=False)
    export_gexf_from_gephi_tables(
        df_nodes=df_nodes_gephi,
        df_edges=df_edges_gephi,
        output_path=gexf_path,
        directed=False
    )

    print("\nArquivos subreddit-subreddit para Gephi gerados:")
    print(nodes_path)
    print(edges_path)
    print(gexf_path)

    return df_nodes_gephi, df_edges_gephi


# ============================================================
# 8. MÉTRICAS DE REDE
# ============================================================

def calculate_metrics_by_subreddit(
    df_edges_user_user,
    output_dir=METRICS_DIR,
):
    metrics = []

    if df_edges_user_user.empty:
        df_metrics = pd.DataFrame()
        os.makedirs(output_dir, exist_ok=True)
        df_metrics.to_csv(f"{output_dir}/metrics_by_subreddit.csv", index=False)
        return df_metrics

    try:
        import community as community_louvain
        has_louvain = True
    except ImportError:
        has_louvain = False
        print(
            "\nBiblioteca python-louvain não encontrada. "
            "A modularidade não será calculada."
        )

    for subreddit in df_edges_user_user["subreddit"].unique():
        sub_edges = df_edges_user_user[
            df_edges_user_user["subreddit"] == subreddit
        ]

        sub_edges_undirected = aggregate_undirected_edges(sub_edges)
        G = nx.from_pandas_edgelist(
            sub_edges_undirected,
            source="node_a",
            target="node_b",
            edge_attr="weight",
            create_using=nx.Graph()
        )

        nodes = G.number_of_nodes()
        edges = G.number_of_edges()

        if nodes == 0:
            continue

        density = nx.density(G)
        avg_degree = sum(dict(G.degree()).values()) / nodes
        components = nx.number_connected_components(G)

        largest_component_size = 0
        if components > 0:
            largest_component_size = len(max(nx.connected_components(G), key=len))

        avg_clustering = nx.average_clustering(G) if nodes > 1 else 0
        assortativity = (
            nx.degree_assortativity_coefficient(G)
            if nodes > 2 and edges > 1
            else None
        )

        modularity = None
        communities_count = None

        if has_louvain and nodes > 1 and edges > 0:
            partition = community_louvain.best_partition(
                G,
                weight="weight",
                random_state=RANDOM_SEED,
            )
            modularity = community_louvain.modularity(
                partition,
                G,
                weight="weight"
            )
            communities_count = len(set(partition.values()))

        metrics.append({
            "subreddit": subreddit,
            "nodes": nodes,
            "edges": edges,
            "density": density,
            "avg_degree": avg_degree,
            "connected_components": components,
            "largest_component_size": largest_component_size,
            "avg_clustering": avg_clustering,
            "degree_assortativity": assortativity,
            "interaction_weight": int(sub_edges["weight"].sum()),
            "modularity": modularity,
            "communities_count": communities_count
        })

    df_metrics = pd.DataFrame(metrics)

    os.makedirs(output_dir, exist_ok=True)
    df_metrics.to_csv(f"{output_dir}/metrics_by_subreddit.csv", index=False)

    print("Métricas por subreddit salvas em data/metrics/metrics_by_subreddit.csv")

    return df_metrics


def calculate_global_centrality(
    df_edges_user_user,
    output_dir=METRICS_DIR,
):
    if df_edges_user_user.empty:
        df_centrality = pd.DataFrame()
        os.makedirs(output_dir, exist_ok=True)
        df_centrality.to_csv(f"{output_dir}/centrality_users.csv", index=False)
        return df_centrality

    df_undirected = aggregate_undirected_edges(df_edges_user_user)
    G = nx.from_pandas_edgelist(
        df_undirected,
        source="node_a",
        target="node_b",
        edge_attr="weight",
        create_using=nx.Graph()
    )

    if G.number_of_nodes() == 0:
        df_centrality = pd.DataFrame()
        os.makedirs(output_dir, exist_ok=True)
        df_centrality.to_csv(f"{output_dir}/centrality_users.csv", index=False)
        return df_centrality

    degree_centrality = nx.degree_centrality(G)
    weighted_degree = dict(G.degree(weight="weight"))

    if G.number_of_nodes() > 100:
        sample_size = min(CONFIG.betweenness_sample_size, G.number_of_nodes())
        betweenness = nx.betweenness_centrality(
            G,
            k=sample_size,
            seed=CONFIG.random_seed,
        )
    else:
        betweenness = nx.betweenness_centrality(G)

    rows = []

    for node in G.nodes():
        rows.append({
            "user_hash": node,
            "degree_centrality": degree_centrality.get(node, 0),
            "weighted_degree": weighted_degree.get(node, 0),
            "betweenness_centrality": betweenness.get(node, 0)
        })

    df_centrality = pd.DataFrame(rows)

    df_centrality = df_centrality.sort_values(
        by="degree_centrality",
        ascending=False
    )

    os.makedirs(output_dir, exist_ok=True)
    df_centrality.to_csv(f"{output_dir}/centrality_users.csv", index=False)

    print("Centralidade dos usuários salva em data/metrics/centrality_users.csv")

    return df_centrality


def calculate_directed_centrality(
    df_edges_user_user,
    output_dir=METRICS_DIR,
):
    df_directed = aggregate_directed_edges(df_edges_user_user)
    columns = [
        "user_hash",
        "in_degree",
        "out_degree",
        "in_degree_centrality",
        "out_degree_centrality",
        "pagerank",
    ]
    if df_directed.empty:
        result = pd.DataFrame(columns=columns)
    else:
        graph = nx.from_pandas_edgelist(
            df_directed,
            source="source",
            target="target",
            edge_attr="weight",
            create_using=nx.DiGraph(),
        )
        in_degree = dict(graph.in_degree(weight="weight"))
        out_degree = dict(graph.out_degree(weight="weight"))
        in_centrality = nx.in_degree_centrality(graph)
        out_centrality = nx.out_degree_centrality(graph)
        pagerank = nx.pagerank(graph, weight="weight")
        result = pd.DataFrame(
            [
                {
                    "user_hash": node,
                    "in_degree": in_degree.get(node, 0),
                    "out_degree": out_degree.get(node, 0),
                    "in_degree_centrality": in_centrality.get(node, 0),
                    "out_degree_centrality": out_centrality.get(node, 0),
                    "pagerank": pagerank.get(node, 0),
                }
                for node in graph.nodes()
            ]
        ).sort_values("pagerank", ascending=False)
    os.makedirs(output_dir, exist_ok=True)
    result.to_csv(f"{output_dir}/centrality_users_directed.csv", index=False)
    return result


# ============================================================
# 9. VALIDAÇÃO FINAL
# ============================================================

def validate_outputs(
    df_posts,
    df_comments,
    df_edges_user_user,
    df_user_subreddit,
    df_edges_subreddit,
    df_metrics
):
    print("\n==============================")
    print("RESUMO DA COLETA E ANÁLISE")
    print("==============================")

    print(f"Posts coletados: {len(df_posts)}")
    print(f"Comentários coletados: {len(df_comments)}")
    print(f"Arestas usuário-usuário: {len(df_edges_user_user)}")
    print(f"Arestas usuário-subreddit: {len(df_user_subreddit)}")
    print(f"Arestas subreddit-subreddit: {len(df_edges_subreddit)}")

    if not df_posts.empty:
        print("\nPosts por subreddit:")
        print(df_posts["subreddit"].value_counts())

    if not df_comments.empty:
        print("\nComentários por subreddit:")
        print(df_comments["subreddit"].value_counts())

    if not df_metrics.empty:
        print("\nMétricas por subreddit:")
        print(df_metrics)
    else:
        print("\nNenhuma métrica foi calculada. Verifique se existem interações suficientes.")

    print("\nArquivos principais para importar no Gephi:")
    print(f"{GRAPH_DIR}/gephi_user_user_filtered.gexf")
    print(f"{GRAPH_DIR}/gephi_subreddit_subreddit.gexf")
    print(f"{GRAPH_DIR}/gephi_user_user_complete.gexf")
    print("\nCSVs equivalentes, se quiser importar manualmente:")
    print(f"{GRAPH_DIR}/gephi_nodes_user_user_filtered.csv")
    print(f"{GRAPH_DIR}/gephi_edges_user_user_filtered.csv")
    print(f"{GRAPH_DIR}/gephi_nodes_subreddit_subreddit.csv")
    print(f"{GRAPH_DIR}/gephi_edges_subreddit_subreddit.csv")


def process_network_variant(
    df_posts,
    df_comments,
    graph_dir,
    metrics_dir,
    export_by_subreddit=True,
):
    df_edges = build_user_user_edges(
        df_posts,
        df_comments,
        output_dir=graph_dir,
    )
    validate_final_dataset(
        df_posts,
        df_comments,
        df_edges,
        expected_subreddits=SUBREDDITS,
        expected_posts_per_subreddit=LIMIT_UNIQUE_POSTS_PER_SUBREDDIT,
    )
    df_user_subreddit = build_user_subreddit_edges(
        df_posts,
        df_comments,
        output_dir=graph_dir,
    )
    df_edges_subreddit = build_subreddit_subreddit_edges(
        df_user_subreddit,
        output_dir=graph_dir,
    )
    df_metrics = calculate_metrics_by_subreddit(
        df_edges,
        output_dir=metrics_dir,
    )
    calculate_global_centrality(df_edges, output_dir=metrics_dir)
    calculate_directed_centrality(df_edges, output_dir=metrics_dir)
    export_gephi_complete_user_user(df_edges, output_dir=graph_dir)
    export_gephi_user_user_filtered(
        df_edges_user_user=df_edges,
        prefix="user_user_filtered",
        min_weight=GEPHI_MIN_WEIGHT,
        min_degree=GEPHI_MIN_DEGREE,
        keep_largest_component=GEPHI_KEEP_LARGEST_COMPONENT,
        max_nodes=GEPHI_MAX_NODES,
        subreddit=None,
        output_dir=graph_dir,
    )
    if export_by_subreddit:
        export_gephi_by_subreddit(df_edges, output_dir=graph_dir)
    export_gephi_subreddit_graph(df_edges_subreddit, output_dir=graph_dir)
    return df_edges, df_user_subreddit, df_edges_subreddit, df_metrics


def parse_args():
    parser = argparse.ArgumentParser(
        description="Coleta e análise comparativa de redes do Reddit"
    )
    parser.add_argument(
        "--reprocess-existing",
        action="store_true",
        help="Reutiliza data/raw sem acessar novamente as listagens do Reddit.",
    )
    return parser.parse_args()


# ============================================================
# 10. EXECUÇÃO PRINCIPAL
# ============================================================

def main(reprocess_existing=None):
    args = (
        parse_args()
        if reprocess_existing is None
        else argparse.Namespace(reprocess_existing=bool(reprocess_existing))
    )
    create_directories()

    if args.reprocess_existing:
        print("\nReprocessando a coleta existente sem acessar o Reddit...")
        # A leitura aceita tanto os Parquet quanto os CSVs da coleta piloto.
        read_table_with_fallback(f"{RAW_DIR}/posts_raw")
        read_table_with_fallback(f"{RAW_DIR}/comments_raw")
        df_collections = read_table_with_fallback(
            f"{RAW_DIR}/post_collections"
        )
    else:
        raw_manifest = Path(RAW_DIR) / "manifest.json"
        if raw_manifest.exists():
            raise ValueError(
                f"O run_id {CONFIG.run_id} ja possui dados brutos registrados. "
                "Use um novo run_id para realizar outra coleta."
            )
        archive_existing_pilot()
        print("\nIniciando coleta definitiva no Reddit...")
        df_posts_raw, df_comments_raw, df_collections = collect_reddit_data()
        save_raw_data(
            df_posts=df_posts_raw,
            df_comments=df_comments_raw,
            df_collections=df_collections
        )

    print("\nIniciando limpeza e anonimização...")
    df_posts, df_comments = clean_and_process_data()

    balanced_posts, balanced_comments, _ = create_balanced_dataset(
        df_posts,
        df_comments,
        df_collections,
    )

    print("\nProcessando rede observacional...")
    (
        df_edges_user_user,
        df_user_subreddit,
        df_edges_subreddit,
        df_metrics,
    ) = process_network_variant(
        df_posts,
        df_comments,
        graph_dir=GRAPH_DIR,
        metrics_dir=METRICS_DIR,
        export_by_subreddit=EXPORT_BY_SUBREDDIT,
    )

    print("\nProcessando rede balanceada...")
    process_network_variant(
        balanced_posts,
        balanced_comments,
        graph_dir=BALANCED_GRAPH_DIR,
        metrics_dir=BALANCED_METRICS_DIR,
        export_by_subreddit=EXPORT_BY_SUBREDDIT,
    )

    validate_outputs(
        df_posts=df_posts,
        df_comments=df_comments,
        df_edges_user_user=df_edges_user_user,
        df_user_subreddit=df_user_subreddit,
        df_edges_subreddit=df_edges_subreddit,
        df_metrics=df_metrics
    )

    print("\nProcesso finalizado com sucesso.")
    print("Analise consolidada: .\\.venv\\Scripts\\python.exe scripts\\analyze.py")
    print(
        "Reprocessar sem nova coleta: "
        ".\\.venv\\Scripts\\python.exe scripts\\reprocess.py"
    )


if __name__ == "__main__":
    main()
