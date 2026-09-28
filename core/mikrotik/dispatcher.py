import logging
from database.models import Router
from core.db_manager import db_session
from core.mikrotik.api import MikrotikHandler

logger = logging.getLogger("SakrConnect_Dispatcher")

# ==========================================
# قوائم الصلاحيات (RBAC Lists)
# ==========================================
# أوامر المراقبة (مسموحة دائماً حتى لو اشتراك الموزع منتهي)
READ_ONLY_ACTIONS = [
    'get_system_resources', 
    'get_active_users_count', 
    'get_active_sessions_details',
    'get_interface_traffic',
    'get_interfaces'
]

def get_router_and_execute(router_id, action_func, **kwargs):
    """
    المنسق والبوابة الأمنية الذكية (Gatekeeper):
    يستقبل الطلبات، يتحقق من حالة اشتراك صاحب اللوحة، ويُنسق الاتصال.
    يعيد قاموس (Dict) مهندس ليسهل قراءته في واجهة المستخدم (Frontend).
    """
    try:
        # 1. جلب بيانات السيرفر من قاعدة البيانات
        router = db_session.query(Router).filter_by(id=router_id).first()
        
        if not router:
            logger.warning(f"❌ محاولة وصول لسيرفر غير موجود. ID: {router_id}")
            return {"success": False, "message": "لم يتم العثور على السيرفر في قاعدة البيانات.", "data": None}

        # 2. طبقة الحماية والتجميد الذكي (Dashboard Freeze)
        # التعديل الجوهري: الوصول لمالك الشبكة عبر مسار السيرفر -> الشبكة -> المالك
        is_dashboard_frozen = False
        if hasattr(router, 'network') and router.network and hasattr(router.network, 'owner') and router.network.owner:
            is_dashboard_frozen = not getattr(router.network.owner, 'is_active', True)
        
        # إذا كانت اللوحة مجمدة، والأمر المطلوب هو أمر "تحكم" وليس "مراقبة"
        if is_dashboard_frozen and action_func not in READ_ONLY_ACTIONS:
            logger.warning(f"🔒 تم حجب أمر تحكم ({action_func}) للموزع لانتهاء اشتراكه. الراوتر: {router_id}")
            return {
                "success": False, 
                "message": "عفواً، لوحة الإدارة مقيدة لانتهاء الاشتراك. يُرجى التجديد لتتمكن من التحكم في السيرفر.", 
                "data": None
            }

        # 3. فتح الاتصال الآمن بالمايكروتيك (Context Manager)
        # التعديل: استخدام api_pass بدلاً من api_password ليتطابق مع قاعدة البيانات
        with MikrotikHandler(router.ip_address, router.api_user, router.api_pass, router.api_port) as mk:
            
            # التأكد من أن السيرفر متصل فعلياً قبل إعطاء الأمر
            if not mk.connection:
                return {"success": False, "message": "تعذر الاتصال بالمايكروتيك، تأكد من أن السيرفر يعمل ومتصل بالإنترنت.", "data": None}

            # التأكد من أن الدالة المطلوبة موجودة داخل الكلاس
            func_to_call = getattr(mk, action_func, None)
            if not func_to_call:
                return {"success": False, "message": f"الإجراء المطلوب ({action_func}) غير مدعوم في النظام.", "data": None}

            # 4. تنفيذ الأمر الحي (Execution)
            result = func_to_call(**kwargs)

            # 5. هندسة الردود للواجهة (Response Formatting)
            if action_func in READ_ONLY_ACTIONS:
                # أوامر سحب الداتا ترجع البيانات في حقل 'data'
                return {"success": True, "message": "تم سحب البيانات بنجاح.", "data": result}
            else:
                # أوامر التحكم ترجع نجاح أو فشل فقط
                if result:
                    return {"success": True, "message": "تم تنفيذ الأمر على السيرفر بنجاح.", "data": None}
                else:
                    return {"success": False, "message": "السيرفر لم يستجب للأمر أو حدث خطأ أثناء التنفيذ.", "data": None}

    except Exception as e:
        logger.error(f"⚠️ خطأ داخلي في المنسق (Dispatcher) للراوتر {router_id}: {str(e)}")
        return {"success": False, "message": "حدث خطأ في النظام أثناء معالجة الطلب، تمت كتابته في السجلات.", "data": None}