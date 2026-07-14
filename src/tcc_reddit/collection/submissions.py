"""Selecao das listagens de submissions."""


def get_submissions(subreddit, sort_origin: str, limit: int, time_filter: str):
    if sort_origin == "top":
        return subreddit.top(limit=limit, time_filter=time_filter)
    if sort_origin == "controversial":
        return subreddit.controversial(limit=limit, time_filter=time_filter)
    if sort_origin == "hot":
        return subreddit.hot(limit=limit)
    if sort_origin == "new":
        return subreddit.new(limit=limit)
    raise ValueError(f"Tipo de ordenacao invalido: {sort_origin}")
