# ==============================================================================
# SAKR CONNECT - SUBSCRIBERS & SYSTEMS ROUTING (LIVE/PRODUCTION)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: مسجلة باسم مشروع Sakr Connect
# أرقام الدعم الفني للمطور: 01033379719 - 01033379719
# العنوان: 
# صفحة المطور الشخصية: https://www.facebook.com/ahmedsalemJournalist
# صفحة الوكالة: https://www.facebook.com/sakrmediaagency
# ==============================================================================

import os
import io
import zipfile
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, session, abort, request, jsonify, redirect, url_for, flash, send_file
from core.db_manager import db_session
from database.models import Subscriber, User, ActiveSession, SaasPackage, PendingInvoice, Network, Offer, CardTemplate, Router

subscribers_bp = Blueprint('subscribers', __name__)

# ==========================================
# [دالة مساعدة]: جلب الشبكة والمالك الحقيقي وصلاحيات الموزع (معدلة لمنع الطرد)
# ==========================================
def get_authorized_network_context():
    user_id = session.get('user_id')
    role = session.get('role')
    
    if role in ['admin', 'super_admin']:
        return True, None, None 

    current_user = db_session.query(User).filter_by(id=user_id).first()
    if not current_user:
        return False, None, None

    # إذا كان موزع أو مدير فرعي، نجلب المالك الأصلي (Parent) للشبكة
    if role in ['reseller', 'manager']:
        owner_id = current_user.parent_id
        # التحقق من صلاحيات الموزع لإدارة المشتركين
        permissions = session.get('permissions', {})
        if isinstance(permissions, dict) and not permissions.get('can_manage_subscribers', False):
            return False, None, None
    else:
        owner_id = user_id

    owner_network = db_session.query(Network).filter_by(owner_id=owner_id).first()

    # 🔥 الإنشاء التلقائي للشبكة لمنع الطرد للمشتركين الجدد مع تمرير نوع النظام
    if not owner_network and role in ['network', 'cafe']:
        network_name = getattr(current_user, 'network_name', None)
        if not network_name:
            network_name = f"شبكة {current_user.username}"
            
        new_network = Network(owner_id=owner_id, name=network_name, network_type=role)
        db_session.add(new_network)
        db_session.commit()
        owner_network = new_network

    return True, owner_network, owner_id

# ==========================================
# 1. مسار الـ AJAX المركزي (للأزرار اللحظية - مطور)
# ==========================================
@subscribers_bp.route('/api/client/action', methods=['POST'])
def client_action():
    role = session.get('role')
    if role not in ['admin', 'super_admin', 'network', 'reseller', 'manager']:
        return jsonify({"status": "error", "message": "غير مصرح لك"}), 403

    data = request.get_json()
    client_id_raw = data.get('id')
    action = data.get('action')
    sys_type = data.get('system')
    value = data.get('value')

    if not client_id_raw:
        return jsonify({"status": "error", "message": "معرف العميل مفقود"}), 400

    try:
        # 🔥 التعديل الجذري: البحث الذكي بالـ ID الرقمي أو باسم المستخدم النصي
        client = None
        is_numeric = str(client_id_raw).isdigit()
        
        if sys_type == 'pppoe':
            if is_numeric:
                client = db_session.query(Subscriber).filter_by(id=int(client_id_raw)).first()
            else:
                client = db_session.query(Subscriber).filter_by(username=str(client_id_raw)).first()
        else:
            if is_numeric:
                client = db_session.query(User).filter_by(id=int(client_id_raw)).first()
            else:
                client = db_session.query(User).filter_by(username=str(client_id_raw)).first()

        if not client:
            return jsonify({"status": "error", "message": "الحساب غير موجود"}), 404

        # التحقق من الملكية لغير الإدارة المركزية
        if role not in ['admin', 'super_admin']:
            is_auth, owner_network, owner_id = get_authorized_network_context()
            if not is_auth or not owner_network:
                return jsonify({"status": "error", "message": "غير مصرح لك أو لا توجد شبكة"}), 403

            if sys_type == 'pppoe':
                if client.network_id != owner_network.id:
                    return jsonify({"status": "error", "message": "غير مصرح لك"}), 403
            else:
                if client.parent_id != owner_id:
                    return jsonify({"status": "error", "message": "غير مصرح لك"}), 403

        message = f"تم تنفيذ إجراء ({action}) بنجاح."

        # 1. الإيقاف والتفعيل
        if action == 'suspend':
            if sys_type == 'pppoe':
                client.status = 'suspended' if client.status == 'active' else 'active'
            else:
                client.is_active = not client.is_active
            current_status = client.status if sys_type == 'pppoe' else ('active' if client.is_active else 'suspended')
            db_session.commit()
            return jsonify({"status": "success", "new_state": current_status, "message": message})
            
        # 2. تنظيف الماك أدرس
        elif action == 'clear_mac':
            if sys_type == 'pppoe':
                client.mac_address = None

        # 3. الحذف النهائي
        elif action == 'delete':
            db_session.delete(client)
            message = "تم حذف الحساب نهائياً."

        # 4. تغيير كلمة المرور
        elif action == 'change_password':
            if sys_type == 'pppoe':
                client.password = str(value)
            else:
                from werkzeug.security import generate_password_hash
                client.password_hash = generate_password_hash(str(value))
            message = "تم تحديث كلمة المرور بنجاح."

        # 5. إضافة رصيد للموزعين
        elif action == 'add_balance' and sys_type != 'pppoe':
            amount = float(value)
            client.current_balance = getattr(client, 'current_balance', 0) + amount
            message = f"تم إضافة {amount} ج.م للرصيد بنجاح."

        # 6. تصفير الديون
        elif action == 'pay_debt' and sys_type != 'pppoe':
            client.debt = 0
            message = "تم تصفير المديونيات وتسديدها دفترياً بنجاح."
            
        # الفصل من السيرفر سيتم برمجته لاحقاً مع الـ API
        elif action == 'disconnect':
            pass 

        db_session.commit()
        return jsonify({"status": "success", "message": message})

    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# 2. مسار الدخول كعميل (Impersonation) - للسوبر أدمن فقط
# ==========================================
@subscribers_bp.route('/impersonate/<string:sys_type>/<int:client_id>')
def impersonate(sys_type, client_id):
    if session.get('role') not in ['admin', 'super_admin']:
        abort(403)

    session['original_admin_id'] = session['user_id']

    if sys_type == 'pppoe':
        abort(403) 

    elif sys_type in ['cafe', 'network', 'reseller']:
        user = db_session.query(User).filter_by(id=client_id).first()
        if user:
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.username
            session['system_type'] = user.role
            return redirect(url_for('auth.dashboard'))

    abort(404)

# ==========================================
# 3. البروفايل الموحد الديناميكي (إدارة وصلاحيات)
# ==========================================
@subscribers_bp.route('/client/profile/<string:sys_type>/<int:client_id>')
def client_profile(sys_type, client_id):
    role = session.get('role')
    is_auth, owner_network, owner_id = get_authorized_network_context()

    if not is_auth and role not in ['admin', 'super_admin']:
        abort(403)

    client_data = None

    if sys_type in ['pppoe', 'sub']:
        sub = db_session.query(Subscriber).filter_by(id=client_id).first()
        if sub:
            # عزل الرؤية
            if role not in ['admin', 'super_admin'] and sub.network_id != owner_network.id:
                abort(403)

            sector_name = "هوت سبوت" if sub.sub_type == 'hotspot' else "برودباند (PPPoE)"
            client_data = {
                "id": sub.id, 
                "name": getattr(sub, 'full_name', sub.username), 
                "username": sub.username,
                "sector": sector_name, 
                "type": sys_type, 
                "speed": sub.offer.name if sub.offer else "غير محدد",
                "balance": f"{sub.balance} EGP", 
                "days_left": "24 يوم", 
                "label_1": "الاستهلاك", "val_1": f"{sub.quota_used} GB",
                "label_2": "الإجمالي", "val_2": f"{sub.quota_total} GB",
                "progress": (sub.quota_used / sub.quota_total * 100) if getattr(sub, 'quota_total', 0) > 0 else 0,
                "ip": "N/A", 
                "mac": sub.mac_address or "غير مرتبط",
                "status": sub.status
            }
    else:
        user = db_session.query(User).filter_by(id=client_id).first()
        if user:
            if role not in ['admin', 'super_admin'] and user.parent_id != owner_id and user.id != owner_id:
                abort(403)

            sector_name = "قطاع الكافيهات" if user.role == 'cafe' else "الشبكات الفرعية"
            client_data = {
                "id": user.id, "name": getattr(user, 'fullname', user.username), "username": user.username,
                "sector": sector_name, "type": user.role, "speed": "حسب الشبكة",
                "balance": f"{getattr(user, 'current_balance', 0)} EGP", "days_left": f"المديونية: {getattr(user, 'debt', 0)}",
                "label_1": "أقصى مشتركين", "val_1": str(getattr(user, 'max_subscribers', 0)),
                "label_2": "أقصى روترات", "val_2": str(getattr(user, 'max_routers', 0)),
                "progress": 50, "ip": "N/A", "mac": "N/A", "status": "active" if user.is_active else "suspended"
            }

    if not client_data:
        abort(404)

    qr_token = f"http://10.0.0.3/bind?token={client_data['username']}" if sys_type in ['pppoe', 'sub'] else None
    return render_template('client_profile.html', client=client_data, qr_token=qr_token, project_name="Sakr Connect")


# ==========================================
# 4. واجهة الإدارة لقطاع الكافيهات (Hotspot / caf)
# ==========================================
@subscribers_bp.route('/manage/hotspot')
def manage_hotspot():
    current_filter = request.args.get('filter', 'all')
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role in ['admin', 'super_admin']:
        base_query = db_session.query(User).filter_by(role='cafe')
        networks = db_session.query(Network).all()
    else:
        is_auth, owner_network, owner_id = get_authorized_network_context()
        if not is_auth:
            abort(403)
        base_query = db_session.query(User).filter_by(role='cafe', parent_id=owner_id)
        networks = [owner_network] if owner_network else []

    all_cafes = base_query.all()
    
    # --- 1. حساب العدادات اللي الواجهة (HTML) مستنياها ---
    active_cafes_count = sum(1 for c in all_cafes if c.is_active)
    inactive_cafes_count = sum(1 for c in all_cafes if not c.is_active)
    
    # نعتبر إن المديونية اللي تجاوزت 1000 جنيه هي ديون خطرة (زي ما برمجناها في الواجهة)
    high_debt_count = sum(1 for c in all_cafes if hasattr(c, 'debt') and c.debt and c.debt > 1000)
    
    # حساب الإجمالي (دمجنا المسحوبات كإيراد كلي عشان يسمع في الواجهة)
    total_revenue = sum(c.profit_value for c in all_cafes if hasattr(c, 'profit_value') and c.profit_value)
    
    # --- 2. الفلترة بناءً على الزراير الجديدة في الواجهة ---
    if current_filter == 'active':
        cafes_to_show = [c for c in all_cafes if c.is_active]
    elif current_filter == 'high_debt':
        cafes_to_show = [c for c in all_cafes if hasattr(c, 'debt') and c.debt and c.debt > 1000]
    elif current_filter == 'inactive':
        cafes_to_show = [c for c in all_cafes if not c.is_active]
    else:
        cafes_to_show = all_cafes

    # 🔥 التعديل الجذري: ربط اسم الباقة وكود التحصيل ديناميكياً بكل كافيه للعرض في الواجهة
    for c in cafes_to_show:
        pkg = db_session.query(SaasPackage).filter_by(id=getattr(c, 'package_id', None)).first() if getattr(c, 'package_id', None) else None
        c.dynamic_package_name = pkg.name if pkg else "باقة مخصصة"
        c.display_billing_code = getattr(c, 'billing_code', 'غير متوفر')

    cafe_packages = db_session.query(SaasPackage).filter_by(system_type='cafe').order_by(SaasPackage.price.asc()).all()

    return render_template('manage_hotspot.html', 
                           cafes=cafes_to_show, 
                           current_filter=current_filter,
                           active_cafes_count=active_cafes_count,
                           inactive_cafes_count=inactive_cafes_count,
                           high_debt_count=high_debt_count,
                           total_revenue=total_revenue,
                           packages=cafe_packages,
                           networks=networks)

# ==========================================
# 5. مسار رفع ملفات النظام المركزية (SaaS Admin)
# ==========================================
@subscribers_bp.route('/system/files/upload', methods=['POST'])
def upload_system_files():
    if session.get('role') not in ['admin', 'super_admin']:
        abort(403)
        
    try:
        sys_type = request.form.get('system_type', 'cafe')
        base_upload_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'uploads')
        
        hotspot_file = request.files.get('hotspot_file')
        if hotspot_file and hotspot_file.filename:
            hs_dir = os.path.join(base_upload_path, 'hotspots')
            os.makedirs(hs_dir, exist_ok=True)
            hotspot_file.save(os.path.join(hs_dir, f"central_{sys_type}_hotspot.zip"))

        app_file = request.files.get('app_file')
        if app_file and app_file.filename:
            app_dir = os.path.join(base_upload_path, 'apps')
            os.makedirs(app_dir, exist_ok=True)
            app_file.save(os.path.join(app_dir, f"central_{sys_type}_app.apk"))

        flash('تم رفع وتحديث ملفات النظام المركزية بنجاح!', 'success')
    except Exception as e:
        flash(f'حدث خطأ أثناء رفع الملفات: {str(e)}', 'error')
        
    return redirect(request.referrer)

# ==========================================
# 6. مسار إضافة/تعديل الباقات (SaaS Admin) - لعملاء الشبكات والكافيهات فقط
# ==========================================
@subscribers_bp.route('/packages/save', methods=['POST'])
def save_package():
    if session.get('role') not in ['admin', 'super_admin']:
        abort(403)
        
    try:
        pkg_id = request.form.get('package_id')
        sys_type = request.form.get('system_type')
        name = request.form.get('name')
        country = request.form.get('country', 'EG')
        currency = request.form.get('currency', 'EGP' if country == 'EG' else 'USD')
        
        def safe_int(val, default=0):
            try: return int(float(val))
            except: return default

        price = float(request.form.get('price', 0))
        max_subscribers = safe_int(request.form.get('max_subscribers'))
        max_offers = safe_int(request.form.get('max_offers'))
        max_vouchers = safe_int(request.form.get('max_vouchers'))
        max_designs = safe_int(request.form.get('max_designs'))
        max_servers = safe_int(request.form.get('max_servers'))
        max_resellers = safe_int(request.form.get('max_resellers'))
        duration = safe_int(request.form.get('duration_months', 1))
        is_active = True if request.form.get('is_active') else False
        app_access = True if request.form.get('app_access') else False
        hotspot_access = 'active' if request.form.get('hotspot_access') else ''
        notes = request.form.get('notes', '')

        if pkg_id:
            package = db_session.query(SaasPackage).filter_by(id=pkg_id).first()
            if package:
                package.name = name
                package.price = price
                package.max_subscribers = max_subscribers
                package.max_offers = max_offers
                package.max_vouchers = max_vouchers
                package.max_designs = max_designs
                package.max_servers = max_servers
                package.max_resellers = max_resellers
                package.duration_months = duration
                package.is_active = is_active
                package.country = country
                package.currency = currency
                
                if hasattr(package, 'app_access'): package.app_access = app_access
                if hasattr(package, 'hotspot_file'): package.hotspot_file = hotspot_access
                if hasattr(package, 'notes'): package.notes = notes
                    
            flash('تم تحديث بيانات الباقة بنجاح!', 'success')
        else:
            kwargs = {
                'system_type': sys_type,
                'name': name,
                'price': price,
                'max_subscribers': max_subscribers,
                'max_offers': max_offers,
                'max_vouchers': max_vouchers,
                'max_designs': max_designs,
                'max_servers': max_servers,
                'max_resellers': max_resellers,
                'duration_months': duration,
                'is_active': is_active,
                'country': country,
                'currency': currency
            }
            if hasattr(SaasPackage, 'app_access'): kwargs['app_access'] = app_access
            if hasattr(SaasPackage, 'hotspot_file'): kwargs['hotspot_file'] = hotspot_access
            if hasattr(SaasPackage, 'notes'): kwargs['notes'] = notes

            new_package = SaasPackage(**kwargs)
            db_session.add(new_package)
            flash('تمت إضافة الباقة بنجاح!', 'success')
            
        db_session.commit()
        
    except Exception as e:
        db_session.rollback()
        flash(f'حدث خطأ أثناء الحفظ: {str(e)}', 'error')
        
    if sys_type.startswith('network'):
        return redirect(url_for('subscribers.manage_networks'))
    else:
        return redirect(url_for('subscribers.manage_hotspot'))

# ==========================================
# 7. مسار حذف الباقة (SaaS Admin)
# ==========================================
@subscribers_bp.route('/manage/package/delete/<int:pkg_id>')
def delete_package(pkg_id):
    if session.get('role') not in ['admin', 'super_admin']:
        abort(403)
        
    try:
        package = db_session.query(SaasPackage).filter_by(id=pkg_id).first()
        if package:
            db_session.delete(package)
            db_session.commit()
            flash('تم حذف الباقة بنجاح.', 'success')
    except Exception as e:
        db_session.rollback()
        flash('حدث خطأ أثناء محاولة الحذف.', 'error')
        
    return redirect(request.referrer)

# ==========================================
# 8. واجهة إدارة الشبكات المركزية (net) (SaaS Admin)
# ==========================================
@subscribers_bp.route('/manage/network')
def manage_networks():
    if session.get('role') not in ['admin', 'super_admin']:
        abort(403)
        
    current_filter = request.args.get('filter', 'all')
    
    # 1. سحب كافة الكيانات المسجلة كأصحاب شبكات (Nodes)
    all_clients = db_session.query(User).filter_by(role='network').all()
    
    # 2. حساب العدادات ديناميكياً بالقرش من قاعدة البيانات لتغذية بطاقات العرض الكبرى
    total_clients = len(all_clients)
    active_clients = sum(1 for c in all_clients if getattr(c, 'is_active', False))
    suspended_clients = sum(1 for c in all_clients if not getattr(c, 'is_active', False))
    
    total_balances = sum(c.current_balance for c in all_clients if hasattr(c, 'current_balance') and c.current_balance)
    total_debts = sum(c.debt for c in all_clients if hasattr(c, 'debt') and c.debt)
    
    # 3. تصفية وفلترة العملاء المعروضين في الجدول بناءً على الفلتر المختار فوق
    if current_filter == 'active':
        clients_to_show = [c for c in all_clients if getattr(c, 'is_active', False)]
    elif current_filter == 'suspended':
        clients_to_show = [c for c in all_clients if not getattr(c, 'is_active', False)]
    else:
        clients_to_show = all_clients
        
    # 🔥 التعديل الجذري: ربط اسم الباقة وكود التحصيل ديناميكياً بكل صاحب شبكة للعرض في الواجهة
    for c in clients_to_show:
        pkg = db_session.query(SaasPackage).filter_by(id=getattr(c, 'package_id', None)).first() if getattr(c, 'package_id', None) else None
        c.dynamic_package_name = pkg.name if pkg else "باقة مخصصة"
        c.display_billing_code = getattr(c, 'billing_code', 'غير متوفر')

    # سحب الباقات والشبكات المرتبطة
    network_packages = db_session.query(SaasPackage).filter_by(system_type='network').order_by(SaasPackage.price.asc()).all()
    networks = db_session.query(Network).all()
    
    # 4. تمرير الداتا كاملة لضمان عمل الواجهة السيادية بكفاءة 100% دون أي أصفار وهمية
    return render_template('manage_networks.html', 
                           clients=clients_to_show, 
                           packages=network_packages, 
                           networks=networks,
                           total_clients=total_clients,
                           active_clients=active_clients,
                           suspended_clients=suspended_clients,
                           total_balances=total_balances,
                           total_debts=total_debts,
                           current_filter=current_filter)

# ==========================================
# 9. مسار إنشاء الفاتورة المعلقة ديناميكياً (دفع Webhook/SaaS)
# ==========================================
@subscribers_bp.route('/client/checkout', methods=['POST'])
def client_checkout():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "بيانات الدفع مفقودة"}), 400
        
    username = data.get('username')
    sender_phone = data.get('sender_phone')
    offer_id = data.get('offer_id')
    card_template_id = data.get('card_template_id')
    
    if not username or not sender_phone:
        return jsonify({"status": "error", "message": "اسم المستخدم ورقم المحفظة مطلوبان"}), 400
        
    if not offer_id and not card_template_id:
        return jsonify({"status": "error", "message": "يجب تحديد باقة أو كارت للتفعيل"}), 400

    subscriber = db_session.query(Subscriber).filter_by(username=username).first()
    if not subscriber:
        return jsonify({"status": "error", "message": "المشترك غير موجود"}), 404
        
    network = db_session.query(Network).filter_by(id=subscriber.network_id).first()
    if not network:
        return jsonify({"status": "error", "message": "بيانات الشبكة غير مكتملة"}), 404
        
    owner_id = network.owner_id
    amount = 0.0
    is_instant = False
    
    # تفعيل كود التحصيل بناءً على نوع العملية لمنع خطأ قاعدة البيانات وربطه بالـ Webhook
    if offer_id:
        offer = db_session.query(Offer).filter_by(id=offer_id).first()
        if not offer:
            return jsonify({"status": "error", "message": "الباقة المطلوبة غير متاحة"}), 404
        amount = offer.price
        payer_billing_code = subscriber.billing_code  # ربط كود المشترك المعتمد الذي يبدأ بـ -SUB
    elif card_template_id:
        card = db_session.query(CardTemplate).filter_by(id=card_template_id).first()
        if not card:
            return jsonify({"status": "error", "message": "الكارت المطلوب غير متاح"}), 404
        amount = card.price
        is_instant = True
        import random
        payer_billing_code = f"VOU-{random.randint(100000, 999999)}"  # توليد كود كارت فوري يبدأ بـ -VOU ليطابقه الـ Webhook تلقائياً
        
    if amount <= 0:
        return jsonify({"status": "error", "message": "خطأ في تسعير الباقة"}), 400
        
    try:
        new_invoice = PendingInvoice(
            user_id=owner_id,
            payer_billing_code=payer_billing_code,  # حل مشكلة الـ IntegrityError وإلزامية الحقل
            subscriber_username=subscriber.username,
            amount=amount,
            sender_phone=sender_phone,
            status='pending',
            offer_id=offer_id if offer_id else None,
            card_template_id=card_template_id if card_template_id else None,
            is_instant=is_instant
        )
        db_session.add(new_invoice)
        db_session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"تم تسجيل الطلب بنجاح. كود التحصيل المركزي الخاص بك: {payer_billing_code}. يرجى تحويل مبلغ {amount} ج.م للرقم المحدد للتفعيل التلقائي.",
            "invoice_id": new_invoice.id,
            "amount": amount
        }), 200
        
    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    
# ==============================================================================
# إدارة المشتركين الفرعيين (Sub-Clients) لأصحاب الشبكات والموزعين المعتمدين
# ==============================================================================

# ==========================================
# 10. إدارة المشتركين الفرعيين (عرض وإضافة)
# ==========================================
@subscribers_bp.route('/manage/users', methods=['GET', 'POST'])
def manage_users():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
        
    role = session.get('role')
    
    # فحص الصلاحية وجلب الشبكة والمالك الأصلي
    is_auth, owner_network, owner_id = get_authorized_network_context()
    
    if not is_auth and role not in ['admin', 'super_admin']:
        abort(403)

    if not owner_network and role not in ['admin', 'super_admin']:
        flash('يجب إعداد بيانات الشبكة أولاً من حساب المالك.', 'error')
        return redirect(url_for('auth.dashboard')) 

    # ------------------ معالجة طلب الإضافة (POST) ------------------
    if request.method == 'POST':
        # معالجة القيم الفارغة للشبكة
        target_network_id_raw = request.form.get('target_network_id')
        target_network_id = target_network_id_raw if target_network_id_raw and str(target_network_id_raw).strip() != "" else (owner_network.id if owner_network else None)
        
        if not target_network_id:
            flash('تعذر تحديد الشبكة المراد الإضافة إليها.', 'error')
            return redirect(url_for('subscribers.manage_users'))

        owner_user = db_session.query(User).filter_by(id=owner_id).first() if owner_id else None
        
        if owner_user:
            current_subs_count = db_session.query(Subscriber).filter_by(network_id=target_network_id).count()
            max_allowed = getattr(owner_user, 'max_subscribers', 0)
            
            if current_subs_count >= max_allowed and max_allowed > 0:
                flash('لقد وصلت الشبكة للحد الأقصى للمشتركين المسموح به. يرجى ترقية الباقة.', 'error')
                return redirect(url_for('subscribers.manage_users'))

        try:
            # معالجة القيم الفارغة للروتر والباقة
            r_id_raw = request.form.get('router_id')
            router_id = r_id_raw if r_id_raw and str(r_id_raw).strip() != "" else None
            
            o_id_raw = request.form.get('offer_id')
            offer_id = o_id_raw if o_id_raw and str(o_id_raw).strip() != "" else None

            full_name = request.form.get('full_name')
            username = request.form.get('username')
            password = request.form.get('password')
            amount_paid = float(request.form.get('amount_paid', 0))
            
            existing_sub = db_session.query(Subscriber).filter_by(username=username).first()
            if existing_sub:
                flash('اسم المستخدم مسجل مسبقاً، يرجى اختيار اسم آخر.', 'error')
                return redirect(url_for('subscribers.manage_users'))

            offer = db_session.query(Offer).filter_by(id=offer_id).first() if offer_id else None
            offer_price = offer.price if offer else 0

            # 🔥 [التعديل الجذري الأمني]: حساب تاريخ الانتهاء الإجباري (expiry_date)
            current_time = datetime.now()
            if offer:
                duration = getattr(offer, 'duration', 1)
                duration_type = getattr(offer, 'duration_type', 'month')
                
                if duration_type == 'month':
                    expiry_date = current_time + timedelta(days=30 * duration)
                elif duration_type == 'day':
                    expiry_date = current_time + timedelta(days=duration)
                elif duration_type == 'year':
                    expiry_date = current_time + timedelta(days=365 * duration)
                else:
                    expiry_date = current_time + timedelta(days=30)
            else:
                expiry_date = current_time + timedelta(days=30)  # قيمة افتراضية في حالة عدم وجود عرض
            
            debt = 0
            if amount_paid < offer_price:
                debt = offer_price - amount_paid

            # معالجة القيمة الفارغة لنوع المشترك (تم التعديل ليكون افتراضي للشبكات)
            sub_type_raw = request.form.get('sub_type')
            sub_type = sub_type_raw if sub_type_raw and str(sub_type_raw).strip() != "" else 'broadband'

            new_sub = Subscriber(
                full_name=full_name,
                username=username,
                password=password,
                phone=request.form.get('phone'),
                national_id=request.form.get('national_id'),
                email=request.form.get('email'),
                address=request.form.get('address'),
                sub_type=sub_type,
                network_id=target_network_id,
                router_id=router_id,
                offer_id=offer_id,
                balance=debt,
                status='active',
                expiry_date=expiry_date  # تمرير الحقل الإجباري لمنع الرفض
            )
            
            db_session.add(new_sub)
            db_session.flush()
            new_sub.billing_code = f"sub-{new_sub.id}"
            db_session.commit()
            
            flash('تمت إضافة المشترك بنجاح.', 'success')
            
        except Exception as e:
            db_session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'error')

        return redirect(url_for('subscribers.manage_users'))

    # ------------------ معالجة طلب العرض (GET) ------------------
    search_term = request.args.get('search', '')
    server_filter = request.args.get('server', '')

    if role in ['admin', 'super_admin']:
        query = db_session.query(Subscriber)
        routers = db_session.query(Router).all()
        offers = db_session.query(Offer).all()
    else:
        query = db_session.query(Subscriber).filter_by(network_id=owner_network.id)
        routers = db_session.query(Router).join(Network).filter(Network.owner_id == owner_id).all()
        offers = db_session.query(Offer).filter_by(user_id=owner_id).all()
    
    if search_term:
        query = query.filter(
            (Subscriber.full_name.ilike(f'%{search_term}%')) | 
            (Subscriber.username.ilike(f'%{search_term}%'))
        )
    if server_filter:
        query = query.filter_by(router_id=server_filter)

    users = query.all()

    stats_data = {
        'total_users': len(users),
        'renewed_users': sum(1 for u in users if u.status == 'active'),
        'suspended_users': sum(1 for u in users if u.status == 'suspended'),
        'total_debt': sum(u.balance for u in users if u.balance and u.balance > 0)
    }

    return render_template('users.html', 
                           users=users, 
                           routers=routers, 
                           offers=offers,
                           search_term=search_term,
                           stats_data=stats_data,
                           is_admin=(role in ['admin', 'super_admin']))

# ==========================================
# 11. تعديل المشترك الفرعي 
# ==========================================
@subscribers_bp.route('/subscribers/edit', methods=['POST'])
def edit_user_post():
    if 'user_id' not in session: 
        abort(403)
        
    try:
        sub_id = request.form.get('user_id')
        sub = db_session.query(Subscriber).filter_by(id=sub_id).first()
        
        role = session.get('role')
        is_auth, owner_network, owner_id = get_authorized_network_context()

        if not sub:
            flash('المشترك غير موجود.', 'error')
            return redirect(url_for('subscribers.manage_users'))
            
        if role not in ['admin', 'super_admin']:
            if not is_auth or sub.network_id != owner_network.id:
                flash('غير مصرح لك بتعديل هذا المشترك.', 'error')
                return redirect(url_for('subscribers.manage_users'))

        sub.full_name = request.form.get('full_name')
        sub.username = request.form.get('username')
        
        password = request.form.get('password')
        if password: 
            sub.password = password
            
        # معالجة القيم الفارغة للروتر والباقة في التعديل
        r_id = request.form.get('router_id')
        sub.router_id = r_id if r_id and str(r_id).strip() != "" else None
        
        o_id = request.form.get('offer_id')
        sub.offer_id = o_id if o_id and str(o_id).strip() != "" else None
        
        db_session.commit()
        flash('تم التعديل بنجاح.', 'success')

    except Exception as e:
        db_session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'error')

    return redirect(request.referrer or url_for('subscribers.manage_users'))

# ==========================================
# 12. تسديد مديونية المشترك الفرعي (دفترياً فقط) + Override للإدارة المركزية
# ==========================================
@subscribers_bp.route('/subscribers/pay_debt', methods=['POST'])
def add_balance_post():
    if 'user_id' not in session: 
        abort(403)
        
    sub_id = request.form.get('user_id')
    amount = float(request.form.get('amount', 0))
    role = session.get('role')
    
    try:
        sub = db_session.query(Subscriber).filter_by(id=sub_id).first()
        is_auth, owner_network, owner_id = get_authorized_network_context()
        
        if not sub:
            flash('المشترك غير موجود.', 'error')
            return redirect(request.referrer or url_for('subscribers.manage_users'))

        is_authorized = False
        if role in ['admin', 'super_admin']:
            is_authorized = True 
        elif is_auth and owner_network and sub.network_id == owner_network.id:
            is_authorized = True

        if is_authorized and amount > 0:
            sub.balance = max((sub.balance or 0) - amount, 0)
            db_session.commit()
            flash(f'تم تسديد {amount} ج.م بنجاح من حساب المشترك.', 'success')
        else:
            flash('غير مصرح لك أو بيانات غير صحيحة.', 'error')
            
    except Exception as e:
        db_session.rollback()
        flash('حدث خطأ أثناء التسديد.', 'error')
        
    return redirect(request.referrer or url_for('subscribers.manage_users'))

# ==========================================
# 13. تجديد باقة المشترك الفرعي يدوياً (Override)
# ==========================================
@subscribers_bp.route('/subscribers/renew/<int:sub_id>', methods=['GET', 'POST'])
def renew_user(sub_id):
    if 'user_id' not in session: 
        abort(403)
        
    role = session.get('role')
    
    try:
        sub = db_session.query(Subscriber).filter_by(id=sub_id).first()
        is_auth, owner_network, owner_id = get_authorized_network_context()
        
        if not sub:
            flash('المشترك غير موجود.', 'error')
            return redirect(request.referrer or url_for('subscribers.manage_users'))

        is_authorized = False
        if role in ['admin', 'super_admin']:
            is_authorized = True
        elif is_auth and owner_network and sub.network_id == owner_network.id:
            is_authorized = True

        if is_authorized:
            sub.status = 'active'
            sub.quota_used = 0
            
            if sub.offer:
                sub.balance = (sub.balance or 0) + sub.offer.price
                # 🚀 تحديث تاريخ الانتهاء عند التجديد اليدوي
                current_time = datetime.now()
                duration = getattr(sub.offer, 'duration', 1)
                duration_type = getattr(sub.offer, 'duration_type', 'month')
                if duration_type == 'month':
                    sub.expiry_date = current_time + timedelta(days=30 * duration)
                elif duration_type == 'day':
                    sub.expiry_date = current_time + timedelta(days=duration)
                elif duration_type == 'year':
                    sub.expiry_date = current_time + timedelta(days=365 * duration)
                
            db_session.commit()
            flash('تم التجديد اليدوي بنجاح.', 'success')
        else:
            flash('غير مصرح لك بإجراء هذا التجديد.', 'error')
            
    except Exception as e:
        db_session.rollback()
        flash('حدث خطأ أثناء التجديد.', 'error')
        
    return redirect(request.referrer or url_for('subscribers.manage_users'))

# ==========================================
# 14. الحذف النهائي للمشترك الفرعي
# ==========================================
@subscribers_bp.route('/subscribers/delete/<int:sub_id>', methods=['GET', 'POST'])
def delete_user(sub_id):
    if 'user_id' not in session: 
        abort(403)
        
    role = session.get('role')
    
    try:
        sub = db_session.query(Subscriber).filter_by(id=sub_id).first()
        is_auth, owner_network, owner_id = get_authorized_network_context()
        
        if not sub:
            flash('المشترك غير موجود.', 'error')
            return redirect(request.referrer or url_for('subscribers.manage_users'))

        is_authorized = False
        if role in ['admin', 'super_admin']:
            is_authorized = True
        elif is_auth and owner_network and sub.network_id == owner_network.id:
            is_authorized = True

        if is_authorized:
            db_session.delete(sub)
            db_session.commit()
            flash('تم الحذف نهائياً.', 'success')
        else:
            flash('غير مصرح لك.', 'error')
            
    except Exception as e:
        db_session.rollback()
        flash('حدث خطأ أثناء الحذف.', 'error')
        
    return redirect(request.referrer or url_for('subscribers.manage_users'))

# ==========================================
# 15. تحميل قالب الهوت سبوت المخصص للعميل (Dynamic ZIP Injection)
# ==========================================
@subscribers_bp.route('/client/download_hotspot', methods=['GET'])
def download_hotspot():
    user_id = session.get('user_id')
    if not user_id:
        flash('يجب تسجيل الدخول أولاً.', 'error')
        return redirect(url_for('auth.login'))

    try:
        # 1. جلب بيانات العميل الحالية
        current_user = db_session.query(User).filter_by(id=user_id).first()
        network_name = session.get('network_name', getattr(current_user, 'network_name', f'Network_{current_user.username}'))
        support_phone = getattr(current_user, 'phone1', '') or 'رقم الدعم غير مسجل'
        sys_type = session.get('system_type', 'cafe')

        # 2. تحديد مسار الملف المركزي المرفوع من الإدارة
        base_upload_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'uploads', 'hotspots')
        central_zip_path = os.path.join(base_upload_path, f"central_{sys_type}_hotspot.zip")

        if not os.path.exists(central_zip_path):
            flash('عذراً، الإدارة لم تقم برفع قالب الهوت سبوت المركزي حتى الآن.', 'warning')
            return redirect(request.referrer or url_for('auth.dashboard'))

        # 3. معالجة وحقن الملف في الذاكرة (RAM) بدون فك ضغط على الهارد
        memory_file = io.BytesIO()

        with zipfile.ZipFile(central_zip_path, 'r') as base_zip:
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as new_zip:
                for item in base_zip.infolist():
                    file_data = base_zip.read(item.filename)

                    # فحص امتداد الملف لتحديد ما إذا كان قابلاً للتعديل النصي
                    if item.filename.lower().endswith(('.html', '.htm', '.js', '.txt', '.css')):
                        try:
                            # تحويل البيانات لنص، استبدال المتغيرات، ثم إرجاعها لبايتات
                            content = file_data.decode('utf-8')
                            content = content.replace('__NETWORK_NAME__', str(network_name))
                            content = content.replace('__SUPPORT_PHONE__', str(support_phone))
                            # حقن بيانات السلايدر والباقات من قاعدة البيانات المحلية
                            try:
                                from sqlalchemy import text
                                # جلب بيانات السلايدر (4 شرائح مرتبة)
                                slider_result = db_session.execute(text("SELECT platform, title, image_url, link_url FROM slider_cache ORDER BY id ASC LIMIT 4"))
                                slider_data = []
                                for r in slider_result.fetchall():
                                    slider_data.append({"platform": r[0], "title": r[1], "image_url": r[2], "link_url": r[3]})
                                import json
                                slider_json = json.dumps(slider_data, ensure_ascii=False)
                                content = content.replace('"__SLIDER_JSON__"', slider_json)
                                content = content.replace('__SLIDER_JSON__', slider_json)
                                # حقن بيانات الشبكة الإضافية
                                content = content.replace('__NETWORK_TAGLINE__', str(getattr(current_user, 'network_tagline', '') or ''))
                                content = content.replace('__NETWORK_INITIAL__', str(network_name[0] if network_name else 'S'))
                                content = content.replace('__LOGO_URL__', str(getattr(current_user, 'logo_url', '') or ''))
                            except:
                                pass
                            file_data = content.encode('utf-8')
                        except UnicodeDecodeError:
                            # في حالة وجود ملف غير متوافق الترميز، يتم تجاوزه كملف ثنائي
                            pass

                    new_zip.writestr(item, file_data)

        memory_file.seek(0)
        
        # 4. إرسال الملف النهائي للعميل باسم شبكته
        safe_filename = f"Hotspot_{network_name.replace(' ', '_')}.zip"
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=safe_filename
        )

    except Exception as e:
        flash(f'حدث خطأ أثناء تجهيز الملف: {str(e)}', 'error')
        return redirect(request.referrer or url_for('auth.dashboard'))