"""
Sakr Connect - Slider Cron Job
Fetches RSS from 4 platforms and caches in slider_cache table
Runs every 10 minutes via Windows Task Scheduler or cron
"""
import sqlite3
import pathlib
import re
import time
try:
    import requests
    import feedparser
except:
    requests = None

DB_PATH = pathlib.Path(__file__).parent.parent / "sakr_connect.db"

PLATFORMS = [
    {
        "name": "العاصمة الآن الإخبارية",
        "url": "https://elasemaalaan.com/feed/",
        "fallback_title": "أخبار العاصمة الآن",
        "fallback_image": "https://via.placeholder.com/400x200?text=ElAsema",
        "fallback_link": "https://elasemaalaan.com"
    },
    {
        "name": "المصري اليوم",
        "url": "https://www.almasryalyoum.com/rss/rss.aspx",
        "fallback_title": "أخبار المصري اليوم",
        "fallback_image": "https://via.placeholder.com/400x200?text=AlMasry",
        "fallback_link": "https://www.almasryalyoum.com"
    },
    {
        "name": "يلا كورة",
        "url": "https://www.yallakora.com/rss.aspx",
        "fallback_title": "أخبار الكرة المصرية",
        "fallback_image": "https://via.placeholder.com/400x200?text=YallaKora",
        "fallback_link": "https://www.yallakora.com"
    },
    {
        "name": "القرآن الكريم",
        "url": "https://mp3quran.net/api/quran_radio.json",
        "fallback_title": "إذاعة القرآن الكريم - بث مباشر",
        "fallback_image": "https://via.placeholder.com/400x200?text=Quran",
        "fallback_link": "https://mp3quran.net"
    }
]

def fetch_rss(platform):
    """Fetch one platform, return (title, image, link)"""
    try:
        if requests is None:
            return platform["fallback_title"], platform["fallback_image"], platform["fallback_link"]
        
        # Use a short timeout for MikroTik compatibility
        resp = requests.get(platform["url"], timeout=10, headers={"User-Agent": "SakrConnect/1.0"})
        if resp.status_code == 200:
            # Try to parse as RSS
            if "xml" in resp.headers.get("Content-Type","") or "<rss" in resp.text[:1000]:
                # Simple regex for RSS
                title_match = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", resp.text)
                if not title_match:
                    title_match = re.search(r"<title>(.*?)</title>", resp.text)
                title = title_match.group(1).strip() if title_match else platform["fallback_title"]
                
                # Try to find image
                img_match = re.search(r'<media:content[^>]+url="([^"]+)"', resp.text)
                if not img_match:
                    img_match = re.search(r'<enclosure[^>]+url="([^"]+)"', resp.text)
                image = img_match.group(1) if img_match else platform["fallback_image"]
                
                link_match = re.search(r"<link>(.*?)</link>", resp.text)
                link = link_match.group(1).strip() if link_match else platform["fallback_link"]
                
                return title[:150], image, link
            
            # For JSON (Quran)
            if "json" in resp.headers.get("Content-Type",""):
                return platform["fallback_title"], platform["fallback_image"], platform["fallback_link"]
                
    except Exception as e:
        print(f"Fetch failed for {platform['name']}: {e}")
    
    return platform["fallback_title"], platform["fallback_image"], platform["fallback_link"]

def run():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    # Ensure table exists
    cur.execute("""
    CREATE TABLE IF NOT EXISTS slider_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        title TEXT NOT NULL,
        image_url TEXT,
        link_url TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Clear old cache
    cur.execute("DELETE FROM slider_cache")
    
    for plat in PLATFORMS:
        title, image, link = fetch_rss(plat)
        cur.execute("INSERT INTO slider_cache (platform, title, image_url, link_url) VALUES (?, ?, ?, ?)",
                    (plat["name"], title, image, link))
        print(f"Cached: {plat['name']} -> {title[:40]}")
    
    conn.commit()
    conn.close()
    print("Slider cache updated")

if __name__ == "__main__":
    run()
