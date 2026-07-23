"""Paletas fixas compartilhadas por variantes e formatos de exportacao."""

from __future__ import annotations

import colorsys
import hashlib


SUBREDDIT_COLORS = {
    "brasil": "#009C3B",
    "brasilivre": "#FFB703",
    "BrasildoB": "#D62828",
    "NoticiasBR": "#3A86FF",
    "politics": "#8338EC",
    "worldnews": "#00B4D8",
    "geopolitics": "#FB5607",
    "news": "#6C757D",
}

BLOCK_COLORS = {
    "Brasil": "#1B9E77",
    "Internacional": "#5E60CE",
    "Misto": "#E76F51",
}

ROLE_COLORS = {
    "central": "#E63946",
    "bridge": "#F4A261",
    "ordinary": "#457B9D",
    "peripheral": "#A8DADC",
}

NEUTRAL_EDGE = "#A8ADB4"
BACKGROUND = "#FFFFFF"


def community_color(community: int | str) -> str:
    """Retorna uma cor deterministica e suficientemente saturada."""
    digest = hashlib.sha256(str(community).encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) / 0xFFFFFFFF
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.62, 0.82)
    return "#{:02X}{:02X}{:02X}".format(
        round(red * 255), round(green * 255), round(blue * 255)
    )


def hex_to_rgb(color: str) -> dict[str, int]:
    value = color.lstrip("#")
    return {
        "r": int(value[0:2], 16),
        "g": int(value[2:4], 16),
        "b": int(value[4:6], 16),
        "a": 1.0,
    }


def color_for_node(attributes: dict, mode: str) -> str:
    if attributes.get("node_type") == "subreddit":
        return SUBREDDIT_COLORS.get(str(attributes.get("subreddit")), "#495057")
    if mode == "block":
        return BLOCK_COLORS.get(str(attributes.get("block")), "#ADB5BD")
    if mode == "community":
        return community_color(attributes.get("community_full", -1))
    if mode == "role":
        return ROLE_COLORS.get(str(attributes.get("node_role")), "#ADB5BD")
    return SUBREDDIT_COLORS.get(
        str(attributes.get("primary_subreddit")), "#ADB5BD"
    )
