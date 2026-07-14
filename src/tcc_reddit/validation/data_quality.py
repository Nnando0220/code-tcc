"""Validacoes de qualidade para os datasets e grafos do TCC."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime

import pandas as pd


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IGNORED_USERNAMES = {
    "",
    "none",
    "nan",
    "<na>",
    "[deleted]",
    "automoderator",
}


def normalize_username(username) -> str | None:
    """Normaliza um autor sem converter ausencias em usuarios artificiais."""
    if username is None or pd.isna(username):
        return None

    value = str(username).strip()
    if value.lower() in IGNORED_USERNAMES:
        return None
    return value


def anonymize_user(username, salt: str | None = None) -> str | None:
    """Pseudonimiza um autor valido com uma chave privada externa ao codigo."""
    normalized = normalize_username(username)
    if normalized is None:
        return None

    effective_salt = salt or os.getenv("TCC_HASH_SALT")
    if not effective_salt:
        raise ValueError("TCC_HASH_SALT nao definido no arquivo .env.")

    return hashlib.sha256(
        (effective_salt + normalized).encode("utf-8")
    ).hexdigest()


def clean_text(text) -> str:
    """Limpa texto ausente e produz uma representacao comparavel em ASCII."""
    if text is None or pd.isna(text):
        return ""

    normalized = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_accents).strip().lower()


def validate_hashes(frame_name: str, frame: pd.DataFrame) -> None:
    """Interrompe o pipeline quando um hash nao nulo nao for SHA-256."""
    if "author_hash" not in frame.columns:
        raise ValueError(f"Coluna author_hash ausente em {frame_name}.")

    non_null_hashes = frame["author_hash"].dropna().astype(str)
    invalid = non_null_hashes[~non_null_hashes.str.fullmatch(HASH_PATTERN)]
    if not invalid.empty:
        raise ValueError(f"Hashes invalidos em {frame_name}: {len(invalid)}")


def validate_weight_preservation(
    detailed_edges: pd.DataFrame,
    directed_edges: pd.DataFrame,
    undirected_edges: pd.DataFrame,
) -> None:
    """Confirma que as agregacoes dirigida e nao dirigida preservam o peso."""
    weights = {
        "detalhada": int(detailed_edges.get("weight", pd.Series(dtype=int)).sum()),
        "dirigida": int(directed_edges.get("weight", pd.Series(dtype=int)).sum()),
        "nao_dirigida": int(undirected_edges.get("weight", pd.Series(dtype=int)).sum()),
    }
    if len(set(weights.values())) != 1:
        raise ValueError(
            "Peso das interacoes nao foi preservado: "
            + ", ".join(f"{name}={value}" for name, value in weights.items())
        )


def validate_final_dataset(
    df_posts: pd.DataFrame,
    df_comments: pd.DataFrame,
    df_edges: pd.DataFrame,
    *,
    expected_subreddits: Iterable[str] | None = None,
    expected_posts_per_subreddit: int | None = None,
) -> None:
    """Valida chaves, referencias, autores, amostra e autointeracoes."""
    if df_posts["submission_id"].duplicated().any():
        raise ValueError("Existem posts duplicados.")
    if df_comments["comment_id"].duplicated().any():
        raise ValueError("Existem comentarios duplicados.")

    valid_posts = set(df_posts["submission_id"].astype(str))
    comment_posts = df_comments["submission_id"].astype(str)
    orphan_comments = df_comments[~comment_posts.isin(valid_posts)]
    if not orphan_comments.empty:
        raise ValueError(
            f"{len(orphan_comments)} comentarios sem post correspondente."
        )

    self_loops = df_edges[df_edges["source"] == df_edges["target"]]
    if not self_loops.empty:
        raise ValueError(f"{len(self_loops)} autointeracoes encontradas.")

    validate_hashes("posts", df_posts)
    validate_hashes("comments", df_comments)

    if expected_posts_per_subreddit is not None:
        posts_per_subreddit = (
            df_posts.groupby("subreddit")["submission_id"].nunique()
        )
        if expected_subreddits is not None:
            expected = set(expected_subreddits)
            found = set(posts_per_subreddit.index.astype(str))
            if found != expected:
                missing = sorted(expected - found)
                unexpected = sorted(found - expected)
                raise ValueError(
                    "Subreddits divergentes. "
                    f"Ausentes={missing}; inesperados={unexpected}."
                )
        invalid_counts = posts_per_subreddit[
            posts_per_subreddit != expected_posts_per_subreddit
        ]
        if not invalid_counts.empty:
            details = ", ".join(
                f"{subreddit}={count}"
                for subreddit, count in invalid_counts.items()
            )
            raise ValueError(
                "Quantidade de posts por subreddit invalida: " + details
            )

    if "stickied" in df_posts.columns and df_posts["stickied"].fillna(False).any():
        raise ValueError("Foram encontradas postagens fixadas.")


def validate_temporal_window(
    df_posts: pd.DataFrame,
    window_start: str | datetime,
    window_end: str | datetime,
) -> None:
    created = pd.to_datetime(df_posts["created_utc"], unit="s", utc=True, errors="coerce")
    start = pd.to_datetime(window_start, utc=True)
    end = pd.to_datetime(window_end, utc=True)
    invalid = df_posts[created.isna() | (created < start) | (created > end)]
    if not invalid.empty:
        raise ValueError(f"{len(invalid)} postagens fora da janela temporal.")


def validate_comment_ancestors(df_comments: pd.DataFrame) -> None:
    comment_ids = set(df_comments["comment_id"].dropna().astype(str))
    parents = df_comments["parent_id"].dropna().astype(str)
    parent_comment_ids = parents[parents.str.startswith("t1_")].str.removeprefix("t1_")
    missing = parent_comment_ids[~parent_comment_ids.isin(comment_ids)]
    if not missing.empty:
        raise ValueError(
            f"{len(missing)} comentarios balanceados sem ancestral preservado."
        )
