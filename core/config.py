"""
Project: Sakr Connect
Developer: Sakr Media Agency (صقر ميديا)
Lead Engineer: أحمد سالم الملواني
Support: 01033379719
"""

import os

class Config:
    """
    ملف الإعدادات المركزي (الدستور) لنظام Sakr Connect.
    تم تعديله ليعمل بمحرك SQLite محلياً لسهولة الاختبار والتطوير بدون سيرفرات خارجية.
    """

    # ==========================================
    # 1. ثوابت المشروع وحقوق الملكية (Agency Globals)
    # ==========================================
    PROJECT_NAME = "Sakr Connect"
    DEVELOPER_AGENCY = "Sakr Media Agency (صقر ميديا)"
    LEAD_ENGINEER = "أحمد سالم الملواني"
    SUPPORT_NUMBERS = ["01033379719"]
    ADDRESS = ""
    DEVELOPER_FB = "https://www.facebook.com/ahmedsalemJournalist"
    AGENCY_FB = "https://www.facebook.com/sakrmediaagency"

    # ==========================================
    # 2. إعدادات الأمان والتشفير (Security & Salts)
    # ==========================================
    # These values are read from environment variables in production.
    # For development, sensible defaults are provided but MUST be changed
    # for any production deployment. Never commit real secrets to source control.
    SECRET_KEY = os.environ.get('SAKR_SECRET_KEY', 'Sakr_Super_Secret_Key_2026_!@#')
    VOUCHER_SALT = os.environ.get('VOUCHER_SALT', 'Sakr_Voucher_Encryption_Salt_9988')

    # ==========================================
    # 3. إعدادات قاعدة البيانات المحلية (Local SQLite Engine)
    # ==========================================
    # تحديد المسار الجذري للمشروع لإنشاء ملف قاعدة البيانات بداخله تلقائياً
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    
    # رابط الاتصال الموحد (تم تحويله إلى SQLite للتشغيل المحلي المباشر)
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'sakr_connect.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ==========================================
    # 4. إعدادات المايكروتيك الافتراضية (MikroTik Defaults)
    # ==========================================
    MK_API_PORT = int(os.environ.get('MK_API_PORT', 8728))
    MK_TIMEOUT = int(os.environ.get('MK_TIMEOUT', 5))

    # ==========================================
    # 5. إعدادات محرك الراديوس (FreeRADIUS Config)
    # ==========================================
    # These values are read from environment variables in production.
    # For development, sensible defaults are provided but MUST be changed
    # for any production deployment. Never commit real secrets to source control.
    RADIUS_SECRET = os.environ.get('RADIUS_SECRET', 'sakr_radius_master_secret')
    RADIUS_HOST = os.environ.get('RADIUS_HOST', '127.0.0.1')
    RADIUS_PORT = int(os.environ.get('RADIUS_PORT', 1812))
    RADIUS_ACCT_PORT = int(os.environ.get('RADIUS_ACCT_PORT', 1813))