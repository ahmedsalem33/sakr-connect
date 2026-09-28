from flask import Blueprint, jsonify
from core.db_manager import db_session
from sqlalchemy import text

slider_bp = Blueprint('slider', __name__)

@slider_bp.route('/api/slider/cache')
def get_slider_cache():
    """إرجاع آخر 4 شرائح من الكاش المحلي (بدون CORS)"""
    try:
        result = db_session.execute(text("SELECT platform, title, image_url, link_url FROM slider_cache ORDER BY id ASC LIMIT 4"))
        rows = result.fetchall()
        data = []
        for r in rows:
            data.append({
                "platform": r[0],
                "title": r[1],
                "image_url": r[2],
                "link_url": r[3]
            })
        # Ensure 4 slides in correct order
        # If less than 4, fill with fallbacks
        fallbacks = [
            {"platform": "العاصمة الآن الإخبارية", "title": "أخبار العاصمة الآن", "image_url": "", "link_url": "https://elasemaalaan.com"},
            {"platform": "المصري اليوم", "title": "أخبار المصري اليوم", "image_url": "", "link_url": "https://www.almasryalyoum.com"},
            {"platform": "يلا كورة", "title": "مباريات اليوم", "image_url": "", "link_url": "https://www.yallakora.com"},
            {"platform": "القرآن الكريم", "title": "إذاعة القرآن الكريم", "image_url": "", "link_url": "https://mp3quran.net"},
        ]
        while len(data) < 4:
            data.append(fallbacks[len(data)])
        
        # Ensure first slide is always ElAsema
        # Reorder to match required order
        order = ["العاصمة الآن الإخبارية", "المصري اليوم", "يلا كورة", "القرآن الكريم"]
        ordered = []
        for name in order:
            for item in data:
                if item["platform"] == name:
                    ordered.append(item)
                    break
        # Fill any missing
        for item in data:
            if item not in ordered:
                ordered.append(item)
        
        return jsonify(ordered[:4])
    except Exception as e:
        return jsonify([
            {"platform": "العاصمة الآن الإخبارية", "title": "أخبار العاصمة الآن", "image_url": "", "link_url": "https://elasemaalaan.com"},
            {"platform": "المصري اليوم", "title": "أخبار المصري اليوم", "image_url": "", "link_url": "https://www.almasryalyoum.com"},
            {"platform": "يلا كورة", "title": "مباريات اليوم", "image_url": "", "link_url": "https://www.yallakora.com"},
            {"platform": "القرآن الكريم", "title": "إذاعة القرآن الكريم", "image_url": "", "link_url": "https://mp3quran.net"},
        ])
