import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from sqlalchemy.pool import NullPool  # إضافة هامة جداً لحل مشكلة الاختناق
from core.config import Config

# إعداد نظام تسجيل ومراقبة أخطاء قاعدة البيانات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SakrConnect_DB")

try:
    # 1. إنشاء محرك الاتصال بقاعدة البيانات (Database Engine)
    # تم التعديل ليتوافق تماماً مع SQLite ومنع خطأ QueuePool limit
    engine = create_engine(
        Config.SQLALCHEMY_DATABASE_URI,
        connect_args={'check_same_thread': False},
        poolclass=NullPool
    )
    
    # 2. إنشاء مصنع الجلسات (Session Factory) وجعله آمن التعددية (Thread-safe) عبر scoped_session
    db_session = scoped_session(
        sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )
    )
    
    # 3. التعريف الهيكلي للقاعدة الأساسية (Declarative Base)
    Base = declarative_base()
    Base.query = db_session.query_property()

except Exception as e:
    logger.error(f"❌ خطأ حرج: فشل تأسيس جسر الاتصال بقاعدة البيانات: {str(e)}")
    raise e


def init_db():
    """
    دالة تهيئة قاعدة البيانات.
    تقوم ببناء الجداول، تحديث الأعمدة الهيكلية، وتأسيس جسور الراديوس.
    """
    try:
        # استدعاء ملف الموديلات للتعرف عليها
        import database.models
        
        # بناء الجداول
        Base.metadata.create_all(bind=engine)
        logger.info("✅ تم فحص وتهيئة بنية قاعدة البيانات وإنشاء الجداول بنجاح.")
        
        inspector = inspect(engine)
        existing_columns = [col['name'] for col in inspector.get_columns('users')]
        
        with engine.begin() as connection:
            # تحديث هيكل جدول المستخدمين
            if 'package_id' not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN package_id INTEGER;"))
            if 'parent_id' not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN parent_id INTEGER;"))
            if 'discount_rate' not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN discount_rate FLOAT DEFAULT 0.0;"))
            if 'api_token' not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN api_token VARCHAR(255);"))
            if 'country' not in existing_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN country VARCHAR(2) DEFAULT 'EG';"))
            
            # تحديث هيكل جدول الباقات (saas_packages)
            pkg_columns = [col['name'] for col in inspector.get_columns('saas_packages')]
            if 'country' not in pkg_columns:
                connection.execute(text("ALTER TABLE saas_packages ADD COLUMN country VARCHAR(2) DEFAULT 'EG';"))
            if 'currency' not in pkg_columns:
                connection.execute(text("ALTER TABLE saas_packages ADD COLUMN currency VARCHAR(10) DEFAULT 'EGP';"))
            if 'max_servers' not in pkg_columns:
                connection.execute(text("ALTER TABLE saas_packages ADD COLUMN max_servers INTEGER DEFAULT 0;"))
            if 'max_subscribers' not in pkg_columns:
                connection.execute(text("ALTER TABLE saas_packages ADD COLUMN max_subscribers INTEGER DEFAULT 0;"))
            
            # --- تأسيس جسور الاتصال المباشر مع الراديوس (Radius Integration) ---
            # فيو التحقق (radcheck)
            connection.execute(text("""
                CREATE VIEW IF NOT EXISTS radcheck AS 
                SELECT id AS id, username AS username, 'Cleartext-Password' AS attribute, 
                password AS value, ':=' AS op FROM subscribers WHERE status = 'active'
            """))
            
            # فيو التحديد (radreply)
            connection.execute(text("""
                CREATE VIEW IF NOT EXISTS radreply AS 
                SELECT id AS id, username AS username, 'Mikrotik-Rate-Limit' AS attribute, 
                speed AS value, ':=' AS op FROM subscribers WHERE status = 'active'
            """))
            logger.info("✅ تم تأسيس جسور الاتصال (Radius Views) بنجاح داخل قاعدة البيانات.")

    except Exception as e:
        logger.error(f"❌ خطأ أثناء محاولة تهيئة وبناء الجداول أو تحديث الأعمدة: {str(e)}")
        raise e


def shutdown_session(exception=None):
    """
    دالة إغلاق الجلسة وتحرير الاتصال.
    """
    db_session.remove()