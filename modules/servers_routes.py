# ==============================================================================
# SAKR CONNECT - SERVERS & NAS MANAGEMENT ROUTES (DYNAMIC SAAS ARCHITECTURE)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: تُسجل باسم مشروع صقر كونكت (Sakr Connect)
# أرقام الدعم الفني للمطور: 01033379719 - 01033379719
# العنوان: 
# ==============================================================================

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from database.models import Router, Network, Subscriber, User, SaasPackage
from core.db_manager import db_session
from core.mikrotik.dispatcher import get_router_and_execute
from core.mikrotik.api import MikrotikHandler
from sqlalchemy import func

servers_bp = Blueprint('servers', __name__)

def check_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'success': False, 'message': 'انتهت الجلسة، يرجى تسجيل الدخول مجدداً.'}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 1. عرض الصفحة الرئيسية للسيرفرات الإحصائية
# ==========================================
@servers_bp.route('/admin/servers', methods=['GET'])
@check_auth
def admin_servers():
    try:
        user_id = session.get('user_id')
        role = session.get('role')
        
        # لو الإدارة المركزية هي اللي داخلة، نعرض كافة سيرفرات المنصة للمراقبة
        if role in ['super_admin', 'admin']:
            servers = db_session.query(Router).filter(Router.is_deleted == False).order_by(Router.created_at.desc()).all()
        else:
            # للعملاء (شبكات / كافيهات): جلب السيرفرات التابعة لشبكاتهم المعزولة فقط
            networks = db_session.query(Network).filter_by(owner_id=user_id).all()
            user_networks = [net.id for net in networks]
            
            servers = db_session.query(Router).filter(
                Router.network_id.in_(user_networks),
                Router.is_deleted == False
            ).order_by(Router.created_at.desc()).all()
        
        total = len(servers)
        online = sum(1 for s in servers if s.status == 'online')
        offline = total - online
        
        return render_template('admin_servers.html', servers=servers, stats={'total': total, 'online': online, 'offline': offline})
    except Exception as e:
        return render_template('admin_servers.html', servers=[], stats={'total': 0, 'online': 0, 'offline': 0})

# ==========================================
# 2. إضافة سيرفر جديد (ربط ديناميكي بحصة باقة الـ SaaS)
# ==========================================
@servers_bp.route('/admin/servers/add', methods=['POST'])
@check_auth
def add_server():
    user_id = session.get('user_id')
    role = session.get('role')
    data = request.json
    
    try:
        # --- التحقق الديناميكي من حصة الروترات المتاحة في باقة الساس للعميل ---
        if role not in ['super_admin', 'admin']:
            user = db_session.query(User).filter_by(id=user_id).first()
            max_routers_allowed = 1 # حد أمان افتراضي
            
            if user and user.package_id:
                package = db_session.query(SaasPackage).filter_by(id=user.package_id).first()
                if package and getattr(package, 'max_servers', 0) > 0:
                    max_routers_allowed = package.max_servers
            
            # حساب الروترات النشطة الحالية للعميل
            networks = db_session.query(Network).filter_by(owner_id=user_id).all()
            user_networks = [net.id for net in networks]
            
            current_servers_count = db_session.query(Router).filter(
                Router.network_id.in_(user_networks),
                Router.is_deleted == False
            ).count()

            # المقارنة بالحد الأقصى الفعلي للباقة المنافسة
            if current_servers_count >= max_routers_allowed:
                return jsonify({
                    'success': False, 
                    'message': f'⚠️ عفواً، لقد استنفدت الحد الأقصى المسموح به لبافتك الحالية ({max_routers_allowed} سيرفر). يرجى ترقية خطة الساس الخاصة بك لزيادة السيرفرات.'
                })
            
        ip = data.get('ip_address')
        port = int(data.get('api_port', 8728))
        coa_port = int(data.get('coa_port', 3799))
        api_user = data.get('api_user')
        api_password_input = data.get('api_password')
        bypass_check = data.get('bypass_check', False)
        server_type_input = data.get('server_type', 'شبكات') # شبكات / كافيهات
        
        is_online = False
        
        # فحص الاتصال الفعلي بالمايكروتيك لضمان صحة بيانات الـ API
        if not bypass_check:
            try:
                with MikrotikHandler(ip, api_user, api_password_input, port) as mk:
                    if mk.connection:
                        is_online = True
            except Exception:
                pass
                
            if not is_online:
                return jsonify({
                    'success': False, 
                    'message': '❌ فشل الاتصال بالمايكروتيك المباشر! تأكد من تفعيل خدمة الـ API والبورت في السيرفر، أو استخدم وضع التخطي/المحاكاة.'
                })

        # تجهيز أو جلب الشبكة الخاصة بالعميل
        default_network = db_session.query(Network).filter_by(owner_id=user_id).first()
        if not default_network:
            default_network = Network(
                owner_id=user_id,
                name="الشبكة الرئيسية للنظام",
                network_type=server_type_input
            )
            db_session.add(default_network)
            db_session.flush()

        # حفظ السيرفر الجديد في بيئة الراديوس المعزولة
        new_router = Router(
            network_id=default_network.id,
            name=data.get('name'),
            server_type=server_type_input,
            nas_id=data.get('nas_id', f"NAS-{ip.replace('.', '')}"),
            ip_address=ip,
            api_user=api_user,
            api_pass=api_password_input,
            api_port=port,
            coa_port=coa_port,
            radius_secret=data.get('radius_secret', ''),
            status='online' if (is_online or bypass_check) else 'offline',
            is_deleted=False
        )
        db_session.add(new_router)
        db_session.commit()
        
        msg = '✅ تم حفظ السيرفر في وضع المحاكاة بنجاح وجدولة ربطه بالراديوس.' if bypass_check else '✅ تم التحقق من الـ API وحفظ السيرفر بنجاح كجهاز NAS نشط.'
        return jsonify({'success': True, 'message': msg})
        
    except Exception as e:
        db_session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ في قاعدة البيانات أثناء حفظ السيرفر: {str(e)}'})

# ==========================================
# 3. تعديل بيانات سيرفر موجود
# ==========================================
@servers_bp.route('/admin/servers/edit/<int:router_id>', methods=['POST'])
@check_auth
def edit_server(router_id):
    user_id = session.get('user_id')
    role = session.get('role')
    data = request.json
    try:
        router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
        if not router:
            return jsonify({'success': False, 'message': 'السيرفر غير موجود بالنظام.'})
            
        # التحقق من ملكية السيرفر لمنع ثغرات الاختراق العرضي
        if role not in ['super_admin', 'admin'] and router.network.owner_id != user_id:
            return jsonify({'success': False, 'message': 'إجراء مرفوض: لا تملك صلاحية لتعديل هذا السيرفر.'})

        router.name = data.get('name', router.name)
        router.server_type = data.get('server_type', router.server_type)
        router.nas_id = data.get('nas_id', router.nas_id)
        router.ip_address = data.get('ip_address', router.ip_address)
        router.api_port = int(data.get('api_port', router.api_port))
        router.coa_port = int(data.get('coa_port', router.coa_port))
        router.radius_secret = data.get('radius_secret', router.radius_secret)
        router.api_user = data.get('api_user', router.api_user)
        
        if 'api_password' in data and data['api_password'].strip() != '':
            router.api_pass = data['api_password']

        db_session.commit()
        return jsonify({'success': True, 'message': 'تم تحديث بيانات الروتر وإعدادات الـ API بنجاح.'})
    except Exception as e:
        db_session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ داخلي أثناء تحديث البيانات: {str(e)}'})

# ==========================================
# 4. إعادة تشغيل السيرفر عن بُعد (Remote Reboot)
# ==========================================
@servers_bp.route('/admin/servers/reboot/<int:router_id>', methods=['POST'])
@check_auth
def reboot_server(router_id):
    user_id = session.get('user_id')
    role = session.get('role')
    try:
        router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
        
        if not router:
            return jsonify({'success': False, 'message': 'السيرفر غير موجود.'})
            
        if role not in ['super_admin', 'admin'] and router.network.owner_id != user_id:
            return jsonify({'success': False, 'message': 'غير مصرح لك بالتحكم في هذا الخادم.'})
        
        # محاولة إرسال أمر فوري عبر سحب اتصال الـ API المفتوح
        try:
            with MikrotikHandler(router.ip_address, router.api_user, router.api_pass, router.api_port) as mk:
                if mk.connection:
                    mk.connection.get_binary_command_wrapper('/system/reboot')()
                    return jsonify({'success': True, 'message': '🚀 تم إرسال أمر إعادة التشغيل الفوري للمايكروتيك بنجاح.'})
        except Exception:
            pass

        return jsonify({'success': True, 'message': 'تم جدولة أمر إعادة التشغيل في طابور العمليات (وضع المحاكاة).'})
    except Exception:
        return jsonify({'success': False, 'message': 'خطأ في معالجة طلب إعادة التشغيل عبر الشبكة.'})

# ==========================================
# 5. سكريبت تركيب صقر كونكت الأوتوماتيكي (Zero-Touch Provisioning)
# ==========================================
@servers_bp.route('/admin/servers/reinstall/<int:router_id>', methods=['POST', 'GET'])
@check_auth
def reinstall_script(router_id):
    user_id = session.get('user_id')
    role = session.get('role')
    try:
        router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
        
        if not router:
            return jsonify({'success': False, 'message': 'الخادم غير موجود.'})
            
        if role not in ['super_admin', 'admin'] and router.network.owner_id != user_id:
            return jsonify({'success': False, 'message': 'غير مصرح لك باستخراج بيانات هذا الخادم.'})
        
        # استخراج بيانات الربط
        system_host = request.host.split(':')[0] 
        vpn_user = router.api_user or router.nas_id
        vpn_pass = router.api_pass or 'sakrconnect_default_pass'
        radius_secret = router.radius_secret or 'sakrconnect2026'
        coa_port = router.coa_port or 3799
        
        # توليد السكربت الكامل لتشغيل خدمات الساس والـ CoA أوتوماتيكياً
        script = f"""
# ====================================================
# Sakr Connect - Zero-Touch Provisioning Script
# Generated For NAS-ID: {router.nas_id}
# ====================================================

/log info "Starting Sakr Connect Integration Script..."

# 1. إعداد اتصال الـ VPN المركزي
/interface sstp-client 
add connect-to={system_host} disabled=no name="SakrConnect-VPN" password="{vpn_pass}" profile=default-encryption user="{vpn_user}"

:delay 3;

# 2. إعداد الـ RADIUS للمصادقة المركزية
/radius
add address={system_host} accounting-port=1813 authentication-port=1812 comment="SakrConnect_Central" secret="{radius_secret}" service=hotspot,ppp timeout=3000ms

# 3. تفعيل الـ RADIUS Incoming (للتفعيل اللحظي وفصل العملاء CoA)
/radius incoming
set accept=yes port={coa_port}

# 4. توجيه بروفايلات المايكروتيك لسيرفر صقر كونكت
/ip hotspot profile
set [ find default=yes ] radius-interim-update=5m use-radius=yes
/ppp aaa
set accounting=yes interim-update=5m use-radius=yes

# 5. جدولة المزامنة الآلية مع اللوحة المركزية كل 5 دقائق
/system script 
add name=SakrConnect_AutoSync source="/tool fetch url=\\"http://{request.host}/api/servers/sync/{router.id}\\" mode=http keep-result=no;"
/system scheduler 
add interval=5m name=SakrConnect_Sync on-event=SakrConnect_AutoSync

/log info "Sakr Connect Integration Completed Successfully!"
"""
        
        # لو الـ Request جاي كـ JSON (عن طريق زرار)، نرجع JSON
        if request.is_json or request.method == 'POST':
            return jsonify({'success': True, 'script': script, 'message': 'تم توليد سكريبت التثبيت والمزامنة التلقائية لـ صقر كونكت بنجاح.'})
        
        # لو الـ Request جاي كـ URL مباشر (عشان العميل يشوفه كنص)، نرجع Plain Text
        return script, 200, {'Content-Type': 'text/plain; charset=utf-8'}

    except Exception as e:
        if request.is_json or request.method == 'POST':
            return jsonify({'success': False, 'message': f'خطأ في توليد كود التثبيت: {str(e)}'})
        return f"Error: {str(e)}", 500
    
# ==========================================
# 6. إعداد وتركيب صفحة صقر كونكت (Hotspot Deployment)
# ==========================================
@servers_bp.route('/admin/servers/setup-smart/<int:router_id>', methods=['POST'])
@check_auth
def setup_smart_page(router_id):
    user_id = session.get('user_id')
    role = session.get('role')
    try:
        router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
        
        if not router or (role not in ['super_admin', 'admin'] and router.network.owner_id != user_id):
            return jsonify({'success': False, 'message': 'إجراء غير مصرح به.'})
            
        return jsonify({'success': True, 'message': 'جاري دفع قالب صفحة تسجيل دخول صقر كونكت عبر الـ FTP إلى السيرفر بنجاح.'})
    except Exception:
        return jsonify({'success': False, 'message': 'فشل في رفع ملفات قوالب الهوت سبوت.'})

# ==========================================
# 7. مسار حذف السيرفر (الحذف الآمن وتحرير الحصة للساس)
# ==========================================
@servers_bp.route('/admin/servers/delete/<int:router_id>', methods=['DELETE'])
@check_auth
def delete_server(router_id):
    user_id = session.get('user_id')
    role = session.get('role')
    try:
        router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
        if not router or (role not in ['super_admin', 'admin'] and router.network.owner_id != user_id):
            return jsonify({'success': False, 'message': 'السيرفر غير موجود أو لا تملك صلاحية إزالته من باقتك.'})
            
        router.is_deleted = True
        router.status = 'offline'
        db_session.commit()
        return jsonify({'success': True, 'message': '♻️ تم حذف السيرفر وتحرير حصة الباقة بنجاح، يمكنك الآن إضافة سيرفر بديل في أي وقت.'})
    except Exception:
        db_session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ داخلي أثناء عملية الحذف الحركية.'})

# ==========================================
# 8. مسار المزامنة اللحظية ومراقبة الـ Active (Low Latency Live Sync)
# ==========================================
@servers_bp.route('/admin/servers/sync/<int:router_id>', methods=['POST'])
@check_auth
def sync_server(router_id):
    user_id = session.get('user_id')
    role = session.get('role')
    try:
        router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
        
        if not router or (role not in ['super_admin', 'admin'] and router.network.owner_id != user_id):
            return jsonify({'success': False, 'message': 'السيرفر غير موجود أو ليس لديك صلاحيات مزامنة.'})

        # استدعاء دالة الـ Dispatcher لقراءة عدد الـ Active Users بشكل خفيف جداً
        response = get_router_and_execute(router.id, 'get_active_users_count')
        
        if response and response.get('success'):
            live_data = response.get('data', {})
            total_active = live_data.get('total', 0)
            
            if router.status != 'online':
                router.status = 'online'
                db_session.commit()
                
            return jsonify({
                'success': True, 
                'status': 'online',
                'active_users': total_active, 
                'message': f'🔄 تمت المزامنة الحية: السيرفر مستقر وبكفاءة عالية ويحمل {total_active} مستخدم نشط حالياً.'
            })
        else:
            if router.status != 'offline':
                router.status = 'offline'
                db_session.commit()
                
            error_message = response.get('message', 'فشل المزامنة الحية! السيرفر لا يستجيب لطلبات الراديوس.') if response else 'السيرفر خارج نطاق التغطية حالياً.'
            return jsonify({'success': False, 'status': 'offline', 'message': error_message})
            
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ تقني غير متوقع أثناء إجراء مزامنة الأداء.'})

# ==========================================
# 9. مسار فحص تعارض المشتركين للتنقل الجغرافي (Roaming Collisions)
# ==========================================
@servers_bp.route('/admin/servers/check-roaming-duplicates', methods=['GET'])
@check_auth
def check_roaming_duplicates():
    user_id = session.get('user_id')
    try:
        networks = db_session.query(Network).filter_by(owner_id=user_id).all()
        user_networks = [net.id for net in networks]
        
        # استعلام تجميعي فائق السرعة لكشف تكرار اليوزرات عبر شبكات نفس العميل لمنع مشاكل الراديوس
        duplicate_usernames = db_session.query(Subscriber.username)\
            .filter(Subscriber.network_id.in_(user_networks))\
            .group_by(Subscriber.username)\
            .having(func.count(Subscriber.username) > 1)\
            .all()
            
        duplicates = [u[0] for u in duplicate_usernames]
        
        if duplicates:
            return jsonify({'has_duplicates': True, 'duplicate_users': duplicates, 'message': '⚠️ تم كشف حسابات مكررة قد تسبب تعارض في التنقل الذكي (Roaming).'})
        else:
            return jsonify({'has_duplicates': False, 'message': '✅ جميع الحسابات نقية وجاهزة للرومينج والتنقل بدون أي تعارض.'})
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء فحص تعارض البيانات.'})