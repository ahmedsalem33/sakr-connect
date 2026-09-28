# ==============================================================================
# SAKR CONNECT - CENTRAL AUTHENTICATION & GATEWAYS (LIVE/PRODUCTION)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: مسجلة باسم مشروع Sakr Connect
# الدعم الفني للمطور: 01033379719 - 01033379719
# العنوان: 
# ==============================================================================

import os
import time
from flask import Blueprint, render_template, session, request, jsonify, redirect, url_for, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from core.db_manager import db_session
from database.models import User, Subscriber, Router, SaasPackage, Network, ActiveSession, AdminNotification, AdminNotification, AuditLog, Voucher, FinancialTransaction
from core.auth.trial import get_trial_status, get_effective_owner

# حماية Brute Force: 3 محاولات -> بلوك 30 ثانية (في الذاكرة + DB)
_failed_logins = {}  # username -> {count, block_until}

auth_bp = Blueprint('auth', __name__)

# ==============================================================================
# [أدوات الحماية والحراسة - Gatekeepers]
# ==============================================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('role') not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def check_subscription_status(f):
    """
    حارس اللوحة المركزي: يقوم بغلق اللوحة كاملة وحظر التصفح أو عرض المشتركين
    بمجرد انتهاء الاشتراك أو مهلة الـ 48 ساعة دون دفع.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('is_locked'):
            flash('⚠️ انتهت صلاحية الاشتراك. يرجى سداد الفاتورة لتفعيل اللوحة مرة أخرى.', 'danger')
            return redirect(url_for('finance.sakr_account'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# [البوابة الأولى]: دخول الإدارة المركزية (السوبر أدمن)
# ==============================================================================
@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember')
        client_ip = request.remote_addr or 'unknown'
        # Brute force للإدارة أيضاً
        now_ts = time.time()
        attempt = _failed_logins.get(f"admin_{username}", {'count': 0, 'block_until': 0})
        if attempt['block_until'] > now_ts:
            remaining = int(attempt['block_until'] - now_ts)
            flash(f'⚠️ حظر مؤقت {remaining} ثانية بعد 3 محاولات.', 'danger')
            return render_template('admin_login.html')
        
        user = db_session.query(User).filter_by(username=username).first()
        if user and user.role in ['admin', 'super_admin'] and check_password_hash(user.password_hash, password):
            _failed_logins.pop(f"admin_{username}", None)
            session.clear()
            if remember in ['on', 'true', '1']:
                session.permanent = True
            session.update({
                'user_id': user.id, 
                'role': 'admin', 
                'is_admin': True,
                'logged_in': True,
                'username': user.username,
                'network_name': 'القيادة المركزية',
                'server_name': 'السيرفر الرئيسي'
            })
            try:
                db_session.add(AuditLog(code=username, action='admin_login_success', mac_address=client_ip, device_info=request.headers.get('User-Agent','')[:100], ap_location='admin'))
                db_session.commit()
            except: db_session.rollback()
            return redirect(url_for('auth.central_index'))
        
        # فشل
        attempt['count'] += 1
        if attempt['count'] >= 3:
            attempt['block_until'] = now_ts + 30
            attempt['count'] = 0
        _failed_logins[f"admin_{username}"] = attempt
        try:
            db_session.add(AuditLog(code=username, action='admin_login_failed', mac_address=client_ip, device_info='login', ap_location='admin'))
            db_session.commit()
        except: db_session.rollback()
        flash('⚠️ بيانات الدخول غير صحيحة.', 'danger')
    return render_template('admin_login.html')

# ==============================================================================
# [البوابة الثانية]: دخول الأنظمة الأساسية (الشبكات والكافيهات)
# ==============================================================================
# دخول مباشر بنوع محدد من واجهة الووردبريس (نظام الشبكات / نظام الكافيهات)
@auth_bp.route('/login/<system_type>', methods=['GET'])
def login_typed(system_type):
    if system_type not in ['network', 'cafe']:
        abort(404)
    next_page = request.args.get('next')
    return render_template('login.html', next=next_page, selected_system=system_type)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    next_page = request.args.get('next') or request.form.get('next')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        system_type = request.form.get('system_type') 
        remember = request.form.get('remember')
        client_ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown')

        # حماية Brute Force: 3 محاولات غلط -> بلوك 30 ثانية
        now_ts = time.time()
        attempt = _failed_logins.get(username, {'count': 0, 'block_until': 0})
        if attempt['block_until'] > now_ts:
            remaining = int(attempt['block_until'] - now_ts)
            flash(f'⚠️ تم حظر الدخول مؤقتاً بعد 3 محاولات خاطئة. حاول بعد {remaining} ثانية.', 'danger')
            # تسجيل محاولة محظورة
            try:
                db_session.add(AuditLog(code=username, action='blocked_login', mac_address=client_ip, device_info='blocked', ap_location='login'))
                db_session.commit()
            except: db_session.rollback()
            return render_template('login.html', next=next_page)
        
        try:
            # 1. فحص جدول المديرين، الكافيهات، والموزعين (جدول User)
            user = db_session.query(User).filter_by(username=username).first()
            
            if user and check_password_hash(user.password_hash, password):
                session.clear()
                
                if remember in ['on', 'true', '1']:
                    session.permanent = True
                
                # استخدام الدالة الموحدة لحساب حالة التجربة والقفل
                trial_status = get_trial_status(user)
                
                # 2. استعلام الشبكة والسيرفر لإلغاء القيمة الوهمية "شبكة مخصصة"
                owner_id = user.parent_id if user.role in ['reseller', 'manager'] else user.id
                network = db_session.query(Network).filter_by(owner_id=owner_id).first()
                router = db_session.query(Router).filter_by(network_id=network.id).first() if network else None
                
                # المعالجة الديناميكية لاسم الشبكة والكافيه
                if network and network.name:
                    entity_name = network.name
                else:
                    entity_name = f"كافيه {user.username}" if user.role == 'cafe' else f"شبكة {user.username}"

                # المعالجة الديناميكية لاسم السيرفر المربوط
                server_name = router.name if router else "السيرفر الرئيسي"

                session.update({
                    'user_id': user.id, 
                    'role': user.role, 
                    'is_admin': False,
                    'username': user.username, 
                    'fullname': getattr(user, 'fullname', user.username), 
                    'system_type': system_type if system_type else user.role,
                    'billing_code': getattr(user, 'billing_code', ''),
                    'is_locked': trial_status['is_locked'],
                    'is_trial': trial_status['is_trial'],
                    'trial_end_iso': trial_status['trial_end_iso'],
                    'remaining_seconds': trial_status['remaining_seconds'],
                    'country': getattr(user, 'country', 'EG'),
                    'permissions': getattr(user, 'permissions', None) if user.role == 'reseller' else None,
                    'network_name': entity_name,
                    'server_name': server_name,
                    'show_merge': getattr(user, 'show_merge', True)
                })
                
                # تسجيل دخول ناجح -> تصفير عداد المحاولات + AuditLog
                _failed_logins.pop(username, None)
                try:
                    db_session.add(AuditLog(code=username, action='login_success', mac_address=client_ip, device_info=request.headers.get('User-Agent','')[:100], ap_location=system_type or user.role))
                    db_session.commit()
                except: db_session.rollback()

                # Redirect to next page or dashboard
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('auth.dashboard'))

            # في حالة عدم وجود الحساب أو باسورد غلط -> تسجيل فشل + بلوك بعد 3
            attempt = _failed_logins.get(username, {'count': 0, 'block_until': 0})
            attempt['count'] += 1
            if attempt['count'] >= 3:
                attempt['block_until'] = now_ts + 30  # بلوك 30 ثانية
                attempt['count'] = 0
                flash('⚠️ 3 محاولات خاطئة - تم الحظر 30 ثانية.', 'danger')
            _failed_logins[username] = attempt
            try:
                db_session.add(AuditLog(code=username, action='login_failed', mac_address=client_ip, device_info=request.headers.get('User-Agent','')[:100], ap_location=system_type or 'unknown'))
                db_session.commit()
            except: db_session.rollback()
            flash('⚠️ بيانات الدخول غير صحيحة.', 'danger')
            
        except Exception as e:
            db_session.rollback()
            print(f"CRITICAL LOGIN ERROR: {str(e)}")
            flash('⚠️ حدث خطأ داخلي في السيرفر أثناء محاولة تسجيل الدخول.', 'danger')

    return render_template('login.html', next=next_page)

# ==============================================================================
# فحص توفر اسم المستخدم (AJAX)
# ==============================================================================
@auth_bp.route('/api/check_username', methods=['POST'])
def check_username():
    data = request.get_json()
    if not data or 'username' not in data:
        return jsonify({"exists": False}), 400

    username = data.get('username')

    try:
        user_exists = db_session.query(User).filter_by(username=username).first()
        sub_exists = db_session.query(Subscriber).filter_by(username=username).first()

        if user_exists or sub_exists:
            return jsonify({"exists": True}), 200
        
        return jsonify({"exists": False}), 200

    except Exception as e:
        return jsonify({"exists": False, "error": str(e)}), 500

# ==============================================================================
# [بوابة التسجيل]: إنشاء حساب جديد لعملاء SaaS (معدلة لسحب كامل التفاصيل)
# ==============================================================================
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # قراءة معاملات WordPress Redirect
    wp_ref = request.args.get('ref')
    wp_plan = request.args.get('plan', type=int)
    
    if request.method == 'POST':
        usage_type = request.form.get('usage_type')
        fullname = request.form.get('fullname')
        username = request.form.get('username')
        password = request.form.get('password')
        phone1 = request.form.get('phone1')
        plan_id = request.form.get('plan_id') or request.form.get('wp_plan')
        network_name = request.form.get('network_name') 
        system_type = request.form.get('system_type') or usage_type
        
        # كشف الدولة تلقائياً من Cloudflare Header
        country = request.headers.get('CF-IPCountry', 'EG')
        if country == 'EG':
            country = 'EG'
        else:
            country = 'INT'
        
        if usage_type not in ['network', 'cafe']:
            flash('⚠️ غير مصرح بالتسجيل من هنا. يرجى مراجعة إدارة النظام.', 'danger')
            return redirect(url_for('auth.register'))

        if not username or not fullname or not password:
            flash('⚠️ جميع البيانات الأساسية مطلوبة.', 'danger')
            return redirect(url_for('auth.register'))

        if usage_type in ['network', 'cafe'] and not network_name:
            flash('⚠️ اسم الشبكة مطلوب لعملاء الشبكات والكافيهات.', 'danger')
            return redirect(url_for('auth.register'))

        try:
            user_exists = db_session.query(User).filter_by(username=username).first()
            sub_exists = db_session.query(Subscriber).filter_by(username=username).first()
            
            if user_exists or sub_exists:
                flash('⚠️ اسم المستخدم مسجل مسبقاً، يرجى اختيار اسم آخر.', 'warning')
                return redirect(url_for('auth.register'))

            import random
            prefix_map = {'network': 'NET', 'cafe': 'CAF'}
            prefix = prefix_map.get(usage_type, 'USR')
            billing_code = f"{prefix}-{random.randint(100000, 999999)}"

            trial_end_date = datetime.utcnow() + timedelta(hours=48)

            # 1. إنشاء المستخدم الأساسي - للكافيهات والشبكات: التجربة 48h بدون saas_expiry فعال
            # saas_expiry_date يبقى None خلال التجربة ويُضبط فقط عند دفع أول باقة (30 يوم)
            new_user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=usage_type,
                billing_code=billing_code,
                account_status='trial',
                saas_expiry_date=None,
                country=country
            )
            # نحفظ trial_end في grace_period_end للاستخدام في trial.py لو احتجنا
            if hasattr(new_user, 'grace_period_end'):
                new_user.grace_period_end = trial_end_date
            
            if hasattr(new_user, 'fullname'): new_user.fullname = fullname
            if hasattr(new_user, 'phone1'): new_user.phone1 = phone1
            if hasattr(new_user, 'package_id'): new_user.package_id = plan_id or wp_plan

            db_session.add(new_user)
            db_session.flush()

            # 2. إنشاء السجل الخاص بالشبكة وربطه بالمستخدم
            if usage_type in ['network', 'cafe'] and network_name:
                new_network = Network(
                    name=network_name,
                    owner_id=new_user.id,
                    network_type=usage_type
                )
                
                if hasattr(new_network, 'location'): new_network.location = country
                if hasattr(new_network, 'system_type'): new_network.system_type = system_type
                db_session.add(new_network)

            db_session.commit()
            
            # إنشاء إشعار للأدمن المركزي عند تسجيل شبكة/كافيه جديد
            try:
                admin_notif = AdminNotification(
                    title="عميل جديد - تسجيل شبكة/كافيه",
                    message=f"تم تسجيل {usage_type}: {network_name} (المستخدم: {username}) - كود التحصيل: {billing_code}",
                    related_user_id=new_user.id
                )
                db_session.add(admin_notif)
                db_session.commit()
            except Exception:
                pass  # لا نفشل التسجيل لو الإشعار فشل
            
            flash(f'✅ تم إنشاء الحساب بنجاح! كود التحصيل الخاص بك هو: {billing_code}', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db_session.rollback()
            print(f"\n====================================\nCRITICAL REGISTRATION ERROR (DATABASE):\n{str(e)}\n====================================\n")
            flash('⚠️ حدث خطأ داخلي أثناء التسجيل، يرجى مراجعة التيرمينال لمعرفة السبب.', 'danger')
            return redirect(url_for('auth.register'))

    try:
        # فلترة الباقات حسب الدولة (مصر vs دولي)
        country = request.headers.get('CF-IPCountry', 'EG')
        is_egypt = country == 'EG'
        
        query = db_session.query(SaasPackage).filter_by(is_active=True)
        if is_egypt:
            query = query.filter(SaasPackage.system_type.in_(['network', 'cafe']))
        else:
            query = query.filter(SaasPackage.system_type.in_(['network_int', 'cafe_int']))
        
        active_packages = query.all()
        dynamic_packages = [{"id": pkg.id, "name": pkg.name, "type": pkg.system_type, "price": pkg.price} for pkg in active_packages]
    except Exception:
        dynamic_packages = []

    return render_template('register.html', 
                           dynamic_packages=dynamic_packages,
                           wp_plan=wp_plan,
                           wp_ref=wp_ref,
                           detected_country=country)

# ==============================================================================
# [استعادة كلمة المرور]
# ==============================================================================
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    return "صفحة استعادة كلمة المرور - قيد التطوير"

# ==============================================================================
# [البوابة الثالثة]: دخول التطبيق للكيانات الفرعية (API)
# ==============================================================================
@auth_bp.route('/api/v1/app/login', methods=['POST'])
def app_login():
    data = request.get_json()
    if not data: return jsonify({"status": "error"}), 400
    
    username, password, account_type = data.get('username'), data.get('password'), data.get('type')
    
    try:
        if account_type in ['reseller', 'network', 'cafe']:
            user = db_session.query(User).filter_by(username=username, role=account_type).first()
            if user and check_password_hash(user.password_hash, password):
                return jsonify({"status": "success", "token": f"{account_type.upper()}_{user.id}"})
        
        elif account_type == 'subscriber':
            sub = db_session.query(Subscriber).filter_by(username=username).first()
            if sub and sub.password == password:
                return jsonify({"status": "success", "token": f"SUB_{sub.id}"})
                
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================================================================
# [اللوحات والتحكم المركزي الحامي من الصلاحيات و تواريخ الانتهاء]
# ==============================================================================
@auth_bp.route('/admin/central/dashboard')
@login_required
@role_required(['admin']) 
def central_index():
    from sqlalchemy import func as _func
    stats = {
        'cpu': None, 'ram': None, 'db_ms': None,
        'routers_total': 0, 'routers_online': 0,
        'home_total': 0, 'home_online': 0,
        'cafe_total': 0, 'net_total': 0,
        'vouchers_total': 0, 'vouchers_today': 0,
        'sessions_now': 0,
        'revenue_today': 0.0, 'revenue_total': 0.0,
        'balances_total': 0.0, 'debts_total': 0.0,
        'alerts_total': 0,
        'top_network': 'لا توجد شبكات بعد',
        'v_days': [], 'v_counts': [],
        'r_days': [], 'r_sums': [],
        'live_logs': [],
    }
    try:
        try:
            import psutil as _psutil
            stats['cpu'] = int(_psutil.cpu_percent(interval=None))
            stats['ram'] = int(_psutil.virtual_memory().percent)
        except Exception:
            pass

        try:
            import time as _time
            _t0 = _time.time()
            db_session.query(User.id).first()
            stats['db_ms'] = int((_time.time() - _t0) * 1000)
        except Exception:
            pass

        stats['routers_total'] = db_session.query(Router).count()
        active_router_ids = set(
            r[0] for r in db_session.query(ActiveSession.router_id).distinct().all() if r[0]
        )
        if active_router_ids:
            stats['routers_online'] = db_session.query(Router).filter(Router.id.in_(list(active_router_ids))).count()
        stats['sessions_now'] = db_session.query(ActiveSession).count()

        stats['home_total'] = db_session.query(Subscriber).filter_by(sub_type='home').count()
        stats['home_online'] = db_session.query(ActiveSession).filter_by(type='pppoe').count()
        stats['cafe_total'] = db_session.query(User).filter_by(role='cafe').count()
        stats['net_total'] = db_session.query(User).filter(User.role.in_(['network', 'reseller'])).count()

        stats['vouchers_total'] = db_session.query(Voucher).count()
        _today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            stats['vouchers_today'] = db_session.query(Voucher).filter(Voucher.created_at >= _today).count()
        except Exception:
            stats['vouchers_today'] = 0

        try:
            stats['revenue_today'] = float(db_session.query(_func.coalesce(_func.sum(FinancialTransaction.amount), 0)).filter(
                FinancialTransaction.created_at >= _today,
                FinancialTransaction.payment_status == 'paid').scalar() or 0)
            stats['revenue_total'] = float(db_session.query(_func.coalesce(_func.sum(FinancialTransaction.amount), 0)).filter(
                FinancialTransaction.payment_status == 'paid').scalar() or 0)
        except Exception:
            pass
        try:
            stats['balances_total'] = float(db_session.query(_func.coalesce(_func.sum(User.current_balance), 0)).filter(
                User.role.notin_(['admin', 'super_admin'])).scalar() or 0)
            stats['debts_total'] = float(db_session.query(_func.coalesce(_func.sum(User.debt), 0)).filter(
                User.role.notin_(['admin', 'super_admin'])).scalar() or 0)
        except Exception:
            pass
        try:
            stats['alerts_total'] = db_session.query(AuditLog).filter(
                AuditLog.action.in_(['login_failed', 'admin_login_failed', 'blocked_login'])).count()
        except Exception:
            pass

        try:
            nets = db_session.query(Network).all()
            best_name, best_n = 'لا توجد شبكات بعد', 0
            for _n in nets:
                _c = db_session.query(Subscriber).filter_by(network_id=_n.id).count()
                if _c > best_n:
                    best_name, best_n = _n.name, _c
            if best_n > 0:
                stats['top_network'] = '{} ({} مشترك)'.format(best_name, best_n)
        except Exception:
            pass

        try:
            rows = db_session.query(
                _func.date(Voucher.created_at), _func.count(Voucher.id)
            ).filter(Voucher.created_at >= datetime.utcnow() - timedelta(days=6)
            ).group_by(_func.date(Voucher.created_at)).order_by(_func.date(Voucher.created_at)).all()
            stats['v_days'] = [str(r[0]) for r in rows]
            stats['v_counts'] = [int(r[1]) for r in rows]
        except Exception:
            pass
        try:
            rows = db_session.query(
                _func.date(FinancialTransaction.created_at),
                _func.coalesce(_func.sum(FinancialTransaction.amount), 0)
            ).filter(FinancialTransaction.created_at >= datetime.utcnow() - timedelta(days=9),
                     FinancialTransaction.payment_status == 'paid'
            ).group_by(_func.date(FinancialTransaction.created_at)
            ).order_by(_func.date(FinancialTransaction.created_at)).all()
            stats['r_days'] = [str(r[0]) for r in rows]
            stats['r_sums'] = [float(r[1] or 0) for r in rows]
        except Exception:
            pass

        try:
            _logs = db_session.query(AuditLog).order_by(AuditLog.id.desc()).limit(12).all()
            for _l in _logs:
                _ts = getattr(_l, 'timestamp', None)
                stats['live_logs'].append({
                    'time': _ts.strftime('%H:%M:%S') if _ts else '#{}'.format(_l.id),
                    'action': _l.action or '',
                    'code': _l.code or '',
                })
        except Exception:
            pass
    except Exception as e:
        print('central_index stats error: {}'.format(e))

    return render_template('index.html', page_title="التحكم المركزي", central_stats=stats)

@auth_bp.route('/system/dashboard')
@login_required
@check_subscription_status # تفعيل حارس الحساب المركزي على لوحة التحكم بالكامل
def dashboard():
    user_id = session.get('user_id')
    role = session.get('role')
    
    # تحديد المالك الأساسي للشبكة للحصول على الإحصائيات الدقيقة
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()

    # القاموس الافتراضي للإحصائيات (Zero-state)
    stats = {
        'cpu_usage': 0, 'ram_usage': 0, 'network_capacity': 0, 'sales_target': 0,
        'total_clients': 0, 'active_sessions': 0, 'available_clients': 0,
        'active_vouchers': 0, 'active_pppoe': 0, 'expired_clients': 0,
        'warning_clients': 0, 'suspended_clients': 0, 'exceeded_clients': 0,
        'new_clients': 0, 'shift_sales': 0, 'sold_vouchers': 0,
        'active_cafe_users': 0, 'connected_devices': 0, 'quota_used': 0, 'quota_total': 1
    }

    # حقن البيانات الحية من قاعدة البيانات في حال وجود شبكة للعميل
    if owner_network:
        # استعلامات المشتركين المربوطين بالشبكة
        subs_query = db_session.query(Subscriber).filter_by(network_id=owner_network.id)
        
        stats['total_clients'] = subs_query.count()
        stats['active_pppoe'] = subs_query.filter_by(sub_type='home').count()
        stats['active_vouchers'] = subs_query.filter_by(sub_type='hotspot').count()
        stats['suspended_clients'] = subs_query.filter_by(status='suspended').count()
        
        # استعلامات الروترات والجلسات الحية (الرادار)
        routers = db_session.query(Router).filter_by(network_id=owner_network.id).all()
        router_ids = [r.id for r in routers]
        if router_ids:
            stats['active_sessions'] = db_session.query(ActiveSession).filter(ActiveSession.router_id.in_(router_ids)).count()
            stats['connected_devices'] = len(router_ids)
            
        # العملاء المتاحين (مقارنة الحد الأقصى للباقة بالعملاء الحاليين)
        max_subs = getattr(current_user, 'max_subscribers', 0)
        if max_subs > 0:
            stats['available_clients'] = max(0, max_subs - stats['total_clients'])
        else:
            stats['available_clients'] = "مفتوح"

    context = {
        'current_role': role,
        'is_trial': session.get('is_trial'), 
        'stats': stats,
        'pppoe_users': [],
        'hotspot_vouchers': []
    }
    return render_template('dashboard.html', **context)

# ==============================================================================
# [واجهات الـ API للقوائم الجانبية السريعة في الداشبورد]
# ==============================================================================
@auth_bp.route('/api/quick_drawer/all')
@login_required
def get_drawer_all_clients():
    user_id = session.get('user_id')
    role = session.get('role')
    
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    
    clients_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id).all()
        for sub in subs:
            clients_data.append({
                "name": getattr(sub, 'full_name', sub.username),
                "username": sub.username,
                "status": "نشط" if sub.status == 'active' else "موقوف",
                "ip": "غير متاح حالياً", 
                "mac": sub.mac_address or "غير مرتبط",
                "type": "هوت سبوت" if sub.sub_type == 'hotspot' else "برودباند",
                "debt": sub.balance or 0
            })
            
    return jsonify({"success": True, "data": clients_data})

@auth_bp.route('/api/quick_drawer/active_sessions')
@login_required
def get_drawer_active_sessions():
    user_id = session.get('user_id')
    role = session.get('role')
    
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    
    sessions_data = []
    if owner_network:
        routers = db_session.query(Router).filter_by(network_id=owner_network.id).all()
        router_ids = [r.id for r in routers]
        
        if router_ids:
            active_sessions = db_session.query(ActiveSession).filter(ActiveSession.router_id.in_(router_ids)).all()
            for s in active_sessions:
                sessions_data.append({
                    "username": s.username,
                    "ip": s.ip_address,
                    "mac": getattr(s, 'mac_address', 'N/A'),
                    "uptime": str(getattr(s, 'uptime', 'N/A')),
                    "download": round(getattr(s, 'download_bytes', 0) / (1024**2), 2), 
                    "upload": round(getattr(s, 'upload_bytes', 0) / (1024**2), 2)
                })
                
    return jsonify({"success": True, "data": sessions_data})

@auth_bp.route('/api/quick_drawer/vouchers')
@login_required
def get_drawer_vouchers():
    user_id = session.get('user_id')
    role = session.get('role')
    
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    
    vouchers_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id, sub_type='hotspot').all()
        for sub in subs:
            vouchers_data.append({
                "username": sub.username,
                "status": "نشط" if sub.status == 'active' else "منتهي",
                "quota_used": f"{getattr(sub, 'quota_used', 0)} GB",
                "quota_total": f"{getattr(sub, 'quota_total', 0)} GB",
            })
            
    return jsonify({"success": True, "data": vouchers_data})

@auth_bp.route('/api/quick_drawer/available')
@login_required
def get_drawer_available():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    
    available_data = []
    if owner_network:
        total_subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id).count()
        max_subs = getattr(current_user, 'max_subscribers', 0)
        available_count = max(0, max_subs - total_subs) if max_subs > 0 else 0
        
        available_data.append({
            "info": f"متبقي {available_count} مشترك",
            "available_count": available_count
        })
    return jsonify({"success": True, "data": available_data})

@auth_bp.route('/api/quick_drawer/suspended')
@login_required
def get_drawer_suspended():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    
    suspended_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id, status='suspended').all()
        for sub in subs:
            suspended_data.append({
                "username": sub.username,
                "name": getattr(sub, 'full_name', sub.username),
                "reason": "توقف إداري"
            })
    return jsonify({"success": True, "data": suspended_data})

@auth_bp.route('/api/quick_drawer/expired')
@login_required
def get_drawer_expired():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    expired_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id).all()
        for sub in subs:
            if sub.expiry_date and sub.expiry_date < datetime.utcnow():
                expired_data.append({"username": sub.username, "name": getattr(sub, 'full_name', sub.username), "status": "منتهي", "expiry": sub.expiry_date.strftime('%Y-%m-%d')})
    return jsonify({"success": True, "data": expired_data})

@auth_bp.route('/api/quick_drawer/warning')
@login_required
def get_drawer_warning():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    warning_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id).all()
        for sub in subs:
            if sub.expiry_date and 0 <= (sub.expiry_date - datetime.utcnow()).days <= 3:
                warning_data.append({"username": sub.username, "name": getattr(sub, 'full_name', sub.username), "days_left": (sub.expiry_date - datetime.utcnow()).days})
    return jsonify({"success": True, "data": warning_data})

@auth_bp.route('/api/quick_drawer/exceeded')
@login_required
def get_drawer_exceeded():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    exceeded_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id).all()
        for sub in subs:
            if sub.quota_total and sub.quota_used and sub.quota_used >= sub.quota_total:
                exceeded_data.append({"username": sub.username, "name": getattr(sub, 'full_name', sub.username), "used": f"{sub.quota_used}/{sub.quota_total} GB"})
    return jsonify({"success": True, "data": exceeded_data})

@auth_bp.route('/api/quick_drawer/new')
@login_required
def get_drawer_new():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    new_data = []
    if owner_network:
        week_ago = datetime.utcnow() - timedelta(days=7)
        subs = db_session.query(Subscriber).filter(Subscriber.network_id==owner_network.id, Subscriber.created_at >= week_ago).all()
        for sub in subs:
            new_data.append({"username": sub.username, "name": getattr(sub, 'full_name', sub.username), "created": sub.created_at.strftime('%Y-%m-%d')})
    return jsonify({"success": True, "data": new_data})

@auth_bp.route('/api/quick_drawer/pppoe')
@login_required
def get_drawer_pppoe():
    user_id = session.get('user_id')
    role = session.get('role')
    current_user = db_session.query(User).filter_by(id=user_id).first()
    owner_id = current_user.parent_id if role in ['reseller', 'manager'] else user_id
    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()
    pppoe_data = []
    if owner_network:
        subs = db_session.query(Subscriber).filter_by(network_id=owner_network.id, sub_type='home', status='active').all()
        for sub in subs:
            pppoe_data.append({"username": sub.username, "name": getattr(sub, 'full_name', sub.username), "status": sub.status})
    return jsonify({"success": True, "data": pppoe_data})

@auth_bp.route('/logout')
def logout():
    role = session.get('role')
    username = session.get('username', 'unknown')
    client_ip = request.remote_addr or 'unknown'
    try:
        db_session.add(AuditLog(code=username, action='logout', mac_address=client_ip, device_info=role or 'unknown', ap_location='logout'))
        db_session.commit()
    except: db_session.rollback()
    session.clear()
    if role == 'admin':
        return redirect(url_for('auth.admin_login'))
    return redirect(url_for('auth.login'))