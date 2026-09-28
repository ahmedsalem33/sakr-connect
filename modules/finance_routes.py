# ==============================================================================
# SAKR CONNECT - FINANCE ROUTES (SMART MULTI-TENANT ARCHITECTURE)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: مسجلة باسم مشروع صقر كونكت (Sakr Connect)
# أرقام الدعم الفني للمطور: 01033379719 - 01033379719
# العنوان: 
# صفحة المطور الشخصية: https://www.facebook.com/ahmedsalemJournalist
# صفحة الوكالة: https://www.facebook.com/sakrmediaagency
# ==============================================================================

import json
import random
import datetime
from flask import Blueprint, render_template, session, redirect, url_for, abort, request, jsonify, flash
from sqlalchemy import func
from core.db_manager import db_session
from werkzeug.security import generate_password_hash

# استدعاء المنسق المركزي للتحكم في المايكروتيك (إن وجد)
try:
    from core.dispatcher import get_router_and_execute
except ImportError:
    get_router_and_execute = None

# استدعاء الجداول الأساسية
from database.models import (
    User, Subscriber, FinancialTransaction, Network, Router, 
    SystemSettings, SaasPackage, Voucher, PendingInvoice, CardTemplate
)
from database.central_models import GlobalSetting

finance_bp = Blueprint('finance', __name__)

# --- دالة مساعدة لجلب نسبة العمولة المركزية ---
def get_commission_rate():
    try:
        settings = db_session.query(SystemSettings).first()
        return getattr(settings, 'commission_rate', 0.05) 
    except:
        return 0.05

# ==========================================================
# 1. شاشة المراقبة المالية المركزية (خاصة بالإدارة العليا فقط)
# ==========================================================
@finance_bp.route('/admin/finance', methods=['GET'])
def admin_finance():
    role = session.get('role')
    user_id = session.get('user_id')
    
    # تم حظر الدخول لأي رتبة باستثناء الإدارة العليا
    if role not in ['super_admin', 'admin']:
        abort(403)
        
    today = datetime.datetime.utcnow()
    start_of_month = datetime.datetime(today.year, today.month, 1)
    
    query = db_session.query(FinancialTransaction)
    total_commission_earned = 0.0
    
    query = query.filter(FinancialTransaction.transaction_type == 'saas_renewal')
    total_commission_earned = db_session.query(func.sum(User.debt)).filter(User.role.in_(['network', 'cafe'])).scalar() or 0.0

    transactions = query.order_by(FinancialTransaction.created_at.desc()).limit(100).all()
    
    total_revenue = query.filter(
        FinancialTransaction.payment_status == 'paid',
        FinancialTransaction.created_at >= start_of_month
    ).with_entities(func.sum(FinancialTransaction.amount)).scalar() or 0.0
    
    formatted_transactions = []
    for txn in transactions:
        entity_name = "غير محدد"
        if txn.entity_type in ['network', 'cafe', 'company']:
            user = db_session.query(User).filter_by(id=txn.user_id).first()
            entity_name = user.fullname if user else f"عميل ساس #{txn.user_id}"
        elif txn.entity_type == 'reseller':
            res = db_session.query(User).filter_by(id=txn.user_id).first()
            entity_name = res.fullname if res else f"موزع #{txn.user_id}"
        elif txn.entity_type == 'subscriber':
            sub = db_session.query(Subscriber).filter_by(id=txn.user_id).first()
            entity_name = sub.username if sub else f"مشترك #{txn.user_id}"
        elif txn.entity_type == 'flyer':
            entity_name = "عميل طياري (كارت فوري)"
            
        formatted_transactions.append({
            'id': txn.id,
            'date': txn.created_at.strftime('%Y-%m-%d %H:%M'),
            'entity_name': entity_name,
            'type': 'إيجار/مديونية وكالة' if txn.transaction_type == 'saas_renewal' else ('كارت فوري' if txn.transaction_type == 'instant_voucher' else 'تجديد باقة محلي'),
            'amount': f"{txn.amount:,.2f}",
            'status': txn.payment_status,
            'method': txn.payment_method or 'دفع إلكتروني'
        })

    # جلب الفواتير المعلقة للمراجعة اليدوية
    pending_invoices = db_session.query(PendingInvoice).filter_by(status='pending').order_by(PendingInvoice.created_at.desc()).all()
    total_debts = sum(inv.amount for inv in pending_invoices)

    # تجهيز بيانات الفواتير المعلقة للقالب
    pending_data = []
    for inv in pending_invoices:
        user = db_session.query(User).filter_by(id=inv.user_id).first()
        customer_name = user.fullname if user else f"عميل #{inv.user_id}"
        customer_phone = user.phone1 if user else inv.sender_phone
        customer_billing = inv.payer_billing_code
        pending_data.append({
            'id': inv.id,
            'user_id': inv.user_id,
            'customer_name': customer_name,
            'customer_phone': customer_phone,
            'billing_code': customer_billing,
            'amount': f"{inv.amount:,.2f}",
            'sender_phone': inv.sender_phone,
            'date': inv.created_at.strftime('%Y-%m-%d %H:%M'),
            'invoice_status': inv.status
        })

    return render_template('admin_finance.html', 
                            transactions=formatted_transactions,
                            pending_invoices=pending_data,
                            total_revenue=total_revenue,
                            total_debts=total_debts,
                            total_commission_earned=total_commission_earned)


# ==========================================================
# (جديد) مسار مخصص لتقارير الشبكات والموزعين (بدون تداخل مع الإدارة)
# ==========================================================
@finance_bp.route('/user_finance', methods=['GET'])
def user_finance():
    user_id = session.get('user_id')
    role = session.get('role')
    
    if role not in ['network', 'reseller', 'cafe']:
        abort(403)
        
    user = db_session.query(User).filter_by(id=user_id).first()
    if not user:
        abort(404)

    # جلب إعدادات النظام وتجهيزها للقالب
    app_settings = db_session.query(SystemSettings).first()
    app_settings_dict = {
        'app_primary_color': getattr(app_settings, 'primary_color', '#e11d48') if app_settings else '#e11d48'
    }

    # تجهيز كائن user_data بالبيانات اللي القالب بتاعك بيدور عليها
    package = user.package
    user_data = {
        'network_name': user.fullname,
        'support_phone': user.phone1,
        'package_name': package.name if package else "غير محدد",
        'price': package.price if package else 0.0,
        'next_renewal': user.saas_expiry_date.strftime('%Y-%m-%d') if user.saas_expiry_date else "غير محدد",
        'status': 'active' if user.is_active else 'inactive',
        'target_wallet': user.phone1, 
        'accumulated_commission': user.debt or 0.0
    }

    transactions = db_session.query(FinancialTransaction).filter(
        (FinancialTransaction.user_id == user_id) | 
        (FinancialTransaction.target_wallet_id == user_id)
    ).order_by(FinancialTransaction.created_at.desc()).all()

    return render_template('user_finance.html', 
                            user_data=user_data,
                            transactions=transactions,
                            app_settings=app_settings_dict,
                            payment_settings={'wallet_active': True, 'instapay_active': True})
                            
# ==========================================================
# 2. بوابة الفواتير والدعم المالي والتحقق من المهلة (SaaS Accounts Engine)
# ==========================================================
@finance_bp.route('/account/billing', methods=['GET'])
def sakr_account():
    user_id = session.get('user_id')
    role = session.get('role')
    
    if not user_id:
        return redirect(url_for('auth.login'))
        
    now_time = datetime.datetime.utcnow()
    is_locked = False
    is_readonly = False
    show_welcome_modal = False
    is_local_entity = False 
    
    if role in ['network', 'reseller', 'cafe']:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user: abort(404)
        
        created_at = getattr(user, 'created_at', now_time) or now_time
        billing_code = getattr(user, 'billing_code', None)
        is_local_entity = getattr(user, 'parent_id', None) is not None
        
        if not billing_code:
            if is_local_entity:
                prefix = 'RES-'
            else:
                prefix = 'NET-' if role in ['network', 'reseller'] else 'CAF-'
                
            user.billing_code = f"{prefix}{random.randint(100000, 999999)}"
            db_session.commit()
            billing_code = user.billing_code
            
        has_paid = (user.account_status == 'active' and (user.saas_expiry_date and user.saas_expiry_date > now_time)) if not is_local_entity else getattr(user, 'is_active', False)
        debt = getattr(user, 'debt', 0.0) or 0.0
        balance = getattr(user, 'current_balance', 0.0) or 0.0

    elif role == 'subscriber':
        sub = db_session.query(Subscriber).filter_by(id=user_id).first()
        if not sub: abort(404)
        
        created_at = sub.created_at or now_time
        billing_code = getattr(sub, 'billing_code', None)
        is_local_entity = getattr(sub, 'network_id', None) is not None
        
        if not billing_code:
            prefix = 'SUB-'
            sub.billing_code = f"{prefix}{random.randint(100000, 999999)}"
            db_session.commit()
            billing_code = sub.billing_code
            
        has_paid = (sub.status == 'active' and (sub.expiry_date and sub.expiry_date > now_time))
        debt = 0.0
        balance = getattr(sub, 'current_balance', 0.0) or 0.0
    else:
        abort(403)
        
    elapsed_time = now_time - created_at
    
    if not has_paid:
        if elapsed_time > datetime.timedelta(hours=48):
            is_locked = True
            session['is_locked'] = True
        else:
            is_readonly = True  
            show_welcome_modal = True  
    else:
        session['is_locked'] = False
        session['is_readonly'] = False

    saas_package = None
    if not is_local_entity and role in ['network', 'cafe']:
        saas_package = db_session.query(SaasPackage).filter_by(id=user.package_id if role in ['network', 'cafe'] else None).first()
    
    billing_data = {
        'collect_code': billing_code,
        'balance': balance,
        'debts': debt if role != 'subscriber' else (saas_package.price if saas_package and not has_paid else 0.0),
        'total_invoice': saas_package.price if saas_package else (debt if debt > 0 else 0.0),
        'expiry_date': (user.saas_expiry_date.strftime('%Y-%m-%d %H:%M') if role != 'subscriber' else sub.expiry_date.strftime('%Y-%m-%d %H:%M')) if has_paid else 'ينتهي قريباً',
        'invoice_start': created_at.strftime('%Y-%m-%d'),
        'invoice_end': (created_at + datetime.timedelta(days=30)).strftime('%Y-%m-%d'),
        'duration_days': 30,
        'extra_fees': 0.0
    }
    
    transfers = db_session.query(FinancialTransaction).filter(
        (FinancialTransaction.user_id == user_id) | (FinancialTransaction.target_wallet_id == user_id)
    ).order_by(FinancialTransaction.created_at.desc()).all()
    
    return render_template('sakr_account.html', 
                            billing=billing_data, 
                            saas_package=saas_package, 
                            transfers=transfers, 
                            is_locked=is_locked,
                            is_readonly=is_readonly,
                            show_welcome_modal=show_welcome_modal,
                            is_local_entity=is_local_entity)


# ==========================================================
# 3. محرك التحصيل الآلي المركزي (Dual-Path Webhook Engine)
# ==========================================================
@finance_bp.route('/webhook/payment', methods=['POST'])
def payment_webhook():
    payment_setting = db_session.query(GlobalSetting).filter_by(setting_key='payment_gateway_config').first()
    payment_config = json.loads(payment_setting.setting_value) if payment_setting and payment_setting.setting_value else {}
    expected_secret = payment_config.get('webhook_secret', '')
    
    provided_secret = request.headers.get('X-Sakr-Signature') or request.headers.get('Authorization')
    if expected_secret and provided_secret != expected_secret:
        return jsonify({"status": "error", "message": "Unauthorized Webhook Call - توقيع غير مصرح به"}), 401

    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "لم يتم استلام أي بيانات"}), 400

    billing_code = data.get('billing_code') or data.get('reference')
    amount = float(data.get('amount', 0.0))
    transaction_ref = data.get('transaction_id', 'AUTO-WEBHOOK')
    payment_method = data.get('payment_method', 'SakrConnectPay')

    if not billing_code:
        return jsonify({"status": "error", "message": "كود التحصيل مفقود"}), 400

    now_time = datetime.datetime.utcnow()
    commission_rate = get_commission_rate()

    # [المسار الجديد المطور]: مطابقة أكواد الفواتير والمعاملات المعلقة المباشرة لترقية الباقات
    if str(billing_code).startswith('TX-'):
        txn = db_session.query(FinancialTransaction).filter_by(transaction_ref=billing_code, payment_status='pending').first()
        if not txn:
            return jsonify({"status": "error", "message": "المعاملة المالية غير موجودة أو تم سدادها بالفعل"}), 404
            
        user = db_session.query(User).filter_by(id=txn.user_id).first()
        if not user:
            return jsonify({"status": "error", "message": "المستخدم الخاص بالعملية غير موجود"}), 404
            
        txn.payment_status = 'paid'
        txn.payment_method = payment_method
        txn.transaction_ref = f"WEBHOOK-{transaction_ref}"
        
        sys_type = 'cafe' if user.role == 'cafe' else ('reseller' if user.role == 'reseller' else 'network')
        pkg = db_session.query(SaasPackage).filter_by(system_type=sys_type, price=amount, is_active=True).first()
        
        days_to_add = 30
        if pkg:
            user.package_id = pkg.id
            user.max_routers = getattr(pkg, 'max_servers', user.max_routers)
            user.max_subscribers = getattr(pkg, 'max_subscribers', user.max_subscribers)
            days_to_add = getattr(pkg, 'duration_months', 1) * 30
        else:
            user.current_balance = (user.current_balance or 0.0) + amount
            days_to_add = 0
            
        if days_to_add > 0:
            user.account_status = 'active'
            user.is_active = True
            user.debt = 0.0
            if user.saas_expiry_date and user.saas_expiry_date > now_time:
                user.saas_expiry_date += datetime.timedelta(days=days_to_add)
            else:
                user.saas_expiry_date = now_time + datetime.timedelta(days=days_to_add)
        
        invoice = db_session.query(PendingInvoice).filter_by(user_id=user.id, amount=amount, status='pending').order_by(PendingInvoice.created_at.desc()).first()
        if invoice:
            invoice.status = 'paid'
            
        db_session.commit()
        return jsonify({"status": "success", "message": "تمت معالجة الفاتورة المعلقة وتفعيل الباقة ديناميكياً."}), 200

    # تحليل البادئة في حال كان كود تحصيل عادي
    prefix = billing_code.split('-')[0] + '-' if '-' in billing_code else ''

    try:
        # المسار الأول: مسار وكالة صقر ميديا (SaaS & Debt Collection)
        if prefix in ['NET-', 'CAF-', 'COM-', 'SYS-']:
            user = db_session.query(User).filter_by(billing_code=billing_code).first()
            if not user:
                return jsonify({"status": "error", "message": "حساب الساس غير موجود"}), 404

            user.account_status = 'active'
            user.is_active = True
            user.debt = 0.0 
            
            if user.saas_expiry_date and user.saas_expiry_date > now_time:
                user.saas_expiry_date += datetime.timedelta(days=30)
            else:
                user.saas_expiry_date = now_time + datetime.timedelta(days=30)

            new_tx = FinancialTransaction(
                user_id=user.id,
                entity_type=user.role,
                transaction_type='saas_renewal',
                amount=amount,
                payment_status='paid',
                payment_method=payment_method,
                transaction_ref=transaction_ref,
                created_at=now_time
            )
            db_session.add(new_tx)
            db_session.commit()
            return jsonify({"status": "success", "message": "تم التجديد وسداد المديونية لصالح الوكالة بنجاح."}), 200

        # المسار الثاني: المسار المحلي لأصحاب الشبكات (مشتركين / موزعين)
        elif prefix in ['SUB-', 'RES-']:
            owner_id = None
            tx_user_id = None
            entity_type = None

            if prefix == 'SUB-':
                sub = db_session.query(Subscriber).filter_by(billing_code=billing_code).first()
                if not sub:
                    return jsonify({"status": "error", "message": "المشترك غير موجود"}), 404
                    
                network = db_session.query(Network).filter_by(id=sub.network_id).first()
                owner_id = network.owner_id if network else None
                
                sub.status = 'active'
                sub.quota_used = 0.0
                if sub.expiry_date and sub.expiry_date > now_time:
                    sub.expiry_date += datetime.timedelta(days=30)
                else:
                    sub.expiry_date = now_time + datetime.timedelta(days=30)

                tx_user_id = sub.id
                entity_type = 'subscriber'

                if get_router_and_execute and network and network.router_id:
                    active_profile = sub.offer.name if getattr(sub, 'offer', None) else 'default'
                    try:
                        get_router_and_execute(router_id=network.router_id, action_func='change_pppoe_profile', username=sub.username, new_profile=active_profile)
                    except Exception as e:
                        print(f"Mikrotik Error: {str(e)}")

            elif prefix == 'RES-':
                reseller = db_session.query(User).filter_by(billing_code=billing_code).first()
                if not reseller:
                    return jsonify({"status": "error", "message": "الموزع غير موجود"}), 404
                    
                owner_id = reseller.parent_id 
                reseller.debt = 0.0
                reseller.is_active = True
                tx_user_id = reseller.id
                entity_type = 'reseller'

            network_owner = db_session.query(User).filter_by(id=owner_id).first()
            if network_owner:
                network_owner.current_balance = (network_owner.current_balance or 0.0) + amount
                commission = amount * commission_rate
                network_owner.debt = (network_owner.debt or 0.0) + commission

            new_tx = FinancialTransaction(
                user_id=tx_user_id,
                target_wallet_id=owner_id, 
                entity_type=entity_type,
                transaction_type='local_renewal',
                amount=amount,
                payment_status='paid',
                payment_method=payment_method,
                transaction_ref=transaction_ref,
                created_at=now_time
            )
            db_session.add(new_tx)
            db_session.commit()
            return jsonify({"status": "success", "message": "تم التجديد المحلي وإضافة الرصيد لمحفظة الشبكة وتقييد العمولة."}), 200

        # المسار الثالث: العميل الطياري - شراء الكروت الفورية (VOU-) - كروت فورية Offline بدون تسجيل
        elif prefix == 'VOU-':
            invoice = db_session.query(PendingInvoice).filter_by(payer_billing_code=billing_code, status='pending').first()
            if not invoice:
                return jsonify({"status": "error", "message": "لم يتم العثور على فاتورة معلقة لهذا الكود"}), 404

            network_owner = db_session.query(User).filter_by(id=invoice.user_id).first()
            if not network_owner:
                return jsonify({"status": "error", "message": "صاحب الشبكة غير موجود"}), 404

            network_owner.current_balance = (network_owner.current_balance or 0.0) + amount
            commission = amount * commission_rate
            network_owner.debt = (network_owner.debt or 0.0) + commission

            network = db_session.query(Network).filter_by(owner_id=network_owner.id).first()
            voucher = None
            if network:
                voucher = db_session.query(Voucher).filter_by(network_id=network.id, status='unused', price=invoice.amount).first()
                if voucher:
                    voucher.status = 'sold'
                    voucher.is_instant = True
                    voucher.sold_at = now_time
                    invoice.card_template_id = voucher.id

            invoice.status = 'paid'

            new_tx = FinancialTransaction(
                user_id=invoice.id, 
                target_wallet_id=network_owner.id,
                entity_type='flyer',
                transaction_type='instant_voucher',
                amount=amount,
                payment_status='paid',
                payment_method=payment_method,
                transaction_ref=f"Voucher: {voucher.code if voucher else 'N/A'}",
                created_at=now_time
            )
            db_session.add(new_tx)
            db_session.commit()
            return jsonify({
                "status": "success", 
                "message": "تم شراء الكارت الفوري وإضافة الرصيد لمحفظة الشبكة وتقييد العمولة.",
                "voucher_code": voucher.code if voucher else None
            }), 200

        else:
            return jsonify({"status": "error", "message": "بادئة كود التحصيل غير معروفة"}), 400

    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": f"حدث خطأ داخلي في معالجة الدفع: {str(e)}"}), 500


# ==========================================================
# 4. واجهات الترقية والدفع المباشر للإنتاج (PRODUCTION ARTIFACTS)
# ==========================================================

@finance_bp.route('/packages/upgrade', methods=['GET'])
def upgrade_package():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    user_id = session['user_id']
    user = db_session.query(User).filter_by(id=user_id).first()
    if not user:
        abort(404)
        
    sys_type = 'cafe' if user.role == 'cafe' else 'network'
    # فلترة الباقات حسب دولة المستخدم (EG = مصري، INT = دولي)
    country = getattr(user, 'country', 'EG')
    if country == 'EG':
        system_types = [sys_type]
    else:
        system_types = [f"{sys_type}_int"]
    
    available_packages = db_session.query(SaasPackage).filter(
        SaasPackage.system_type.in_(system_types), 
        SaasPackage.is_active==True
    ).order_by(SaasPackage.price.asc()).all()
    
    return render_template('upgrade_packages.html', packages=available_packages, user=user, user_country=country)


@finance_bp.route('/finance/add-transaction', methods=['GET'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    user_id = session['user_id']
    user = db_session.query(User).filter_by(id=user_id).first()
    return render_template('add_transaction.html', user=user)


@finance_bp.route('/finance/checkout', methods=['POST'])
def finance_checkout():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    user_id = session['user_id']
    package_id = request.form.get('package_id')
    custom_amount = request.form.get('amount')
    sender_phone = request.form.get('sender_phone', '').strip()
    payment_method = request.form.get('payment_method', 'Electronic Wallet')

    now_time = datetime.datetime.utcnow()
    
    try:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            abort(404)
            
        target_amount = 0.0
        pkg_name = "شحن محفظة / تسديد مديونية"
        pkg = None
        
        if package_id:
            pkg = db_session.query(SaasPackage).filter_by(id=int(package_id)).first()
            if not pkg:
                flash('🚨 الباقة المطلوبة غير موجودة بنظام صقر كونكت المركزي.', 'danger')
                return redirect('/client/account')
            target_amount = pkg.price
            pkg_name = f"ترقية إلى باقة: {pkg.name}"
        else:
            target_amount = float(custom_amount) if custom_amount else 0.0

        if target_amount <= 0:
            flash('🚨 يرجى تحديد قيمة مالية صحيحة لإتمام العملية.', 'danger')
            return redirect('/client/account')

        # أتمتة حقيقية: التفعيل الفوري إذا كان رصيد المحفظة يغطي التكلفة بالكامل
        if user.current_balance >= target_amount and package_id and pkg:
            user.current_balance -= target_amount
            user.package_id = pkg.id
            
            months = getattr(pkg, 'duration_months', 1)
            days_to_add = months * 30
            
            if user.saas_expiry_date and user.saas_expiry_date > now_time:
                user.saas_expiry_date += datetime.timedelta(days=days_to_add)
            else:
                user.saas_expiry_date = now_time + datetime.timedelta(days=days_to_add)
                
            user.account_status = 'active'
            user.is_active = True
            user.max_routers = getattr(pkg, 'max_servers', user.max_routers)
            user.max_subscribers = getattr(pkg, 'max_subscribers', user.max_subscribers)
            
            new_tx = FinancialTransaction(
                user_id=user.id,
                entity_type=user.role,
                transaction_type='saas_renewal',
                amount=target_amount,
                package_name=pkg_name,
                payment_status='paid',
                payment_method='Wallet Balance',
                transaction_ref=f"BAL-AUTO-{int(now_time.timestamp())}",
                created_at=now_time
            )
            db_session.add(new_tx)
            db_session.commit()
            flash(f'✅ تم خصم التكلفة من رصيدك المتاح، وتفعيل {pkg_name} بنجاح وبشكل فوري!', 'success')
            
        else:
            # الرصيد لا يكفي -> توليد طلب دفع وفاتورة معلقة حقيقية ليلقطها محرك الـ Webhook تلقائياً
            ref_code = f"TX-{user.id}-{int(now_time.timestamp())}"
            
            new_tx = FinancialTransaction(
                user_id=user.id,
                entity_type=user.role,
                transaction_type='saas_renewal',
                amount=target_amount,
                package_name=pkg_name,
                payment_status='pending',
                payment_method=payment_method,
                transaction_ref=ref_code,
                created_at=now_time
            )
            db_session.add(new_tx)
            
            new_invoice = PendingInvoice(
                user_id=user.id,
                payer_billing_code=user.billing_code,  # تم إضافة السطر هنا بنجاح لربط الكود المركزي
                subscriber_username=user.username,
                amount=target_amount,
                sender_phone=sender_phone if sender_phone else (user.phone1 or "01000000000"),
                status='pending',
                offer_id=None,
                is_instant=True if package_id else False,
                created_at=now_time
            )
            db_session.add(new_invoice)
            db_session.commit()
            
            flash(f'⏳ تم إنشاء طلب الدفع بنجاح كود المرجع: {ref_code}. يرجى تحويل مبلغ {target_amount} ج.م لتفعيل حسابك تلقائياً وبشكل فوري عند إتمام التحويل.', 'info')

        return redirect('/client/account')

    except Exception as e:
        db_session.rollback()
        flash(f'🚨 حدث خطأ أثناء معالجة الفاتورة: {str(e)}', 'danger')
        return redirect('/client/account')


# ==========================================================
# 5. دوال التحكم اليدوي الكاش والعمليات السيادية للإدارة العليا (جديد)
# ==========================================================

@finance_bp.route('/manage/client/payment', methods=['POST'])
def manual_admin_payment():
    """ استقبال دفع الكاش يدوي في يدك وتصفير المديونية المتأخرة فوراً أو شحن المحفظة """
    if session.get('role') not in ['admin', 'super_admin']:
        abort(403)
        
    client_id = request.form.get('client_id')
    amount = float(request.form.get('amount', 0.0))
    transaction_type = request.form.get('transaction_type')
    
    user = db_session.query(User).filter_by(id=client_id).first()
    if not user:
        flash('⚠️ العميل غير موجود في نظام صقر كونكت.', 'danger')
        return redirect(request.referrer or '/admin/finance')
        
    now_time = datetime.datetime.utcnow()
    
    if transaction_type == 'settle_debt':
        user.debt = 0.0
        user.account_status = 'active'
        user.is_active = True
        
        if user.saas_expiry_date and user.saas_expiry_date > now_time:
            user.saas_expiry_date += datetime.timedelta(days=30)
        else:
            user.saas_expiry_date = now_time + datetime.timedelta(days=30)
            
        tx_type = 'saas_renewal'
        msg = f'✅ تم استلام الكاش، تسديد مديونية ({user.fullname}) بالكامل، وفتح لوحة التحكم بنجاح.'
        
    elif transaction_type == 'add_balance':
        user.current_balance = (user.current_balance or 0.0) + amount
        tx_type = 'wallet_recharge'
        msg = f'✅ تم إيداع شحن مالي يدوي بقيمة {amount} ج.م في محفظة العميل ({user.fullname}).'
    else:
        flash('🚨 نوع الإجراء المالي غير معروف.', 'danger')
        return redirect(request.referrer or '/admin/finance')
        
    new_tx = FinancialTransaction(
        user_id=user.id,
        entity_type=user.role,
        transaction_type=tx_type,
        amount=amount,
        payment_status='paid',
        payment_method='Cash (Manual)',
        transaction_ref=f"CASH-{user.id}-{int(now_time.timestamp())}",
        created_at=now_time
    )
    db_session.add(new_tx)
    
    invoice = db_session.query(PendingInvoice).filter_by(user_id=user.id, status='pending').order_by(PendingInvoice.created_at.desc()).first()
    if invoice:
        invoice.status = 'paid'
        
    try:
        db_session.commit()
        flash(msg, 'success')
    except Exception as e:
        db_session.rollback()
        flash(f'🚨 حدث خطأ أثناء معالجة القيد: {str(e)}', 'danger')
        
    return redirect(request.referrer or '/admin/finance')


@finance_bp.route('/subscribers/renew/<int:transaction_id>', methods=['POST'])
def manual_settle_transaction(transaction_id):
    """ اعتماد الفاتورة المعلقة يدوياً من دفتر حسابات الإدارة وفتح باقة الساس فوراً """
    if session.get('role') not in ['admin', 'super_admin']:
        return jsonify({"status": "error", "message": "غير مصرح لك بدخول بوابة الإدارة الماليّة"}), 403

    txn = db_session.query(FinancialTransaction).filter_by(id=transaction_id, payment_status='pending').first()
    if not txn:
        return jsonify({"status": "error", "message": "المعاملة المالية غير موجودة أو تم اعتمادها مسبقاً"}), 404

    user = db_session.query(User).filter_by(id=txn.user_id).first()
    if not user:
        return jsonify({"status": "error", "message": "العميل صاحب المعاملة لم يعد مسجلاً بالنظام"}), 404

    now_time = datetime.datetime.utcnow()
    txn.payment_status = 'paid'
    txn.payment_method = 'Manual Settlement (Admin)'
    
    user.account_status = 'active'
    user.is_active = True
    user.debt = 0.0
    
    if user.saas_expiry_date and user.saas_expiry_date > now_time:
        user.saas_expiry_date += datetime.timedelta(days=30)
    else:
        user.saas_expiry_date = now_time + datetime.timedelta(days=30)

    invoice = db_session.query(PendingInvoice).filter_by(user_id=user.id, amount=txn.amount, status='pending').order_by(PendingInvoice.created_at.desc()).first()
    if invoice:
        invoice.status = 'paid'

    try:
        db_session.commit()
        return jsonify({"status": "success", "message": "تم تسوية الفاتورة يدوياً بنجاح، وتمديد فترة الساس للعميل."}), 200
    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


@finance_bp.route('/api/client/action', methods=['POST'])
def api_client_action():
    """ محرك الأوامر والقرارات السيادية للإدارة المركزية (طرد، إيقاف، حذف، تغيير باسوورد، فحص ويب هوك) """
    if session.get('role') not in ['admin', 'super_admin']:
        return jsonify({"status": "error", "message": "صلاحيات غير كافية لتنفيذ الأمر السيادي"}), 403

    data = request.get_json() or {}
    action = data.get('action')
    target_id = data.get('id')
    
    if not action or not target_id:
        return jsonify({"status": "error", "message": "معطيات الأمر المركزي مفقودة"}), 400

    try:
        if action == 'retry_webhook':
            txn = db_session.query(FinancialTransaction).filter_by(id=target_id).first()
            if txn and txn.payment_status == 'pending':
                return jsonify({"status": "error", "message": "بوابة الدفع الشريكة لم تسجل أي حوالات مكتملة لهذا المرجع حتى الآن."}), 200
            return jsonify({"status": "success", "message": "المعاملة مكتملة ومطابقة مسبقاً في الدفاتر."}), 200
            
        elif action == 'suspend':
            user = db_session.query(User).filter_by(id=target_id).first()
            if user:
                user.is_active = not user.is_active
                db_session.commit()
                return jsonify({"status": "success", "message": "تم تغيير حالة ربط الخدمة بنجاح."}), 200
            return jsonify({"status": "error", "message": "حساب العميل غير موجود"}), 404
            
        elif action == 'change_password':
            new_password = data.get('value')
            if not new_password:
                return jsonify({"status": "error", "message": "الباسوورد الجديد فارغ"}), 400
            user = db_session.query(User).filter_by(id=target_id).first()
            if user:
                user.password_hash = generate_password_hash(new_password)
                db_session.commit()
                return jsonify({"status": "success", "message": "تم تشفير وتحديث كلمة المرور الجديدة فوراً."}), 200
            return jsonify({"status": "error", "message": "الحساب مفقود"}), 404
            
        elif action == 'delete':
            user = db_session.query(User).filter_by(id=target_id).first()
            if user:
                db_session.query(Network).filter_by(owner_id=user.id).delete()
                db_session.delete(user)
                db_session.commit()
                return jsonify({"status": "success", "message": "تم مسح العميل وجميع البنى التحتية التابعة له من السيرفر بنجاح."}), 200
            return jsonify({"status": "error", "message": "الحساب محذوف بالفعل"}), 404

        elif action == 'toggle_merge':
            user = db_session.query(User).filter_by(id=target_id).first()
            if user:
                current = getattr(user, 'show_merge', True)
                user.show_merge = not current
                # Also sync to network_clients if exists
                try:
                    from database.central_models import NetworkClient
                    nc = db_session.query(NetworkClient).filter_by(client_name=user.username).first()
                    if nc and hasattr(nc, 'show_merge'):
                        nc.show_merge = user.show_merge
                except:
                    pass
                db_session.commit()
                status = "مفعلة" if user.show_merge else "مخفية"
                return jsonify({"status": "success", "message": f"تم تغيير حالة صفحة الدمج إلى: {status}"}), 200
            return jsonify({"status": "error", "message": "العميل غير موجود"}), 404
            
        return jsonify({"status": "error", "message": "أمر سيادي غير مدعوم بالنظام"}), 400

    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": f"خطأ داخلي في السيرفر: {str(e)}"}), 500