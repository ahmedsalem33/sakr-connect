"""
Project: Sakr Connect
Developer: Sakr Media Agency (صقر ميديا)
Lead Engineer: أحمد سالم الملواني
Support: 01033379719 - 01033379719
"""

import logging
from sqlalchemy import text
from core.db_manager import db_session

# إعداد نظام المراقبة لمحرك الراديوس
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SakrConnect_Radius")

class RadiusHandler:
    """
    العقل المدبر للتعامل مع جداول FreeRADIUS القياسية.
    يتحكم في المصادقة، تحديد السرعات، ومراقبة الاستهلاك الفعلي للمشتركين.
    """

    @staticmethod
    def add_or_update_user(username, password, cleartext=True):
        """
        حقن أو تحديث بيانات العميل (كارت أو برودباند) في جدول radcheck.
        هذا الجدول هو ما يسأل عنه المايكروتيك عند محاولة دخول أي عميل.
        """
        attribute = "Cleartext-Password" if cleartext else "Crypt-Password"
        try:
            # التحقق أولاً إذا كان العميل موجوداً لتحديثه بدلاً من تكرار الإدخال
            check_sql = text("SELECT id FROM radcheck WHERE username = :u AND attribute = :attr")
            existing = db_session.execute(check_sql, {"u": username, "attr": attribute}).fetchone()

            if existing:
                update_sql = text("UPDATE radcheck SET value = :p WHERE id = :id")
                db_session.execute(update_sql, {"p": password, "id": existing[0]})
            else:
                insert_sql = text("INSERT INTO radcheck (username, attribute, op, value) VALUES (:u, :attr, ':=', :p)")
                db_session.execute(insert_sql, {"u": username, "attr": attribute, "p": password})
                
            db_session.commit()
            logger.info(f"✅ تم تسجيل بيانات المصادقة للعميل: {username} في الراديوس.")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"❌ خطأ أثناء تسجيل العميل {username} في radcheck: {str(e)}")
            return False

    @staticmethod
    def assign_profile(username, profile_name):
        """
        تخصيص باقة أو سرعة للعميل عبر جدول radusergroup.
        (يجب أن يكون البروفايل معرفاً مسبقاً في جداول radgroupreply).
        """
        try:
            # مسح أي بروفايل قديم للعميل لضمان عدم حدوث تعارض (Overlapping)
            delete_old = text("DELETE FROM radusergroup WHERE username = :u")
            db_session.execute(delete_old, {"u": username})
            
            # حقن البروفايل الجديد
            insert_new = text("INSERT INTO radusergroup (username, groupname, priority) VALUES (:u, :g, 1)")
            db_session.execute(insert_new, {"u": username, "g": profile_name})
            
            db_session.commit()
            logger.info(f"تم ربط العميل {username} بالباقة/السرعة: {profile_name}")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"خطأ أثناء ربط الباقة للعميل {username}: {str(e)}")
            return False

    @staticmethod
    def get_user_usage(username):
        """
        قراءة الاستهلاك اللحظي (التحميل والرفع) من جدول radacct.
        تقوم هذه الدالة بجمع البايتات المستهلكة من كل جلسات العميل لتعرضها في لوحة التحكم.
        """
        try:
            sql = text("""
                SELECT 
                    SUM(acctinputoctets) as total_upload, 
                    SUM(acctoutputoctets) as total_download 
                FROM radacct 
                WHERE username = :u
            """)
            result = db_session.execute(sql, {"u": username}).fetchone()
            
            # معالجة القيم في حالة كان العميل لم يستخدم الإنترنت بعد (تكون القيم None)
            upload_bytes = result[0] if result[0] else 0
            download_bytes = result[1] if result[1] else 0
            
            return {
                "upload_bytes": upload_bytes,
                "download_bytes": download_bytes,
                "total_bytes": upload_bytes + download_bytes
            }
        except Exception as e:
            logger.error(f"خطأ أثناء قراءة استهلاك العميل {username}: {str(e)}")
            return {"upload_bytes": 0, "download_bytes": 0, "total_bytes": 0}

    @staticmethod
    def remove_user(username):
        """
        حذف العميل نهائياً من جداول الراديوس (عند انتهاء الكارت أو حذف المشترك).
        """
        try:
            db_session.execute(text("DELETE FROM radcheck WHERE username = :u"), {"u": username})
            db_session.execute(text("DELETE FROM radusergroup WHERE username = :u"), {"u": username})
            db_session.commit()
            logger.info(f"تم مسح العميل {username} من خوادم الراديوس.")
            return True
        except Exception as e:
            db_session.rollback()
            logger.error(f"خطأ أثناء حذف العميل {username}: {str(e)}")
            return False