# ==========================================
# Project: Sakr Connect
# Developer: Sakr Media Agency (صقر ميديا)
# Lead Engineer: أحمد سالم الملواني
# Support: 01033379719
# العنوان: 
# صفحة المطور الشخصية: https://www.facebook.com/ahmedsalemJournalist
# صفحة الوكالة: https://www.facebook.com/sakrmediaagency
# حقوق النشر: تُسجل باسم المشروع (Sakr Connect)
# ==========================================

import os
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, abort, session, redirect, url_for, request, flash, jsonify, send_from_directory, Response, g
from functools import wraps

# 1. إضافة استدعاءات قاعدة البيانات هنا (تم إضافة init_db للاستدعاء)
from core.db_manager import engine, Base, db_session, init_db 
import database.models  
from database.models import BroadcastMessage, AuditLog, User, Router
from database.central_models import GlobalSetting, NetworkClient 
from core.auth.trial import get_trial_status 
from core.config import Config 

# استيراد البلوبرينت الخاصة بالنظام بالكامل
from modules.vouchers_routes import vouchers_bp
from modules.subscribers_routes import subscribers_bp
from modules.infrastructure_routes import infrastructure_bp
from modules.security_routes import security_bp
from modules.finance_routes import finance_bp
from modules.support_routes import support_bp  
from modules.servers_routes import servers_bp  
from modules.recharge_routes import recharge_bp  
from modules.client_settings_routes import client_settings_bp  
from modules.auth_routes import auth_bp
from modules.settings_routes import settings_bp
from modules.app_routes import app_bp
from modules.slider_routes import slider_bp

# تم إيقاف نظام المنازل (للاحتفاظ بالكود للمستقبل دون استهلاكه في الذاكرة)
# from modules.home_routes import home_bp

app = Flask(__name__)
app.secret_key = "sakr_media_agency_super_secret"

# تسجيل الموديولات في التطبيق
app.register_blueprint(vouchers_bp)
app.register_blueprint(subscribers_bp)
app.register_blueprint(infrastructure_bp)
app.register_blueprint(security_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(support_bp)  
app.register_blueprint(servers_bp)  
app.register_blueprint(recharge_bp)  
app.register_blueprint(client_settings_bp)  
app.register_blueprint(auth_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(app_bp)
app.register_blueprint(slider_bp)

# إيقاف تسجيل مسارات المنازل
# app.register_blueprint(home_bp)

# ==========================================
# 2. أمر بناء الجداول 
# ==========================================
with app.app_context():
    init_db() 
    print("[OK] Database tables verified and created successfully.")

# ==========================================
# [ جدار الحماية وحارس دورة حياة الـ SaaS - موحد ]
# ==========================================
@app.before_request
def saas_lockdown_middleware():
    # مسارات مستثناة بالكامل - للكافيهات والشبكات: التجربة تفتح كل الصفحات لكن حظر الربط, والقفل يبقي فقط sakr_account
    # /api/generate_script مستثنى لأنه يطبق حظره الخاص (رسالة نصية) بدلاً من redirect
    exempt_paths = [
        '/static', '/auth/login', '/auth/logout', '/auth/register', 
        '/auth/admin/login', '/auth/forgot-password', '/api/check_username',
        '/client/account', '/finance/checkout', '/api/generate_script',
        '/portal', '/process_fast_purchase', '/download', '/logout'
    ]
    
    if any(request.path.startswith(p) for p in exempt_paths):
        return

    # قيم افتراضية
    g.is_trial_active = True
    g.has_active_sub = False
    g.is_locked = False

    # لو مفيش جلسة، يخلي الـ auth decorators تتعامل معاه
    if 'user_id' not in session:
        return

    role = session.get('role')
    
    # الأدمن والسوبر أدمن معفيين
    if role in ['admin', 'super_admin']:
        return

    # حساب الحالة الموحدة
    current_user_id = session.get('user_id')
    current_user = db_session.query(User).filter_by(id=current_user_id).first()
    
    if not current_user:
        return
        
    trial_status = get_trial_status(current_user)
    
    # تحديث الجلسة والقوالب
    session['is_trial'] = trial_status['is_trial']
    session['is_locked'] = trial_status['is_locked']
    session['trial_end_iso'] = trial_status['trial_end_iso']
    session['remaining_seconds'] = trial_status['remaining_seconds']
    
    g.is_trial_active = trial_status['is_trial']
    g.has_active_sub = not trial_status['is_locked'] and not trial_status['is_trial']
    g.is_locked = trial_status['is_locked']

    # القفل الشامل: أي طلب لصفحة محمية يتحول لصفحة الفواتير
    if trial_status['is_locked']:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"status": "locked", "message": "الاشتراك منتهي، يرجى التجديد"}), 403
        return redirect(url_for('finance.sakr_account'))

# ==========================================
# 3. مسار تحميل الملفات المرفوعة
# ==========================================
@app.route('/download/<folder>/<filename>')
def download_file(folder, filename):
    if folder not in ['hotspots', 'apps', 'logos']:
        abort(404)
        
    base_dir = os.path.abspath(os.path.dirname(__file__))
    target_dir = os.path.join(base_dir, 'uploads', folder)
    
    return send_from_directory(target_dir, filename, as_attachment=True)

# ==========================================
# 4. مسار توليد سكريبت المايكروتيك (مع قفل الربط في الفترة التجريبية أو عند انتهاء الباقة) - خاص بالكافيهات والشبكات
# ==========================================
@app.route('/api/generate_script/<nas_id>', methods=['GET'])
def generate_mikrotik_script(nas_id):
    # فحص مباشر لحالة الكافيه/الشبكة (لا يعتمد على g لأن المسار قد يكون مستثنى)
    is_trial = True
    has_sub = False
    try:
        if 'user_id' in session:
            current_user = db_session.query(User).filter_by(id=session.get('user_id')).first()
            if current_user:
                trial_status = get_trial_status(current_user)
                is_trial = trial_status['is_trial']
                has_sub = not trial_status['is_locked'] and not trial_status['is_trial']
            else:
                # لو مستخدم غير موجود, اعتبر تجريبي (حظر)
                is_trial = True
                has_sub = False
        else:
            # زائر غير مسجل -> حظر الربط
            is_trial = True
            has_sub = False
    except Exception:
        is_trial = True
        has_sub = False
    
    # إذا كان الحساب تجريبي (أول 48 ساعة) أو منتهي الصلاحية، يتم حظر توليد سكريبت الربط التلقائي فوراً
    # للكافيهات: مسموح له طباعة وبيع الكروت لكن ممنوع ربط المايكروتيك حتى يدفع
    if is_trial or not has_sub:
        msg = "⚠️ نظام صقر كونكت: عذراً، لا يمكن ربط أجهزة المايكروتيك أو توليد سكريبت الاتصال التلقائي خلال الفترة التجريبية أو عند انتهاء الترخيص. يرجى تفعيل واشتراك الحساب أولاً لتفعيل جسور الربط المركزي."
        return Response(msg, mimetype='text/plain; charset=utf-8')
    
    # العميل بدون IP ثابت - هو من يتصل بنا (Reverse Connection)
    # نستخدم IP/دومين السيرفر المركزي كما يراه العميل (request.host) - أوتوماتيك
    server_ip = request.host.split(':')[0] if request.host else Config.RADIUS_HOST
    # لو الطلب لوكال (127.0.0.1) نحاول نجيب IP الشبكة الحقيقي تلقائياً عشان السكريبت يشتغل للمايكروتك
    if server_ip in ['127.0.0.1', 'localhost', '0.0.0.0']:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            server_ip = s.getsockname()[0]
            s.close()
        except:
            server_ip = Config.RADIUS_HOST if Config.RADIUS_HOST not in ['127.0.0.1','localhost','0.0.0.0'] else "YOUR_SERVER_IP"
    
    # جلب secret الخاص بالروتر من DB عبر nas_id (كل روتر له secret مختلف)
    radius_secret = Config.RADIUS_SECRET  # افتراضي
    try:
        router_obj = db_session.query(Router).filter_by(nas_id=nas_id).first()
        if router_obj and router_obj.radius_secret:
            radius_secret = router_obj.radius_secret
    except Exception:
        pass
    
    rsc_content = f"""/radius remove [find comment="SakrConnect_Radius"]
/radius add address={server_ip} secret={radius_secret} service=hotspot authentication-port=1812 accounting-port=1813 comment="SakrConnect_Radius"
/radius add address={server_ip} secret={radius_secret} service=ppp authentication-port=1812 accounting-port=1813 comment="SakrConnect_Radius"
/ip hotspot profile set [find name=default] radius-location-id="{nas_id}" use-radius=yes
"""
    return Response(rsc_content, mimetype='text/plain')

# ==========================================

@app.context_processor
def inject_global_data():
    current_role = session.get('role')
    
    sector_map = {
        'reseller': 'resellers',
        'cafe': 'cafes'
    }
    user_sector = sector_map.get(current_role, 'all')

    active_broadcast = None
    try:
        if current_role in ['admin', 'super_admin']:
            active_broadcast = db_session.query(BroadcastMessage).filter_by(is_active=True).order_by(BroadcastMessage.id.desc()).first()
        else:
            active_broadcast = db_session.query(BroadcastMessage).filter(
                BroadcastMessage.is_active == True,
                BroadcastMessage.target_sector.in_(['all', user_sector])
            ).order_by(BroadcastMessage.id.desc()).first()
    except Exception:
        pass

    default_msg = "🦅 مرحباً بكم في لوحة التحكم المركزية لنظام صقر كونكت (Sakr Connect Radius System) | خوادم المنظومة تعمل بكفاءة واستقرار. لطلبات الدعم الفني، التحديثات، أو تجديد تراخيص النظام، نسعد بتواصلكم عبر واتساب: 01033379719 - 01033379719."
    broadcast_text = active_broadcast.message if active_broadcast else default_msg

    radar_logs = []
    if current_role in ['admin', 'super_admin']:
        try:
            radar_logs = db_session.query(AuditLog).order_by(AuditLog.id.desc()).limit(5).all()
        except Exception:
            pass

    # تمرير متغيرات القفل والفترة التجريبية بشكل مركزي لجميع قوالب الـ HTML تلقائياً
    return dict(
        current_role=current_role,
        global_broadcast=broadcast_text,
        radar_logs=radar_logs,
        is_locked=getattr(g, 'is_locked', False),
        is_trial_active=getattr(g, 'is_trial_active', True)
    )

def requires_roles(*roles):
    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            
            user_role = session.get('role')
            if user_role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return wrapper

@app.route('/admin/api/broadcast', methods=['POST'])
@requires_roles('admin', 'super_admin')
def api_broadcast():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "بيانات مفقودة"}), 400
        
    message = data.get('message', '').strip()
    target = data.get('target', 'all')
    
    if not message:
        return jsonify({"status": "error", "message": "الرسالة فارغة"}), 400
        
    try:
        db_session.query(BroadcastMessage).filter_by(target_sector=target, is_active=True).update({"is_active": False})
        new_msg = BroadcastMessage(message=message, target_sector=target, is_active=True)
        db_session.add(new_msg)
        db_session.commit()
        
        return jsonify({"status": "success", "message": "تم بث الإشعار بنجاح"})
    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect('/sakr')
    
    user_role = session.get('role')
    
    if user_role in ['admin', 'super_admin']:
        return render_template('index.html', project_name="Sakr Connect")
    else:
        return redirect(url_for('auth.dashboard'))

@app.route('/admin/monitor')
@requires_roles('admin', 'super_admin')
def admin_monitor():
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from database.models import Voucher, ActiveSession, Network, Router
    # بيانات حية 100% بدون هارد كود - كلها من DB
    try:
        # 1. جلسات الكروت النشطة الآن (ActiveSession)
        try:
            active_vouchers = db_session.query(ActiveSession).count()
        except:
            active_vouchers = 0
        # fallback: Voucher active
        if active_vouchers == 0:
            try:
                active_vouchers = db_session.query(Voucher).filter_by(status='active').count()
            except: active_vouchers = 0

        # 2. إجمالي الكروت المصدرة هذا الشهر
        start_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        try:
            total_vouchers = db_session.query(Voucher).filter(Voucher.created_at >= start_month).count()
        except:
            total_vouchers = db_session.query(Voucher).count()

        # 3. كروت منتهية / مسدودة
        try:
            depleted_vouchers = db_session.query(Voucher).filter(Voucher.status.in_(['expired','suspended','depleted'])).count()
        except:
            depleted_vouchers = 0

        # 4. محاولات تخطي / أخطاء أمنية
        try:
            security_alerts = db_session.query(AuditLog).filter(AuditLog.action.in_(['login_failed','blocked_login','admin_login_failed'])).count()
        except:
            security_alerts = 0

        # 5. التوزيع الحي للشبكات
        networks = []
        try:
            all_networks = db_session.query(Network).all()
            for net in all_networks:
                # روترات الشبكة
                routers = db_session.query(Router).filter_by(network_id=net.id, is_deleted=False).all()
                router_ids = [r.id for r in routers]
                # متصلين الآن
                online_users = 0
                if router_ids:
                    online_users = db_session.query(ActiveSession).filter(ActiveSession.router_id.in_(router_ids)).count()
                # كروت الشبكة
                total_cards = db_session.query(Voucher).filter_by(network_id=net.id).count()
                used_cards = db_session.query(Voucher).filter_by(network_id=net.id).filter(Voucher.status.in_(['sold','active','used'])).count()
                networks.append({
                    'id': net.id,
                    'name': net.name,
                    'type': net.network_type or 'شبكة',
                    'online_users': online_users,
                    'total_cards': total_cards,
                    'used_cards': used_cards
                })
        except Exception as e:
            print(f"admin_monitor networks error: {e}")
            networks = []

        return render_template('admin_monitor.html', 
                               project_name="Sakr Connect",
                               active_vouchers=active_vouchers,
                               total_vouchers=total_vouchers,
                               depleted_vouchers=depleted_vouchers,
                               security_alerts=security_alerts,
                               networks=networks)
    except Exception as e:
        print(f"admin_monitor error: {e}")
        return render_template('admin_monitor.html', 
                               project_name="Sakr Connect",
                               active_vouchers=0,
                               total_vouchers=0,
                               depleted_vouchers=0,
                               security_alerts=0,
                               networks=[])

@app.route('/portal')
def portal():
    app_visible = True
    app_download_url = "#"
    
    if 'user_id' in session:
        client = db_session.query(NetworkClient).filter_by(id=session.get('network_id')).first()
        if client:
            app_visible = client.app_visible
            
    global_setting = db_session.query(GlobalSetting).filter_by(setting_key='app_download_url').first()
    if global_setting and global_setting.setting_value:
        app_download_url = global_setting.setting_value

    network_owner = {
        'name': 'صقر كونكت', 
        'whatsapp': '01033379719'
    }
    network_cards = []

    try:
        site_name_setting = db_session.query(GlobalSetting).filter_by(setting_key='site_name').first()
        if site_name_setting and site_name_setting.setting_value:
            network_owner['name'] = site_name_setting.setting_value

        whatsapp_setting = db_session.query(GlobalSetting).filter_by(setting_key='whatsapp_number').first()
        if whatsapp_setting and whatsapp_setting.setting_value:
            network_owner['whatsapp'] = whatsapp_setting.setting_value

        if hasattr(database.models, 'Card'):
            cards_data = db_session.query(database.models.Card).all()
            network_cards = [{'id': c.id, 'name': c.name, 'description': getattr(c, 'description', 'كارت شحن'), 'price': c.price} for c in cards_data]
        elif hasattr(database.models, 'Package'):
            packages_data = db_session.query(database.models.Package).all()
            network_cards = [{'id': p.id, 'name': p.name, 'description': getattr(p, 'description', 'باقة إنترنت'), 'price': p.price} for p in packages_data]
            
    except Exception as e:
        print(f"Error fetching dynamic portal data: {e}")

    return render_template('portal.html', 
                           network_cards=network_cards, 
                           network_owner=network_owner,
                           app_visible=app_visible,
                           app_download_url=app_download_url)

@app.route('/process_fast_purchase', methods=['POST'])
def process_fast_purchase():
    card_id = request.form.get('card_id')
    cash_number = request.form.get('cash_number')
    
    flash('جاري مراجعة التحصيل. ستصلك رسالة بالتفعيل.', 'success')
    return redirect(url_for('portal'))

@app.route('/subscriber/dashboard')
def subscriber_dashboard():
    current_user_data = {
        'name': 'عميل',
        'username': 'unknown'
    }
    network_owner = {
        'name': 'صقر كونكت',
        'whatsapp': '01033379719' 
    }
    
    try:
        site_name_setting = db_session.query(GlobalSetting).filter_by(setting_key='site_name').first()
        if site_name_setting and site_name_setting.setting_value:
            network_owner['name'] = site_name_setting.setting_value

        if 'user_id' in session and hasattr(database.models, 'Subscriber'):
            sub = db_session.query(database.models.Subscriber).filter_by(id=session['user_id']).first()
            if sub:
                current_user_data['name'] = getattr(sub, 'full_name', sub.username)
                current_user_data['username'] = sub.username
                
    except Exception as e:
        print(f"Error fetching dynamic subscriber data: {e}")

    return render_template('subscriber_dashboard.html',
                           current_user=current_user_data,
                           is_online=True,
                           consumption_percentage=0, 
                           used_quota='0',
                           remaining_quota='0',
                           total_quota='0',
                           days_remaining='0',
                           network_owner=network_owner)

@app.teardown_appcontext
def shutdown_session(exception=None):
    try:
        db_session.remove()
    except Exception:
        pass

@app.errorhandler(403)
def forbidden(e):
    return "<div style='text-align:center; margin-top:50px; font-family:tahoma;'><h2 style='color:#e11d48;'>🚨 عذراً، ليس لديك صلاحية للوصول لهذه الصفحة.</h2><a href='/'>العودة</a></div>", 403

@app.errorhandler(404)
def not_found(e):
    return "<div style='text-align:center; margin-top:50px; font-family:tahoma;'><h2>⚠️ عذراً، هذه الصفحة غير موجودة.</h2><a href='/'>العودة</a></div>", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)