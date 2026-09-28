# ==============================================================================
# SAKR CONNECT - DATABASE MODELS (CORE ARCHITECTURE - FULLY UPDATED)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: مسجلة باسم مشروع Sakr Connect
# الدعم الفني للمطور: 01033379719 - 01033379719
# العنوان: 
# صفحة المطور: https://www.facebook.com/ahmedsalemJournalist
# صفحة الوكالة: https://www.facebook.com/sakrmediaagency
# ==============================================================================

import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, BigInteger, Text, Float, JSON
from sqlalchemy.orm import relationship, backref
from core.db_manager import Base

class SaasPackage(Base):
    """
    جدول إدارة باقات الساس المركزية للأقسام الأساسية فقط.
    """
    __tablename__ = 'saas_packages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    system_type = Column(String(50), nullable=False)  # القيود الحصرية: 'network', 'cafe', 'network_int', 'cafe_int'
    name = Column(String(100), nullable=False)
    price = Column(Float, default=0.0)
    duration_months = Column(Integer, default=1)
    
    max_servers = Column(Integer, default=0)
    max_subscribers = Column(Integer, default=0)
    max_vouchers = Column(Integer, default=0)
    max_designs = Column(Integer, default=0)
    max_offers = Column(Integer, default=0)
    max_resellers = Column(Integer, default=0)
    extra_server_price = Column(Float, default=0.0)
    
    is_active = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
    
    # الدولة والعملة للفصل بين مصر (EGP) والدولي (USD)
    country = Column(String(2), default='EG', nullable=False)  # 'EG' أو 'INT'
    currency = Column(String(10), default='EGP', nullable=False)  # 'EGP' أو 'USD'
    
    hotspot_file = Column(String(255), nullable=True)
    app_file = Column(String(255), nullable=True)
    app_access = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class User(Base):
    """
    جدول المستخدمين المركزي (SaaS Core Clients & Resellers)
    تم توحيد العملاء الأساسيين (network, cafe, home) وعزلهم عن المشتركين.
    """
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    
    # الأدوار الأساسية: 'network', 'cafe', 'home' | الأدوار الفرعية: 'reseller', 'manager'
    role = Column(String(20), nullable=False, default='network') 
    fullname = Column(String(100), nullable=False)
    email = Column(String(150), nullable=True)
    phone1 = Column(String(20), nullable=True)
    phone2 = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)
    
    # بلد العميل (EG / INT) - للكشف التلقائي والتسعير
    country = Column(String(2), default='EG', nullable=False)
    
    # ⚠️ [التحصيل الرقمي - SaaS]: كود التحصيل الأساسي الذي يقرأه الـ Webhook لتجديد باقة العميل
    billing_code = Column(String(50), unique=True, nullable=True, index=True)
    
    # حقول صلاحية الساس ومهلة الـ 48 ساعة التجريبية لغلق اللوحة كاملة
    saas_expiry_date = Column(DateTime, nullable=True) 
    account_status = Column(String(20), default='trial') # تم التعديل إلى trial ليتوافق مع التسجيل
    grace_period_end = Column(DateTime, nullable=True)
    
    # ⚠️ [الإدارة المركزية]: تتبع المشتركين الجدد والترحيب بهم
    is_welcomed = Column(Boolean, default=False)
    
    # بصمة الربط الخاصة بتطبيق الموبايل
    api_token = Column(String(255), unique=True, nullable=True, index=True)
    
    # ربط العميل الأساسي بباقة الساس المركزية
    package_id = Column(Integer, ForeignKey('saas_packages.id', ondelete="SET NULL"), nullable=True)
    package = relationship("SaasPackage", backref="users")
    
    # التسلسل الهرمي: ربط الموزع الفرعي بصاحب الشبكة
    parent_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    discount_rate = Column(Float, default=0.0) 
    permissions = Column(JSON, nullable=True)  
    children = relationship("User", backref=backref("parent", remote_side=[id]))
    
    # حدود التشغيل المحسوبة ديناميكياً
    max_routers = Column(Integer, default=1)
    max_subscribers = Column(Integer, default=0)
    max_vouchers = Column(Integer, default=0)
    auto_balance = Column(Float, default=0.0)
    current_balance = Column(Float, default=0.0)
    debt = Column(Float, default=0.0)
    profit_type = Column(String(50), default='fixed_per_invoice')
    profit_value = Column(Float, default=0.0)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    networks = relationship("Network", back_populates="owner", cascade="all, delete-orphan")
    batches = relationship("VoucherBatch", back_populates="reseller", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("FinancialTransaction", foreign_keys="[FinancialTransaction.user_id]", back_populates="user", cascade="all, delete-orphan")

class AdminNotification(Base):
    """
    جدول إشعارات الإدارة المركزية (لمتابعة المشتركين الجدد والترحيب بهم فوراً)
    """
    __tablename__ = 'admin_notifications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    related_user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    user = relationship("User")

class Network(Base):
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    network_type = Column(String(20), nullable=False)
    ip_domain = Column(String(255), nullable=True)
    logo = Column(Text, nullable=True)
    client_settings = Column(Text, nullable=True)
    owner = relationship("User", back_populates="networks")
    routers = relationship("Router", back_populates="network", cascade="all, delete-orphan")

class Router(Base):
    __tablename__ = 'routers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    server_type = Column(String(50), nullable=False)
    nas_id = Column(String(100), unique=True, nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    api_user = Column(String(50), nullable=False)
    api_pass = Column(String(50), nullable=False)
    api_port = Column(Integer, default=8728)
    radius_secret = Column(String(100), nullable=False)
    coa_port = Column(Integer, default=3799)
    status = Column(String(20), default='offline')
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    ztp_token = Column(String(100), unique=True, nullable=True, index=True)
    is_provisioned = Column(Boolean, default=False)
    
    network = relationship("Network", back_populates="routers")
    batches = relationship("VoucherBatch", back_populates="router", cascade="all, delete-orphan")

class Offer(Base):
    __tablename__ = 'offers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    
    is_active = Column(Boolean, default=True)
    allow_resellers = Column(Boolean, default=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, default=0.0)
    speed_limit = Column(String(50))
    quota_gb = Column(Float, default=0.0)
    
    peak_time_enabled = Column(Boolean, default=False)
    peak_start = Column(String(10), nullable=True)
    peak_end = Column(String(10), nullable=True)
    peak_speed = Column(String(50), nullable=True)
    
    firewall_filter = Column(String(50), default='none')
    ip_pool = Column(String(100), default='ip_ppp')
    
    duration = Column(Integer, default=1)
    duration_type = Column(String(20), default='month')
    
    package_type = Column(String(20), default='full')
    daily_quota_gb = Column(Float, default=0.0)
    
    after_quota_action = Column(String(50), default='disconnect')
    after_quota_gb = Column(Float, default=0.0)
    after_quota_speed = Column(String(50), nullable=True)
    after_time_action = Column(String(50), default='disconnect')
    
    grace_period_action = Column(String(50), default='stop')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    subscribers = relationship("Subscriber", back_populates="offer")

class Subscriber(Base):
    """
    جدول المشتركين النهائيين (يوزر الواي فاي): 
    ليس لهم دخول على البوابة الرئيسية، ومحكومين بشبكة المالك الأصلي.
    """
    __tablename__ = 'subscribers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    router_id = Column(Integer, ForeignKey('routers.id', ondelete="CASCADE"), nullable=True)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete="CASCADE"), nullable=False)
    offer_id = Column(Integer, ForeignKey('offers.id', ondelete="SET NULL"), nullable=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password = Column(String(64), nullable=False)
    mac_address = Column(String(17), index=True)
    status = Column(String(20), default='active')
    expiry_date = Column(DateTime, nullable=False)
    balance = Column(Float, default=0.0)
    sub_type = Column(String(20), default='home') # نوع اليوزر النهائي داخل الشبكة
    quota_total = Column(Float, default=0.0)
    quota_used = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    full_name = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    national_id = Column(String(50), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(String(255), nullable=True)
    speed = Column(String(20), default='30 Mbps')
    last_login = Column(DateTime, nullable=True)
    
    # ⚠️ [التحصيل الرقمي - Sub]: كود التحصيل الفرعي الذي يقرأه الـ Webhook لتجديد باقة المشترك
    billing_code = Column(String(50), unique=True, nullable=True, index=True)

    router = relationship("Router", backref="subscribers")
    offer = relationship("Offer", back_populates="subscribers")

class ActiveSession(Base):
    __tablename__ = 'active_sessions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), index=True, nullable=False)
    type = Column(String(20), default='pppoe')
    mac_address = Column(String(17), nullable=True)
    ip_address = Column(String(45), nullable=True)
    router_id = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)

class CardTemplate(Base):
    __tablename__ = 'card_templates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    quota_gb = Column(Float, default=0.0)
    speed_limit = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    network = relationship("Network", backref="card_templates")

class VoucherBatch(Base):
    __tablename__ = 'voucher_batches'
    id = Column(Integer, primary_key=True, autoincrement=True)
    router_id = Column(Integer, ForeignKey('routers.id', ondelete="CASCADE"), nullable=False)
    reseller_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    price = Column(Float, default=0.0)
    count = Column(Integer, default=0)
    login_type = Column(String(50), default='user_pass')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    router = relationship("Router", back_populates="batches")
    reseller = relationship("User", back_populates="batches")
    vouchers = relationship("Voucher", back_populates="batch", cascade="all, delete-orphan")

    @property
    def network(self):
        return self.router.network if self.router else None

class Voucher(Base):
    __tablename__ = 'vouchers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey('voucher_batches.id', ondelete="CASCADE"), nullable=True)
    router_id = Column(Integer, ForeignKey('routers.id', ondelete="SET NULL"), nullable=True)
    reseller_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete="CASCADE"), nullable=False)
    code = Column(String(32), nullable=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password = Column(String(64), nullable=True)
    price = Column(Float, default=0.0)
    duration_minutes = Column(Integer, default=0)
    quota_mb = Column(Integer, default=0)
    status = Column(String(20), default='unused')
    used_by_mac = Column(String(17), nullable=True, index=True)
    qr_text = Column(Text, nullable=True)
    
    sold_to_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    sold_at = Column(DateTime, nullable=True)
    is_instant = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    batch = relationship("VoucherBatch", back_populates="vouchers")
    router = relationship("Router")
    reseller = relationship("User", foreign_keys=[reseller_id])
    sold_to = relationship("User", foreign_keys=[sold_to_id])

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), index=True)
    action = Column(String(50))
    mac_address = Column(String(17), index=True)
    device_info = Column(String(255))
    ap_location = Column(String(100))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    download_bytes = Column(BigInteger, default=0)
    upload_bytes = Column(BigInteger, default=0)

class Announcement(Base):
    __tablename__ = 'announcements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    type = Column(String(20))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class BroadcastMessage(Base):
    __tablename__ = 'broadcast_messages'
    id = Column(Integer, primary_key=True, autoincrement=True)
    message = Column(Text, nullable=False)
    target_sector = Column(String(50), default='all')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class CafeMenu(Base):
    __tablename__ = 'cafe_menu'
    id = Column(Integer, primary_key=True, autoincrement=True)
    network_id = Column(Integer, ForeignKey('networks.id', ondelete="CASCADE"), nullable=False)
    item_name = Column(String(100), nullable=False)
    price = Column(Integer, nullable=False)
    image_path = Column(String(255))

class TemplateSetting(Base):
    __tablename__ = 'template_settings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    brand_name = Column(String(100), default='Sakr Connect')
    primary_color = Column(String(7), default='#2563eb')
    template_name = Column(String(50), default='default')
    logo_path = Column(String(255), nullable=True)
    portal_url = Column(String(100), default='10.0.0.3')

class Ticket(Base):
    __tablename__ = 'tickets'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False, index=True)
    user_type = Column(String(50), nullable=False)
    subject = Column(String(255), nullable=False)
    priority = Column(String(50), default='normal')
    status = Column(String(50), default='open')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user = relationship("User", back_populates="tickets")
    replies = relationship("TicketReply", back_populates="ticket", cascade="all, delete-orphan")

class TicketReply(Base):
    __tablename__ = 'ticket_replies'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey('tickets.id', ondelete="CASCADE"), nullable=False)
    sender_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    ticket = relationship("Ticket", back_populates="replies")

class FinancialTransaction(Base):
    __tablename__ = 'financial_transactions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(20), nullable=False, index=True) 
    transaction_type = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    package_name = Column(String(100))
    payment_status = Column(String(20), default='paid')
    payment_method = Column(String(50), nullable=True)
    transaction_ref = Column(String(100), nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    
    target_wallet_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"), nullable=True)
    
    user = relationship("User", foreign_keys=[user_id], back_populates="transactions")

class SystemSettings(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    system_name = Column(String(200), default="Sakr Connect")
    primary_color = Column(String(50), default="#3b82f6")
    logo_path = Column(String(500))
    portal_url = Column(String(100), default='10.0.0.3')
    radius_auth_port = Column(Integer, default=1812)
    radius_acct_port = Column(Integer, default=1813)
    radius_secret = Column(String(255))
    maintenance_mode = Column(Boolean, default=False)
    ip_whitelist = Column(Text)
    failed_login_limit = Column(Integer, default=5)
    cron_auto_suspend = Column(Boolean, default=False)
    mac_policy = Column(Integer, default=1)
    max_devices_per_card = Column(Integer, default=1)
    lock_first_mac = Column(Boolean, default=True)
    roaming_enabled = Column(Boolean, default=False)
    vpn_server_address = Column(String(255))
    vpn_api_username = Column(String(255))
    vpn_api_password = Column(String(255))
    system_currency = Column(String(10), default='EGP')
    redirect_title = Column(String(200), default="تنبيه انتهاء الباقة")
    redirect_headline = Column(String(200), default="عذراً.. انتهت باقتك بالكامل")
    redirect_msg = Column(Text)
    redirect_logo_path = Column(String(500))
    redirect_bg_path = Column(String(500))
    redirect_stop_icon_path = Column(String(500))
    redirect_color_bg = Column(String(7), default="#ef4444")
    redirect_color_text = Column(String(7), default="#ffffff")
    alert_days = Column(Integer, default=3)
    alert_level = Column(String(20), default="warning")

class SystemAdmin(Base):
    __tablename__ = "system_admins"
    id = Column(Integer, primary_key=True, autoincrement=True)
    fullname = Column(String(200))
    username = Column(String(100), unique=True)
    password_hash = Column(Text)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    last_ip = Column(String(100))
    
    api_token = Column(String(255), unique=True, nullable=True, index=True)
    
    can_finance = Column(Boolean, default=False)
    can_routers = Column(Boolean, default=False)
    can_users = Column(Boolean, default=False)
    can_settings = Column(Boolean, default=False)
    can_logs = Column(Boolean, default=False)
    can_backup = Column(Boolean, default=False)
    can_whatsapp = Column(Boolean, default=False)
    can_email = Column(Boolean, default=False)

class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_name = Column(String(100))
    action = Column(Text)
    ip_address = Column(String(100))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class PendingInvoice(Base):
    """
    جدول إدارة الفواتير الرقمية والويب هوك.
    يستقبل كود التحصيل (لعميل أساسي أو مشترك فرعي) لتأكيد الدفع أوتوماتيكياً.
    """
    __tablename__ = 'pending_invoices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"), nullable=False, index=True)
    
    # ⚠️ [الربط الشامل بالويب هوك]: كود التحصيل الذي تم الدفع عليه (سواء كان User أو Subscriber)
    payer_billing_code = Column(String(50), nullable=False, index=True)
    
    subscriber_username = Column(String(64), nullable=True, index=True) # يبقى كمرجع إضافي إذا كان الدفع لـ Subscriber
    
    amount = Column(Float, nullable=False, default=0.0, index=True)
    sender_phone = Column(String(20), nullable=False, index=True)
    
    # ⚠️ حالات الدفع المعتمدة في الويب هوك
    status = Column(String(20), default='pending', nullable=False, index=True) # 'pending', 'paid', 'expired', 'failed'
    
    offer_id = Column(Integer, ForeignKey('offers.id', ondelete="SET NULL"), nullable=True)
    card_template_id = Column(Integer, ForeignKey('card_templates.id', ondelete="SET NULL"), nullable=True)
    is_instant = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", backref=backref("pending_invoices", cascade="all, delete-orphan"))
    offer = relationship("Offer")
    card_template = relationship("CardTemplate")

    def __repr__(self):
        return f"<PendingInvoice ID: {self.id} | BillingCode: {self.payer_billing_code} | Amt: {self.amount} | Status: {self.status}>"


class LineUsageBaseline(Base):
    """
    نقطة انطلاق عدادات كروت الـ WAN (خط الدمج).
    العدادات في المايكروتيك تراكمية منذ آخر ضبط (reset)، فبنمسك "صفر اليوم"
    و"صفر الشهر" عشان نحسب الاستهلاك الفعلي بالجيجا.
    """
    __tablename__ = 'line_usage_baselines'
    id = Column(Integer, primary_key=True, autoincrement=True)
    router_id = Column(Integer, index=True, nullable=False)
    iface = Column(String(100), index=True, nullable=False)
    day = Column(String(10), index=True, nullable=False)   # YYYY-MM-DD
    rx0 = Column(BigInteger, default=0)
    tx0 = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<LineUsageBaseline {self.iface}@R{self.router_id} {self.day}>"