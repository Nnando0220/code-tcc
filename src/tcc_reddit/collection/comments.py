"""Leitura integral e deduplicada das arvores de comentarios."""


def iter_submission_comments(submission, replace_more_limit=None):
    submission.comments.replace_more(limit=replace_more_limit)
    yield from submission.comments.list()
