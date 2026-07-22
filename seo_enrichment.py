"""
seo_enrichment.py — SEO Keyword and Hashtag Enrichment Helper
=============================================================
Generates relevant, high-search-volume hashtags and SEO keywords based on 
deal category and metadata to improve discoverability across Telegram, Twitter, LinkedIn, and Medium.
"""

CATEGORY_HASHTAGS = {
    "Mobile Apps": ["#MobileApp", "#iOSApp", "#AndroidApp", "#AppStore", "#MicroSaaS"],
    "SaaS": ["#SaaS", "#MicroSaaS", "#Software", "#B2B", "#CloudSaaS"],
    "E-commerce": ["#Ecommerce", "#Shopify", "#DTC", "#OnlineBusiness", "#FBA"],
    "AI": ["#AI", "#ArtificialIntelligence", "#MachineLearning", "#AISaaS", "#GenerativeAI"],
    "Agency": ["#Agency", "#DigitalAgency", "#ServiceBusiness", "#B2B"],
    "Content": ["#ContentBusiness", "#Newsletter", "#Media", "#DigitalAssets"],
}

DEFAULT_HASHTAGS = ["#MicroAcquisition", "#StartupForSale", "#BusinessForSale", "#SideHustle", "#PassiveIncome"]


def get_seo_hashtags(category: str = "", name: str = "", limit: int = 5) -> str:
    """Generate a clean block of high-volume SEO hashtags for a deal post."""
    tags = []
    
    # 1. Category specific
    cat_lower = (category or "").lower()
    for cat_key, cat_tags in CATEGORY_HASHTAGS.items():
        if cat_key.lower() in cat_lower or cat_lower in cat_key.lower():
            for t in cat_tags:
                if t not in tags:
                    tags.append(t)
            break
            
    # 2. Name specific keyword check
    if "ai" in (name or "").lower():
        for t in ["#AI", "#AISaaS"]:
            if t not in tags:
                tags.append(t)

    # 3. Fill up with default high-search-volume tags
    for t in DEFAULT_HASHTAGS:
        if t not in tags:
            tags.append(t)

    return " ".join(tags[:limit])


def format_enriched_message(base_message: str, category: str = "", name: str = "") -> str:
    """Appends SEO keyword and hashtag block to a deal message."""
    hashtags = get_seo_hashtags(category=category, name=name, limit=5)
    return f"{base_message}\n\n{hashtags}"


if __name__ == "__main__":
    # Test SEO enrichment locally
    sample_deal = {"name": "OwnYourPics AI", "category": "Mobile Apps"}
    tags = get_seo_hashtags(sample_deal["category"], sample_deal["name"])
    print("[SEO ENRICHMENT TEST]")
    print(f"Category: {sample_deal['category']}")
    print(f"Generated Hashtags: {tags}")
