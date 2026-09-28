"""
Project: Sakr Connect
Developer: Sakr Media Agency (صقر ميديا)
Lead Engineer: أحمد سالم الملواني
Support: 01033379719 - 01033379719
"""

import logging
from werkzeug.security import generate_password_hash, check_password_hash
from core.db_manager import db_session

# استدعاء الجداول الثلاثة لضمان عدم وجود نقطة عمياء في البحث
try:
    from database.models import User, SystemAdmin, Subscriber
except ImportError:
    User = SystemAdmin = Subscriber = None

# إعداد مراقب أخطاء محرك المصادقة
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SakrConnect_Security")

class SecurityManager:
    """
    بوابة الحماية المركزية لنظام Sakr Connect.
    تتولى التشفير، المصادقة الرقمية، وفرض العزل الصارم بين الأنظمة (منازل، كافيهات، شبكات).
    """

    @staticmethod
    def hash_password(password: str) -> str:
        return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

    @staticmethod
    def verify_password(password: str, db_password: str) -> bool:
        """
        دالة التحقق الذكية:
        تدعم الباسوردات المشفرة للحسابات الحديثة، والنصوص العادية للحسابات القديمة.
        """
        if not db_password:
            return False
        
        # فحص إذا كان الباسورد مشفر (Hash)
        if db_password.startswith('pbkdf2:sha256:') or db_password.startswith('scrypt:'):
            return check_password_hash(db_password, password)
        
        # المطابقة المباشرة إذا كان الباسورد مسجل كنص عادي (Plain Text)
        return password == db_password

    @classmethod
    def authenticate_user(cls, username, password, portal_type, system_type=None, app_role=None):
        try:
            # ==========================================
            # 1. تأمين بوابة الإدارة المركزية (تبحث حصراً في SystemAdmin)
            # ==========================================
            if portal_type == 'admin':
                if not SystemAdmin:
                    return False, None
                
                admin = db_session.query(SystemAdmin).filter_by(username=username).first()
                if admin and cls.verify_password(password, getattr(admin, 'password_hash', '')):
                    # منح الرتبة الإدارية وتمريرها للجلسة
                    admin.role = 'super_admin' if admin.username in ['admin', 'super_admin', 'sakr_admin'] else 'admin'
                    logger.info(f"✅ نجاح دخول مسؤول النظام: {username}")
                    return True, admin
                
                logger.warning(f"🚫 حظر محاولة عبور: بيانات غير صحيحة للإدارة [{username}]")
                return False, None

            # ==========================================
            # 2. تأمين اللوحة الموحدة للأنظمة (تبحث في User و Subscriber)
            # ==========================================
            elif portal_type == 'web_portal':
                
                # أ. فحص أصحاب الشبكات والكافيهات والموزعين (جدول User)
                if User:
                    user = db_session.query(User).filter_by(username=username, is_active=True).first()
                    if user:
                        db_pass = getattr(user, 'password_hash', getattr(user, 'password', ''))
                        if cls.verify_password(password, db_pass):
                            # قراءة نوع النظام الفعلي من الداتا بيز (الاعتماد الأساسي على role ثم usage_type)
                            db_role = getattr(user, 'role', getattr(user, 'usage_type', 'غير معروف'))
                            
                            # الاستثناء السيادي: السوبر أدمن يفتح أي بوابة
                            if db_role == 'super_admin':
                                logger.info(f"👑 دخول سيادي (سوبر أدمن) من اللوحة الموحدة: {username}")
                                return True, user
                                
                            # المطابقة الصارمة لبيانات البوابة
                            if db_role == system_type:
                                logger.info(f"✅ نجاح دخول لوحة تحكم: {username} ({system_type})")
                                return True, user
                                
                            logger.warning(f"🚫 منع تداخل: العميل {username} مسجل بنظام [{db_role}] وحاول اختراق بوابة [{system_type}]!")
                            return False, None

                # ب. فحص المشتركين النهائيين للمنازل (جدول Subscriber)
                if Subscriber:
                    sub = db_session.query(Subscriber).filter_by(username=username).first()
                    if sub:
                        db_pass = getattr(sub, 'password', '')
                        if cls.verify_password(password, db_pass):
                            db_role = getattr(sub, 'sub_type', 'home')
                            
                            if db_role == system_type:
                                sub.role = db_role  # توحيد الرتبة للجلسة (Session)
                                logger.info(f"✅ نجاح دخول مشترك: {username} ({system_type})")
                                return True, sub
                                
                            logger.warning(f"🚫 منع تداخل: المشترك {username} حاول اختراق بوابة [{system_type}]!")
                            return False, None

                logger.warning(f"⚠️ فشل محاولة دخول للوحة الموحدة: بيانات غير صحيحة للمعرف ({username})")
                return False, None

            # ==========================================
            # 3. تأمين تطبيق الدفع والماليات (صقر كونكت باي)
            # ==========================================
            elif portal_type == 'app_login':
                if User:
                    user = db_session.query(User).filter_by(username=username, is_active=True).first()
                    if user and cls.verify_password(password, getattr(user, 'password_hash', '')):
                        if user.role == app_role:
                            logger.info(f"✅ نجاح دخول مالي: {username} بصلاحية ({app_role})")
                            return True, user
                
                if Subscriber and app_role == 'subscriber':
                    sub = db_session.query(Subscriber).filter_by(username=username).first()
                    if sub and cls.verify_password(password, getattr(sub, 'password', '')):
                        sub.role = 'subscriber'
                        logger.info(f"✅ نجاح دخول مالي للمشترك: {username}")
                        return True, sub

                logger.warning(f"🚫 منع تداخل مالي للمعرف ({username})")
                return False, None

            return False, None
            
        except Exception as e:
            logger.error(f"❌ خطأ حرج في محرك المصادقة الأمني: {str(e)}")
            return False, None

    @classmethod
    def create_first_admin(cls):
        """
        تأسيس حساب الإدارة العليا والسيادة الفعلي للمنظومة.
        """
        try:
            if not User: return
            admin_exists = db_session.query(User).filter_by(role='super_admin').first()
            if not admin_exists:
                new_admin = User(
                    username='sakr_admin',
                    password_hash=cls.hash_password('sakr2026!@#'),
                    role='super_admin',
                    fullname='أحمد سالم الملواني - صقر ميديا',
                    email='admin@sakrmedia.com',
                    is_active=True
                )
                db_session.add(new_admin)
                db_session.commit()
                logger.info("✅ تم إنشاء حساب السوبر أدمن السيادي بنجاح.")
        except Exception as e:
            db_session.rollback()
            logger.error(f"❌ فشل تأسيس حساب الإدارة السيادي: {str(e)}")