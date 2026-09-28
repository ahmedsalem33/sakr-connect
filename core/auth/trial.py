"""
Project: Sakr Connect
Developer: Sakr Media Agency (صقر ميديا)
Lead Engineer: أحمد سالم الملواني
Support: 01033379719 - 01033379719
"""

from datetime import datetime, timezone, timedelta
from database.models import User


def get_effective_owner(user: User) -> User:
    """
    يرجع المالك الفعلي للحساب (صاحب الشبكة) سواء كان المستخدم مالك أو موزع/مدير
    """
    if user.role in ['reseller', 'manager'] and user.parent_id:
        owner = User.query.filter_by(id=user.parent_id).first()
        return owner if owner else user
    return user


def get_trial_status(user: User) -> dict:
    """
    الدالة الموحدة لحساب حالة الفترة التجريبية والقفل.
    ترجع: {
        'is_trial': bool,          # لا يزال في الفترة التجريبية (48 ساعة)
        'is_locked': bool,         # مقفول تماماً (انتهت التجربة أو الاشتراك)
        'remaining_seconds': int,  # ثواني متبقية في التجربة (0 لو مقفول)
        'trial_end_iso': str,      # ISO datetime لنهاية التجربة
        'account_status': str,     # 'trial' | 'active' | 'expired'
        'saas_expiry_date': str    # ISO datetime لانتهاء الاشتراك المدفوع (لو فيه)
    }
    """
    now = datetime.now(timezone.utc)
    owner = get_effective_owner(user)

    # الإدارة العليا لا تخضع للتجربة أو القفل إطلاقاً
    if getattr(owner, 'role', None) in ['admin', 'super_admin']:
        return {
            'is_trial': False,
            'is_locked': False,
            'remaining_seconds': 0,
            'trial_end_iso': now.isoformat(),
            'account_status': 'active',
            'saas_expiry_date': None
        }
    
    
    # تاريخ إنشاء الحساب (صفوف قديمة قد يكون NULL -> نعتبرها جديدة بتجربة كاملة)
    created_at = getattr(owner, 'created_at', None) or now
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    
    # نهاية الفترة التجريبية (48 ساعة من الإنشاء)
    trial_end = created_at + timedelta(hours=48)
    
    # حالة الاشتراك المدفوع - للكافيهات والشبكات: لا يعتبر trial اشتراك فعال
    has_active_sub = False
    saas_expiry = getattr(owner, 'saas_expiry_date', None)
    # فقط لو account_status == 'active' يعتبر الاشتراك مدفوع (يمنع احتساب 48h التجريبية كاشتراك)
    owner_status = getattr(owner, 'account_status', 'trial')
    if saas_expiry and owner_status == 'active':
        if saas_expiry.tzinfo is None:
            saas_expiry = saas_expiry.replace(tzinfo=timezone.utc)
        if now <= saas_expiry:
            has_active_sub = True
    # حالة خاصة للكافيهات: لو باقي trial لكن لم يدفع, يبقى trial فقط
    
    # الحساب النهائي - أولوية الاشتراك, ثم التجربة, ثم القفل
    is_trial_active = (now <= trial_end) and not has_active_sub and owner_status == 'trial'
    is_locked = not has_active_sub and not is_trial_active
    
    remaining_seconds = 0
    if is_trial_active:
        delta = trial_end - now
        remaining_seconds = max(0, int(delta.total_seconds()))
    
    # تحديث account_status في DB لو محتاج
    if has_active_sub:
        account_status = 'active'
    elif is_trial_active:
        account_status = 'trial'
    else:
        account_status = 'expired'
    
    return {
        'is_trial': is_trial_active,
        'is_locked': is_locked,
        'remaining_seconds': remaining_seconds,
        'trial_end_iso': trial_end.isoformat(),
        'account_status': account_status,
        'saas_expiry_date': saas_expiry.isoformat() if saas_expiry else None
    }


def update_user_account_status(user: User) -> None:
    """
    يحدث account_status في قاعدة البيانات بناءً على الحالة الحالية
    """
    status = get_trial_status(user)
    owner = get_effective_owner(user)
    if owner.account_status != status['account_status']:
        owner.account_status = status['account_status']
        # لا نعمل commit هنا - يترك للوظيفة المستدعية