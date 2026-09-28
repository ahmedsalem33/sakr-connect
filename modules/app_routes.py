# ==============================================================================
# SAKR CONNECT - APP ROUTES & UNIFIED API AUTHENTICATION
# حقوق المطور: Sakr Media Agency | صقر ميديا
# الدعم الفني: 01033379719 - 01033379719
# ==============================================================================

from flask import Blueprint, request, redirect, url_for, flash, jsonify, current_app
from core.db_manager import db_session
from database.models import Subscriber, User, Network, SystemAdmin, PendingInvoice, FinancialTransaction, Router, Voucher, Offer
from database.central_models import GlobalSetting, NetworkClient
import secrets
import re
import datetime
import json
from werkzeug.security import check_password_hash, generate_password_hash

app_bp = Blueprint('app_webview', __name__)

# ==============================================================================
# Helper: قراءة إعدادات التطبيق من GlobalSetting
# ==============================================================================
def get_app_settings():
    """يقرأ إعدادات التطبيق من قاعدة البيانات مع قيم افتراضية"""
    settings = {}
    keys = [
        'app_version', 'app_download_url', 'app_locked', 'app_force_update',
        'app_commission_type', 'app_commission_value', 'app_commission_min',
        'app_commission_max', 'app_support_phones', 'app_maintenance_mode'
    ]
    for key in keys:
        gs = db_session.query(GlobalSetting).filter_by(setting_key=key).first()
        if gs:
            val = gs.setting_value
            if key in ['app_locked', 'app_force_update', 'app_maintenance_mode']:
                settings[key] = val.lower() == 'true'
            elif key in ['app_commission_value', 'app_commission_min', 'app_commission_max']:
                settings[key] = float(val)
            elif key == 'app_support_phones':
                try:
                    settings[key] = json.loads(val)
                except:
                    settings[key] = ['01033379719', '01033379719']
            else:
                settings[key] = val
        else:
            # Defaults
            defaults = {
                'app_version': '1.0.0',
                'app_download_url': 'https://example.com/sakr_connect_pay.apk',
                'app_locked': False,
                'app_force_update': False,
                'app_commission_type': 'percent',
                'app_commission_value': 2.5,
                'app_commission_min': 0.50,
                'app_commission_max': 50.0,
                'app_support_phones': ['01033379719', '01033379719'],
                'app_maintenance_mode': False,
            }
            settings[key] = defaults.get(key)
    return settings

def get_network_client(network_id):
    """جلب بيانات NetworkClient مع التحقق من وجودها"""
    return db_session.query(NetworkClient).filter_by(id=network_id).first()

def calculate_app_commission(amount, client=None):
    """يحسب عمولة التطبيق بناءً على الإعدادات العامة أو المخصصة للعميل"""
    app_settings = get_app_settings()
    
    # تحديد نوع وقيمة العمولة
    if client and client.commission_mode == 'custom':
        commission_type = 'percent'
        commission_value = client.custom_commission_rate or 0
    elif client and client.commission_mode == 'disabled':
        return 0.0
    else:
        commission_type = app_settings.get('app_commission_type', 'percent')
        commission_value = app_settings.get('app_commission_value', 2.5)
    
    if commission_type == 'percent':
        commission = amount * (commission_value / 100)
    else:
        commission = commission_value
    
    # تطبيق الحدود الدنيا والقصوى
    min_comm = app_settings.get('app_commission_min', 0.50)
    max_comm = app_settings.get('app_commission_max', 50.0)
    commission = max(min_comm, min(max_comm, commission))
    
    return round(commission, 2)

# ==============================================================================
# 1. مسارات واجهة الويب (Webview Routes) - مخصصة لواجهة العرض الديناميكية
# ==============================================================================

@app_bp.route('/app/<int:network_id>/login', methods=['GET', 'POST'])
def app_login(network_id):
    # التوجيه إلى مسار البورتال الصحيح مباشرة لمنع خطأ 404 أو BuildError
    portal_url = "/portal"

    if request.method == 'GET':
        return redirect(portal_url)

    login_id = request.form.get('login_id')
    password = request.form.get('password')
    role = request.form.get('role')

    if role == 'admin':
        # الطبقة المركزية: الإدارة العليا
        admin = db_session.query(SystemAdmin).filter(
            SystemAdmin.username == login_id
        ).first()
        
        if admin and check_password_hash(admin.password_hash, password):
            return redirect(url_for('app_webview.admin_dashboard', admin_id=admin.id))

    elif role == 'reseller':
        # طبقة أصحاب الشبكات والموزعين
        reseller = db_session.query(User).filter(
            User.role == 'reseller',
            User.username == login_id
        ).first()
        
        if reseller and check_password_hash(reseller.password_hash, password):
            permissions = reseller.permissions or {}
            if not permissions.get('perm_app_access', True):
                flash("غير مصرح لك بالدخول من التطبيق. راجع إدارة الشبكة.", "error")
                return redirect(portal_url)
            
            return redirect(url_for('app_webview.reseller_dashboard', res_id=reseller.id))

    elif role == 'subscriber':
        # طبقة المشتركين
        subscriber = db_session.query(Subscriber).filter(
            Subscriber.network_id == network_id,
            Subscriber.username == login_id
        ).first()
        
        if subscriber and subscriber.password == password:
            return redirect(url_for('app_webview.subscriber_dashboard', sub_id=subscriber.id))

    # التوجيه المباشر للبورتال في حالة خطأ البيانات
    flash("بيانات الدخول غير صحيحة", "error")
    return redirect(portal_url)

    login_id = request.form.get('login_id')
    password = request.form.get('password')
    role = request.form.get('role')

    if role == 'admin':
        # الطبقة المركزية: الإدارة العليا
        admin = db_session.query(SystemAdmin).filter(
            SystemAdmin.username == login_id
        ).first()
        if admin and check_password_hash(admin.password_hash, password):
            return redirect(url_for('app_webview.admin_dashboard', admin_id=admin.id))
    elif role == 'reseller':
        # طبقة أصحاب الشبكات والموزعين
        reseller = db_session.query(User).filter(
            User.role == 'reseller',
            User.username == login_id
        ).first()
        
        if reseller and check_password_hash(reseller.password_hash, password):
            permissions = reseller.permissions or {}
            if not permissions.get('perm_app_access', True):
                flash("غير مصرح لك بالدخول من التطبيق. راجع إدارة الشبكة.", "error")
                return redirect(portal_url)
            
            return redirect(url_for('app_webview.reseller_dashboard', res_id=reseller.id))

    elif role == 'subscriber':
        # طبقة المشتركين
        subscriber = db_session.query(Subscriber).filter(
            Subscriber.network_id == network_id,
            Subscriber.username == login_id
        ).first()
        
        if subscriber and subscriber.password == password:
            return redirect(url_for('app_webview.subscriber_dashboard', sub_id=subscriber.id))

    # التوجيه المباشر للبورتال في حالة خطأ البيانات
    flash("بيانات الدخول غير صحيحة", "error")
    return redirect(portal_url)

@app_bp.route('/app/admin/<int:admin_id>')
def admin_dashboard(admin_id):
    from flask import render_template
    admin = db_session.query(SystemAdmin).filter_by(id=admin_id).first()
    if not admin:
        return "غير موجود", 404
    # بيانات حية للإدارة المركزية
    total_networks = db_session.query(Network).count()
    total_routers = db_session.query(Router).filter_by(is_deleted=False).count()
    total_subs = db_session.query(Subscriber).count()
    total_vouchers = db_session.query(Voucher).count()
    return render_template('reseller_dashboard.html', reseller={
        'balance': 'مركزي',
        'profit_today': total_subs,
        'sales_monthly': total_vouchers,
        'net_to_network': total_networks
    })

@app_bp.route('/app/reseller/<int:res_id>')
def reseller_dashboard(res_id):
    from flask import render_template
    from datetime import datetime, timedelta
    from sqlalchemy import func
    reseller = db_session.query(User).filter_by(id=res_id).first()
    if not reseller:
        return "غير موجود", 404
    # بيانات حية بدون هارد كود
    today = datetime.utcnow().date()
    start_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # مبيعات اليوم/الشهر من FinancialTransaction
    try:
        profit_today = db_session.query(func.sum(FinancialTransaction.amount)).filter(
            FinancialTransaction.user_id==res_id,
            FinancialTransaction.created_at >= datetime.combine(today, datetime.min.time())
        ).scalar() or 0
        sales_monthly = db_session.query(func.sum(FinancialTransaction.amount)).filter(
            FinancialTransaction.user_id==res_id,
            FinancialTransaction.created_at >= start_month
        ).scalar() or 0
    except:
        profit_today = 0
        sales_monthly = 0
    balance = getattr(reseller, 'current_balance', 0) or 0
    # الصافي للمورد = الرصيد بعد خصم العمولة
    net_to_network = balance
    return render_template('reseller_dashboard.html', reseller={
        'balance': f"{balance:.2f}",
        'profit_today': f"{profit_today:.2f}",
        'sales_monthly': f"{sales_monthly:.2f}",
        'net_to_network': f"{net_to_network:.2f}"
    })

@app_bp.route('/app/subscriber/<int:sub_id>')
def subscriber_dashboard(sub_id):
    from flask import render_template
    sub = db_session.query(Subscriber).filter_by(id=sub_id).first()
    if not sub:
        return "غير موجود", 404
    # بيانات حية للمشترك
    offer = db_session.query(Offer).filter_by(id=sub.offer_id).first() if sub.offer_id else None
    quota_total = getattr(sub, 'quota_total', 0) or (offer.quota_gb if offer else 0)
    quota_used = getattr(sub, 'quota_used', 0) or 0
    remaining = max(0, quota_total - quota_used)
    return render_template('reseller_dashboard.html', reseller={
        'balance': f"{remaining:.1f} GB متبقي",
        'profit_today': sub.status,
        'sales_monthly': sub.expiry_date.strftime('%Y-%m-%d') if sub.expiry_date else 'غير محدد',
        'net_to_network': offer.name if offer else 'بدون عرض'
    })

# ==============================================================================
# 2. مسار الـ API الموحد (Unified API Auth) - لخدمات الخلفية وتوليد البصمة
# ==============================================================================

@app_bp.route('/api/app/auth', methods=['POST'])
def api_app_auth():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "JSON body is required"}), 400
        
    username = data.get('username')
    password = data.get('password') 
    
    if not username or not password:
        return jsonify({"status": "error", "message": "يجب إدخال بيانات الدخول كاملة"}), 400

    # فحص الإدارة المركزية أولاً
    admin = db_session.query(SystemAdmin).filter_by(username=username).first()
    if admin and check_password_hash(admin.password_hash, password): 
        if not admin.api_token:
            admin.api_token = secrets.token_hex(32)
            db_session.commit()
            
        return jsonify({
            "status": "success",
            "token": admin.api_token,
            "role": "super_admin",
            "permissions": {"all_access": True},
            "user_id": admin.id
        }), 200

    # فحص Mوزعين وأصحاب الشبكات
    user = db_session.query(User).filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        permissions = user.permissions or {}
        if not permissions.get('perm_app_access', True):
            return jsonify({"status": "error", "message": "غير مصرح لك باستخدام التطبيق"}), 403

        if not user.api_token:
            user.api_token = secrets.token_hex(32)
            db_session.commit()
            
        return jsonify({
            "status": "success",
            "token": user.api_token,
            "role": user.role, 
            "permissions": permissions,
            "user_id": user.id
        }), 200

    return jsonify({"status": "error", "message": "بيانات الدخول غير صحيحة"}), 401

# ==============================================================================
# 3. عقل الـ Webhook (محرك تحليل الرسائل والمطابقة المالية الآلية)
# ==============================================================================

def extract_transaction_data(sms_text, sender_id=""):
    """
    محلل Regex ذكي ومحدث مخصص للتعرف على كافة شبكات ومحافظ كاش مصر
    (فودافون، إي آند موني، أورانج كاش، وي باي) واستخراج الداتا بدقة وثبات.
    """
    amount = None
    phone = None
    
    # تنظيف وتوحيد اسم المرسل لضمان المطابقة الأمنية
    sender_clean = str(sender_id).lower().strip().replace(" ", "")
    
    # حصر شامل لأسماء النطاقات والـ Sender IDs الخاصة بمحافظ مصر الأربعة
    valid_senders = ['vodafone', 'vf', 'e&', 'etisalat', 'e-cash', 'ecash', 'orange', 'we']
    
    # التحقق من أن الرسالة من مصدر مالي معتمد لمنع الثغرات (في حال عدم الإرسال نتخطى الفحص كبديل)
    is_valid_sender = any(v in sender_clean for v in valid_senders) if sender_clean else True
    if not is_valid_sender:
        return None, None

    # استخراج المبلغ: مرونة كاملة للتعرف على الأرقام الصحيحة والعشرية المتبوعة بـ (ج، جنيه، ج.م، EGP)
    # مع فحص الدلائل السياقية مثل (مبلغ، استلام، إيداع، تحويل، قيمة، إضافة)
    amount_match = re.search(r'(?:مبلغ|استلام|استلمت|إيداع|ايداع|تحويل|قيمة|اضافة|إضافة).*?([0-9]+(?:\.[0-9]+)?)\s*(?:ج|جنيه|جنية|ج\.م|EGP)', sms_text, re.IGNORECASE)
    if amount_match:
        amount = float(amount_match.group(1))

    # استخراج رقم المحفظة: مطابقة أي رقم خلوي مصري سليم من 11 رقم يبدأ بـ (010, 011, 012, 015)
    phone_match = re.search(r'(01[0125][0-9]{8})', sms_text)
    if phone_match:
        phone = phone_match.group(1)

    return amount, phone

@app_bp.route('/api/app/webhook', methods=['POST'])
def process_webhook():
    # 1. التحقق الأمني من الـ Token المرسل من التطبيق
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Missing or invalid token"}), 401
    
    token = auth_header.split(" ")[1]
    
    # تحديد هوية المستقبل (إدارة أو موزع)
    owner_id = None
    entity_type = None
    owner_client = None
    
    admin = db_session.query(SystemAdmin).filter_by(api_token=token).first()
    if admin:
        owner_id = admin.id
        entity_type = 'super_admin'
    else:
        user = db_session.query(User).filter_by(api_token=token).first()
        if user:
            owner_id = user.id
            entity_type = 'reseller'
            # جلب بيانات العميل (NetworkClient) لحساب العمولة
            owner_client = db_session.query(NetworkClient).filter_by(id=user.id).first()
        else:
            return jsonify({"status": "error", "message": "Unauthorized token"}), 401

    # 2. استقبال بيانات الرسالة واسم المرسل
    data = request.get_json()
    sms_text = data.get('sms_text', '')
    sender_id = data.get('sender', '')  # استقبال اسم الشركة (Sender ID) من حقل الإرسال في التطبيق
    
    if not sms_text:
        return jsonify({"status": "ignored", "message": "لا يوجد نص رسالة"}), 400

    # 3. التحليل الذكي للرسالة وتحديد تفاصيل المعاملة
    received_amount, sender_phone = extract_transaction_data(sms_text, sender_id)
    
    if not received_amount or not sender_phone:
        return jsonify({"status": "ignored", "message": "لم يتم التعرف على معاملة مالية معتمدة في الرسالة"}), 200

    # 4. المطابقة المالية الحية مع الفواتير المعلقة
    query = db_session.query(PendingInvoice).filter(
        PendingInvoice.status == 'pending',
        PendingInvoice.sender_phone == sender_phone,
        PendingInvoice.amount == received_amount
    )
    
    if entity_type == 'reseller':
        query = query.filter(PendingInvoice.user_id == owner_id)
        
    pending_invoice = query.first()

    if not pending_invoice:
        return jsonify({"status": "unmatched", "message": "لم يتم العثور على فاتورة مطابقة لهذه العملية"}), 200

    # 5. التنفيذ اللحظي (اعتماد الفاتورة وتوثيق المعاملة)
    try:
        # أ. تحديث حالة الفاتورة
        pending_invoice.status = 'paid'
        pending_invoice.updated_at = datetime.datetime.utcnow()

        # ب. حساب عمولة التطبيق
        app_commission = 0.0
        if owner_client:
            app_commission = calculate_app_commission(received_amount, owner_client)
        
        # ج. تسجيل العملية في الحصالة (Financial Transactions) - العملية الأصلية
        new_transaction = FinancialTransaction(
            user_id=pending_invoice.user_id,
            entity_type='subscriber', # المعاملة تمت من قبل مشترك
            transaction_type='auto_payment',
            amount=received_amount,
            package_name=f"تفعيل آلي للمشترك: {pending_invoice.subscriber_username}",
            payment_status='paid',
            payment_method='webhook_wallet',
            transaction_ref=f"sms_{sender_phone}_{datetime.datetime.utcnow().timestamp()}"
        )
        db_session.add(new_transaction)
        
        # د. تسجيل عمولة التطبيق كعملية منفصلة
        if app_commission > 0 and owner_client:
            # خصم العمولة من رصيد صاحب الشبكة
            owner_client.current_balance = (owner_client.current_balance or 0.0) - app_commission
            owner_client.accumulated_commission = (owner_client.accumulated_commission or 0.0) + app_commission
            
            commission_transaction = FinancialTransaction(
                user_id=owner_id,
                entity_type='network',
                transaction_type='app_commission',
                amount=app_commission,
                package_name=f"عمولة تطبيق صقر كونكت باي - عملية: {pending_invoice.subscriber_username}",
                payment_status='paid',
                payment_method='auto_deduction',
                transaction_ref=f"comm_{sender_phone}_{datetime.datetime.utcnow().timestamp()}"
            )
            db_session.add(commission_transaction)
        
        # ه. حفظ التغييرات
        db_session.commit()

        return jsonify({
            "status": "success", 
            "message": "تمت المطابقة والتفعيل بنجاح",
            "invoice_id": pending_invoice.id,
            "subscriber": pending_invoice.subscriber_username,
            "app_commission": app_commission
        }), 200

    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": f"حدث خطأ أثناء معالجة العملية: {str(e)}"}), 500

# ==============================================================================
# 4. API: بيانات الشبكة للتطبيق (Network Info API)
# ==============================================================================

@app_bp.route('/api/app/network-info/<int:network_id>', methods=['GET'])
def api_network_info(network_id):
    """
    يعيد بيانات الشبكة للتطبيق عند أول تشغيل:
    - اسم الشبكة، رصيد المحفظة، أرقام الدعم الفني (أرقام الوكالة)
    - إعدادات التطبيق (عمولة، قفل، صيانة، إصدار)
    - معلومات العميل (NetworkClient)
    """
    # التحقق من التوكن
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"status": "error", "message": "Missing or invalid token"}), 401
    
    token = auth_header.split(" ")[1]
    
    # التحقق من ملكية التوكن
    admin = db_session.query(SystemAdmin).filter_by(api_token=token).first()
    user = db_session.query(User).filter_by(api_token=token).first()
    
    if not admin and not user:
        return jsonify({"status": "error", "message": "Unauthorized token"}), 401
    
    # جلب بيانات العميل
    client = get_network_client(network_id)
    if not client:
        return jsonify({"status": "error", "message": "الشبكة غير موجودة"}), 404
    
    # التحقق من الصلاحية
    if user and client.id != user.id and (not user.parent_id or client.id != user.parent_id):
        return jsonify({"status": "error", "message": "غير مصرح لك بعرض بيانات هذه الشبكة"}), 403
    
    app_settings = get_app_settings()
    
    # بيانات المحفظة والرصيد
    wallet_balance = getattr(client, 'current_balance', 0.0) or 0.0
    accumulated_commission = getattr(client, 'accumulated_commission', 0.0) or 0.0
    
    # إعدادات العمولة لهذا العميل
    if client.commission_mode == 'custom':
        commission_type = 'percent'
        commission_value = client.custom_commission_rate or 0
    elif client.commission_mode == 'disabled':
        commission_type = 'disabled'
        commission_value = 0
    else:
        commission_type = app_settings.get('app_commission_type', 'percent')
        commission_value = app_settings.get('app_commission_value', 2.5)
    
    return jsonify({
        "status": "success",
        "data": {
            "network": {
                "id": client.id,
                "name": client.client_name,
                "type": client.client_type,
                "ip_domain": client.ip_domain,
                "status": client.status,
            },
            "wallet": {
                "balance": wallet_balance,
                "accumulated_commission": accumulated_commission,
            },
            "app_settings": {
                "version": app_settings.get('app_version'),
                "download_url": app_settings.get('app_download_url'),
                "locked": app_settings.get('app_locked', False),
                "force_update": app_settings.get('app_force_update', False),
                "maintenance_mode": app_settings.get('app_maintenance_mode', False),
                "commission": {
                    "type": commission_type,
                    "value": commission_value,
                    "min": app_settings.get('app_commission_min', 0.50),
                    "max": app_settings.get('app_commission_max', 50.0),
                },
            },
            "support": {
                "phones": app_settings.get('app_support_phones', ['01033379719', '01033379719']),
            },
            "client_settings": client.client_settings,
        }
    }), 200


# ==============================================================================
# 5. Middleware: فحص حالة التطبيق (قفل، صيانة، ظهور)
# ==============================================================================

@app_bp.before_request
def app_security_middleware():
    """يطبق على جميع مسارات التطبيق"""
    # استثناء مسارات المصادقة والصحة
    if request.path in ['/api/app/auth', '/api/app/webhook', '/app/<int:network_id>/login']:
        return
    
    app_settings = get_app_settings()
    
    # وضع الصيانة
    if app_settings.get('app_maintenance_mode'):
        if request.path.startswith('/api/app/'):
            return jsonify({"status": "error", "message": "التطبيق تحت الصيانة، يرجى المحاولة لاحقاً"}), 503
        return "التطبيق تحت الصيانة", 503
    
    # قفل التطبيق بالكامل
    if app_settings.get('app_locked'):
        if request.path.startswith('/api/app/'):
            return jsonify({"status": "error", "message": "التطبيق مقفل من الإدارة المركزية"}), 403
        return "التطبيق مقفل من الإدارة المركزية", 403
    
    # التحقق من ظهور التطبيق للشبكة المحددة
    if request.path.startswith('/api/app/network-info/'):
        # سيتم التحقق داخل الدالة
        pass