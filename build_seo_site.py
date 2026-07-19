import os
import sqlite3
import logging
from pathlib import Path
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "trustmrr_deals.db"
TEMPLATES_DIR = Path(__file__).parent / "seo_site" / "templates"
PUBLIC_DIR = Path(__file__).parent / "seo_site" / "public"

def main():
    load_dotenv()
    
    # Ensure public directory exists
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    
    wiseurl_base = os.getenv("WISEURL_BASE", "https://yourdomain.com/go/")
    
    if not DB_PATH.exists():
        log.error("Database not found at %s. Have you run the ingestion script?", DB_PATH)
        return
        
    log.info("Connecting to database...")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    deals = [dict(row) for row in cur.execute("SELECT * FROM deals ORDER BY name ASC").fetchall()]
    con.close()
    
    if not deals:
        log.warning("No deals found in the database.")
        return
        
    log.info("Found %d deals. Initializing Jinja2 environment...", len(deals))
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    deal_template = env.get_template("deal.html")
    index_template = env.get_template("index.html")
    
    categorized_deals = defaultdict(list)
    
    # Generate individual deal pages
    for deal in deals:
        category = deal.get("category") or "Uncategorized"
        categorized_deals[category].append(deal)
        
        # Render HTML
        html_content = deal_template.render(
            deal=deal,
            wise_url=f"{wiseurl_base}{deal['slug']}"
        )
        
        # Save to file
        file_path = PUBLIC_DIR / f"buy-{deal['slug']}.html"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
    log.info("Successfully generated %d deal pages.", len(deals))
    
    # Sort categories alphabetically
    sorted_categories = {k: categorized_deals[k] for k in sorted(categorized_deals.keys())}
    
    # Generate Index page
    index_html = index_template.render(
        categorized_deals=sorted_categories,
        total_deals=len(deals)
    )
    
    index_path = PUBLIC_DIR / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
        
    log.info("Successfully generated index.html.")
    log.info("Programmatic SEO generation complete. Output in %s", PUBLIC_DIR)

if __name__ == "__main__":
    main()
