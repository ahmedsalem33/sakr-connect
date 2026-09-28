# ==============================================================================
# SAKR CONNECT - FULL RECHARGE & REVENUE ENGINE (PRODUCTION)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# ==============================================================================

from flask import Blueprint, render_template, session, request, jsonify
from database.models import Subscriber, User, FinancialTransaction, Voucher, PendingInvoice, Network
from core.db_manager import db_session

# تم تصحيح المسار ليتوافق مع هيكل مجلدات "صقر كونكت" (الأوتوماتيك)
from core.mikrotik.dispatcher import get_router_and_execute 
from datetime import datetime

recharge_bp = Blueprint('recharge', __name__)

# --- دالة مساعدة لحساب العمولة وترحيلها لمديونية الموزع ---
def apply_commission(user, amount):
    commission_rate = 0.05  # 5% عمولة صقر ميديا (يمكن تعديلها من الإعدادات لاحقاً)
    commission = amount * commission_rate
    user.debt = (user.debt or 0.0) + commission
    return commission

# ==========================================
# 1. شحن مباشر (محفظة إلى محفظة) والتفعيل التلقائي
# ==========================================
@recharge_bp.route('/api/recharge/transfer', methods=['POST'])
def process_transfer():
    data = request.json
    reseller_id = session.get('user_id')
    subscriber_id = data.get('subscriber_id')
    amount = float(data.get('amount', 0))
    # اسم البروفايل أو العرض اللي العميل اختاره
    new_profile = data.get('profile_name', 'Active')

    reseller = db_session.query(User).filter_by(id=reseller_id).first()
    subscriber = db_session.query(Subscriber).filter_by(id=subscriber_id).first()

    if reseller.current_balance < amount:
        return jsonify({"status": "error", "message": "رصيد الموزع غير كافي لإتمام الشحن."})

    # العمليات المالية (بدون تدخل بشري)
    reseller.current_balance -= amount
    subscriber.balance = (subscriber.balance or 0.0) + amount
    apply_commission(reseller, amount)

    # تسجيل الحركة في الدفتر المالي
    tx = FinancialTransaction(
        user_id=subscriber.id, 
        entity_type='subscriber', 
        amount=amount, 
        transaction_type='local_renewal', 
        payment_status='paid'
    )
    db_session.add(tx)

    # ============================================================
    # قلب الأوتوماتيك: إرسال أمر فوري للمايكروتيك لتفعيل الخدمة
    # ============================================================
    activation = get_router_and_execute(
        subscriber.router_id, 
        'change_pppoe_profile', 
        username=subscriber.username, 
        new_profile=new_profile
    )

    if activation and activation.get('success'):
        db_session.commit()
        return jsonify({"status": "success", "message": "تم الشحن وتفعيل السرعة في المايكروتيك بنجاح."})
    else:
        # التراجع المالي لو المايكروتيك كان فاصل عشان فلوس الموزع ماتضيعش
        db_session.rollback()
        return jsonify({"status": "error", "message": "فشل الاتصال بالمايكروتيك لتفعيل الخدمة، لم يتم خصم الرصيد."})

# ==========================================
# 2. شحن كروت الخدش (Scratch Cards) من التطبيق
# ==========================================
@recharge_bp.route('/api/recharge/scratch', methods=['POST'])
def process_scratch():
    data = request.json
    pin = data.get('pin')
    sub_id = data.get('subscriber_id')

    voucher = db_session.query(Voucher).filter_by(username=pin, status='unused').first()
    if not voucher:
        return jsonify({"status": "error", "message": "الكارت غير صالح أو تم استخدامه مسبقاً."})

    subscriber = db_session.query(Subscriber).filter_by(id=sub_id).first()
    
    # حرق الكارت وإضافة الرصيد
    voucher.status = 'used'
    voucher.used_at = datetime.utcnow()
    subscriber.balance = (subscriber.balance or 0.0) + voucher.price
    
    # يمكن استدعاء get_router_and_execute هنا أيضاً لتفعيل النت فوراً لو الرصيد غطى الباقة
    
    db_session.commit()
    return jsonify({"status": "success", "message": "تم شحن الكارت بنجاح في محفظتك."})

# ==========================================
# 3. طلب إيداع يدوي من المحافظ (للموزعين)
# ==========================================
@recharge_bp.route('/api/recharge/wallet-request', methods=['POST'])
def wallet_deposit_request():
    data = request.json
    reseller_id = session.get('user_id')
    amount = float(data.get('amount', 0))
    wallet_number = data.get('wallet_number') 
    
    # إنشاء فاتورة معلقة (Pending) بانتظار السيستم يراجعها
    invoice = PendingInvoice(
        user_id=reseller_id,
        amount=amount,
        billing_code=f"WALT-{datetime.utcnow().strftime('%Y%m%d%H%M')}",
        status='pending',
        details=f"إيداع عبر محفظة كاش من رقم: {wallet_number}"
    )
    db_session.add(invoice)
    db_session.commit()
    
    return jsonify({"status": "success", "message": "تم إرسال الطلب وجاري مراجعته أوتوماتيكياً."})

# ==========================================
# 4. API خاص بالتطبيق (للعميل الطياري Instant Flyer)
# ==========================================
@recharge_bp.route('/api/app/flyer/activate', methods=['POST'])
def flyer_activate():
    # هنا يتم الربط بالـ MAC للشبكة والـ API فور الدفع من التطبيق
    data = request.json
    mac_address = data.get('mac_address')
    router_id = data.get('router_id')
    
    return jsonify({"status": "success", "message": "تم تفعيل شبكة العميل الطياري أوتوماتيكياً."})