"""Testes das regras que protegem os dados derivados."""

import re

import pandas as pd
import pytest

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.networks.pipeline import (
    aggregate_directed_edges,
    aggregate_undirected_edges,
)
from tcc_reddit.validation.data_quality import (
    anonymize_user,
    clean_text,
    validate_comment_ancestors,
    validate_final_dataset,
    validate_hashes,
    validate_temporal_window,
    validate_weight_preservation,
)


@pytest.fixture
def edges():
    return pd.DataFrame(
        [
            {
                "source": "A",
                "target": "B",
                "subreddit": "brasil",
                "interaction_type": "reply_comment",
                "weight": 3,
            },
            {
                "source": "B",
                "target": "A",
                "subreddit": "brasil",
                "interaction_type": "reply_comment",
                "weight": 2,
            },
        ]
    )


@pytest.mark.parametrize(
    "value",
    [None, pd.NA, float("nan"), "nan", "None", "", "[deleted]", "AutoModerator"],
)
def test_missing_users_are_not_hashed(value):
    assert anonymize_user(value, salt="test-secret") is None


def test_valid_user_is_hashed():
    result = anonymize_user("usuario_valido", salt="test-secret")
    assert re.fullmatch(r"[0-9a-f]{64}", result)


def test_clean_text_handles_missing_values():
    assert clean_text(pd.NA) == ""
    assert clean_text(float("nan")) == ""
    assert clean_text("  Olá\nMUNDO  ") == "ola mundo"


def test_weights_are_preserved(edges):
    directed = aggregate_directed_edges(edges)
    undirected = aggregate_undirected_edges(edges)
    validate_weight_preservation(edges, directed, undirected)


def test_invalid_hash_is_rejected():
    frame = pd.DataFrame({"author_hash": ["nan", None]})
    with pytest.raises(ValueError, match="Hashes invalidos"):
        validate_hashes("comments", frame)


def test_final_dataset_rejects_orphan_comments(edges):
    valid_hash = "a" * 64
    posts = pd.DataFrame(
        [{"submission_id": "p1", "subreddit": "brasil", "author_hash": valid_hash}]
    )
    comments = pd.DataFrame(
        [{"comment_id": "c1", "submission_id": "missing", "author_hash": valid_hash}]
    )
    with pytest.raises(ValueError, match="sem post correspondente"):
        validate_final_dataset(posts, comments, edges)


def test_final_dataset_accepts_consistent_data(edges):
    valid_hash = "a" * 64
    posts = pd.DataFrame(
        [
            {
                "submission_id": "p1",
                "subreddit": "brasil",
                "author_hash": valid_hash,
                "stickied": False,
            }
        ]
    )
    comments = pd.DataFrame(
        [{"comment_id": "c1", "submission_id": "p1", "author_hash": None}]
    )
    validate_final_dataset(
        posts,
        comments,
        edges,
        expected_subreddits=["brasil"],
        expected_posts_per_subreddit=1,
    )


def test_temporal_window_rejects_outside_post():
    posts = pd.DataFrame(
        [{"created_utc": pd.Timestamp("2024-01-01", tz="UTC").timestamp()}]
    )
    with pytest.raises(ValueError, match="fora da janela temporal"):
        validate_temporal_window(
            posts,
            "2025-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        )


def test_balanced_comments_require_ancestors():
    comments = pd.DataFrame(
        [{"comment_id": "child", "parent_id": "t1_missing-parent"}]
    )
    with pytest.raises(ValueError, match="sem ancestral preservado"):
        validate_comment_ancestors(comments)
