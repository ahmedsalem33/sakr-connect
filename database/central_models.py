# ==============================================================================
# SAKR CONNECT - CENTRAL MANAGEMENT MODELS (SAAS & SYSTEM CONTROL)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# الدعم الفني: 01033379719 - 01033379719
# المطور المسؤول: أحمد سالم الملواني
# ==============================================================================

import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from core.db_manager import Base

class GlobalSetting(Base):
    """
    جدول الإعدادات العامة والمركزية للنظام والتطبيق.
    يتحكم ديناميكياً في: أسماء المحافظ المسموحة، رقم نسخة التطبيق الحالية، 
    رابط التحميل المباشر للتحديثات، وحالة النظام العامة، وعمولة المنصة.
    """
    __tablename__ = 'global_settings'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    setting_key = Column(String(100), unique=True, nullable=False, index=True) 
    # مثال: 'app_version', 'app_download_url', 'system_commission_config', 'paypal_production_config'
    setting_value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<GlobalSetting {self.setting_key}={self.setting_value}>"


class SubscriptionTier(Base):
    """
    جدول شرائح الأسعار لإدارة اشتراكات أصحاب الشبكات (الموزعين).
    يحدد تكلفة تشغيل السيستم بناءً على حجم الشبكة (عدد المستخدمين).
    """
    __tablename__ = 'subscription_tiers'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tier_name = Column(String(100), nullable=False)        # مثال: الشريحة البرونزية، الشريحة الذهبية
    min_users = Column(Integer, nullable=False, default=1)  # الحد الأدنى للمشتركين
    max_users = Column(Integer, nullable=False, default=100) # الحد الأقصى للمشتركين
    monthly_price = Column(Float, nullable=False, default=0.0) # سعر الاشتراك الشهري لصاحب الشبكة
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    clients = relationship("NetworkClient", back_populates="current_tier")


class AgencyWallet(Base):
    """
    جدول محافظ الوكالة الرسمية (صقر ميديا).
    تستخدم لاستقبل أموال الاشتراكات والإيجارات الشهرية من أصحاب الشبكات والعملاء مباشرة.
    """
    __tablename__ = 'agency_wallets'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_number = Column(String(20), nullable=False, unique=True, index=True)
    provider_name = Column(String(50), nullable=False, default='Vodafone Cash') # فودافون كاش، إنستا باي، باي بال
    is_active = Column(Boolean, default=True)
    grace_period_days = Column(Integer, default=3) # فترة السماح للموزع بعد انتهاء اشتراكه وقبل الإيقاف
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class NetworkClient(Base):
    """
    جدول عملاء الشبكات والكافيهات والمنازل (أصحاب السيرفرات والموزعين المشتركين مع الوكالة).
    يربط ترخيص النظام برقم الـ Device ID الخاص بتطبيق الأندرويد، 
    ويراقب تواريخ الصلاحية، نوع النظام، العمولات المستحقة، وإعدادات العميل المستقلة.
    """
    __tablename__ = 'network_clients'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_name = Column(String(150), nullable=False)                  # اسم صاحب الخدمة
    ip_domain = Column(String(100), unique=True, nullable=False)       # رابط أو آي بي السيرفر الخاص به
    app_device_id = Column(String(150), unique=True, nullable=True, index=True) # معرّف هاتف الأندرويد لربط الـ Listener
    
    # تصنيف نوع العميل (منزلي، كافيه، شبكات وموزعين)
    client_type = Column(String(20), nullable=False, default='network') # 'home', 'cafe', 'network'
    
    # الحساب المالي التراكمي للعمولات المستحقة للوكالة من عمليات الدفع الآلي
    accumulated_commission = Column(Float, nullable=False, default=0.0)
    
    # إعدادات مخصصة وديناميكية لكل عميل (تُخزن كـ JSON Text لأسماء الشبكات، محافظ كاش الخاصة بهم، إلخ)
    client_settings = Column(Text, nullable=True, default='{}')
    
    # ربط بالشريحة السعرية
    current_tier_id = Column(Integer, ForeignKey('subscription_tiers.id', ondelete="SET NULL"), nullable=True)
    current_tier = relationship("SubscriptionTier", back_populates="clients")
    
    # التحكم الزمني والمالي للترخيص
    subscription_start_date = Column(DateTime, nullable=True)
    subscription_end_date = Column(DateTime, nullable=True)
    is_auto_payment_active = Column(Boolean, default=False) # هل العميل مفعّل ميزة الدفع الآلي لمشتركينه؟
    status = Column(String(20), default='active')           # active, suspended, grace_period
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # --- الحقول الجديدة للتحكم الكامل في التطبيق والنسب (God Mode) ---
    app_visible = Column(Boolean, default=True) # تفعيل أو إخفاء زر تحميل التطبيق لعملاء هذه الشبكة
    commission_mode = Column(String(20), default='global') # وضع العمولة: 'global' النظام العام، 'custom' مخصصة، 'disabled' معطلة
    custom_commission_rate = Column(Float, default=0.0) # قيمة النسبة المخصصة للشبكة (تُستخدم إذا كان الوضع custom)

    def __repr__(self):
        return f"<NetworkClient {self.client_name} - Type: {self.client_type} - Status: {self.status}>"