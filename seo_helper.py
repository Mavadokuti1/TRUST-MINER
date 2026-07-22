"""
seo_helper.py — Clean, relevant hashtag helper
===============================================
Single responsibility: given a deal's category (and optionally its name),
return 3–5 relevant, natural-looking hashtags to append to a Telegram or
Twitter post.

Design principles (explicitly NOT black-hat):
  • No keyword stuffing — capped at `limit` (default 5) tags.
  • No doorway pages, no hidden text, no spun variants.
  • Tags are topical and human-readable; they describe the deal, they do
    not attempt to game a ranking algorithm.
"""

from __future__ import annotations

# Relevant, on-topic hashtags per category. Kept short and honest.
CATEGORY_HASHTAGS: dict[str, list[str]] = {
    "saas":        ["#SaaS", "#MicroSaaS", "#Startup"],
    "ai":          ["#AI", "#AITools", "#Startup"],
    "e-commerce":  ["#Ecommerce", "#OnlineBusiness", "#DTC"],
    "ecommerce":   ["#Ecommerce", "#OnlineBusiness", "#DTC"],
    "mobile apps": ["#MobileApp", "#AppBusiness", "#Startup"],
    "mobile app":  ["#MobileApp", "#AppBusiness", "#Startup"],
    "agency":      ["#Agency", "#ServiceBusiness", "#SmallBusiness"],
    "content":     ["#ContentBusiness", "#Newsletter", "#DigitalAssets"],
    "fintech":     ["#Fintech", "#Startup", "#SaaS"],
    "health & fitness": ["#HealthTech", "#FitnessApp", "#Startup"],
    "productivity": ["#Productivity", "#SaaS", "#Startup"],
}

# Always-relevant tags for a micro-acquisition marketplace context.
BASE_HASHTAGS: list[str] = ["#MicroAcquisition", "#BusinessForSale"]


def get_hashtags(category: str = "", name: str = "", limit: int = 5) -> list[str]:
    """
    Build a de-duplicated, order-preserving list of 3–5 relevant hashtags.

    Args:
        category: The deal's category (e.g. "SaaS", "E-commerce", "AI").
        name:     The deal's name (used only for a light AI-topic hint).
        limit:    Maximum number of hashtags to return (default 5, min 3).

    Returns:
        A list of hashtag strings, e.g. ["#SaaS", "#MicroSaaS", ...].
    """
    limit = max(3, min(limit, 5))
    tags: list[str] = []

    def add(candidates: list[str]) -> None:
        for t in candidates:
            if t not in tags and len(tags) < limit:
                tags.append(t)

    cat_key = (category or "").strip().lower()
    if cat_key in CATEGORY_HASHTAGS:
        add(CATEGORY_HASHTAGS[cat_key])
    else:
        # Loose substring match so "SaaS Tools" still maps to the SaaS set.
        for key, vals in CATEGORY_HASHTAGS.items():
            if key in cat_key or cat_key in key:
                add(vals)
                break

    # Light, honest topic hint: only if the product name clearly signals AI.
    if "ai" in (name or "").lower():
        add(["#AI"])

    # Fill any remaining slots with always-relevant marketplace tags.
    add(BASE_HASHTAGS)

    return tags[:limit]


def hashtag_line(category: str = "", name: str = "", limit: int = 5) -> str:
    """Return the hashtags as a single space-separated line."""
    return " ".join(get_hashtags(category=category, name=name, limit=limit))


if __name__ == "__main__":
    for c in ("SaaS", "E-commerce", "AI", "Mobile Apps", "Unknown Niche"):
        print(f"{c:>14} -> {hashtag_line(category=c)}")
