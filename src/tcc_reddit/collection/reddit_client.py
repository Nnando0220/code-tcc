"""Criacao tardia do cliente Reddit."""

import os

import praw


def create_reddit_client() -> praw.Reddit:
    credentials = {
        "REDDIT_CLIENT_ID": os.getenv("REDDIT_CLIENT_ID"),
        "REDDIT_CLIENT_SECRET": os.getenv("REDDIT_CLIENT_SECRET"),
        "REDDIT_USER_AGENT": os.getenv("REDDIT_USER_AGENT"),
    }
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        raise ValueError("Credenciais ausentes no .env: " + ", ".join(missing))
    return praw.Reddit(
        client_id=credentials["REDDIT_CLIENT_ID"],
        client_secret=credentials["REDDIT_CLIENT_SECRET"],
        user_agent=credentials["REDDIT_USER_AGENT"],
    )
