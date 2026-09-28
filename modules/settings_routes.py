# ==============================================================================
# SAKR CONNECT - SETTINGS ROUTES (GOD MODE & CENTRAL ADMIN ONLY)
# حقوق النشر: تُسجل باسم مشروع Sakr Connect
# حقوق المطور: Sakr Media Agency (صقر ميديا)
# الدعم الفني للمطور: 01033379719 - 01033379719
# العنوان: 
# صفحة المطور الشخصية: https://www.facebook.com/ahmedsalemJournalist
# صفحة الوكالة: https://www.facebook.com/sakrmediaagency
# ==============================================================================

import os
import json
from datetime import datetime
import psutil
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, abort, send_file, current_app
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from core.db_manager import db_session

# تم إضافة AuditLog لمنع خطأ الـ 500 في صفحة السجلات الأمنية
from database.models import User, SystemSettings, SystemAdmin, FinancialTransaction, Network, CardTemplate, AuditLog
from database.central_models import GlobalSetting, NetworkClient

settings_bp = Blueprint('settings', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_to_global(key_name, data_dict):
    """دالة مساعدة لحفظ الإعدادات المركزية (God Mode) في الداتابيز للإدارة فقط"""
    setting = db_session.query(GlobalSetting).filter_by(setting_key=key_name).first()
    if not setting:
        setting = GlobalSetting(setting_key=key_name)
        db_session.add(setting)
    setting.setting_value = json.dumps(data_dict)
    db_session.commit()

# ==============================================================================
# 1. إعدادات الإدارة المركزية (God Mode) - مخصصة حصرياً لصقر ميديا
# ==============================================================================

@settings_bp.route('/global-settings', methods=['GET', 'POST'])
@settings_bp.route('/global-settings/update', endpoint='update_global_settings', methods=['POST'])
def global_settings_view():
    if 'user_id' not in session or session.get('role') not in ['admin', 'super_admin']:
        abort(403)
        
    settings = db_session.query(SystemSettings).first()
    if not settings:
        settings = SystemSettings(system_name="Sakr Connect")
        db_session.add(settings)
        db_session.commit()
        
    if request.method == 'POST':
        active_tab = request.form.get('active_tab', 'tab-dashboard')
        
        # تحديث البيانات الأساسية للهوية البصرية والسيستم
        settings.system_name = request.form.get('system_name', settings.system_name)
        settings.primary_color = request.form.get('primary_color', settings.primary_color)
        
        # إعدادات الحماية والأمان (الجدار الناري)
        settings.maintenance_mode = 'maintenance_mode' in request.form
        settings.ip_whitelist = request.form.get('ip_whitelist', '')
        
        # إعدادات الراديوس المركزية
        settings.radius_auth_port = request.form.get('radius_auth_port', '1812')
        settings.radius_acct_port = request.form.get('radius_acct_port', '1813')
        settings.radius_secret = request.form.get('radius_secret', '')
        
        # المهام الآلية (Cron)
        settings.cron_auto_suspend = 'cron_auto_suspend' in request.form
        
        db_session.commit()
        flash('✅ تم حفظ الإعدادات المركزية بنجاح.', 'success')
        return redirect(url_for('settings.global_settings_view', active_tab=active_tab))

    try:
        cpu_usage = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        ram_used = round(ram.used / (1024 ** 3), 1)
        ram_total = round(ram.total / (1024 ** 3), 1)
    except:
        cpu_usage, ram_used, ram_total = 0, 0, 0
        
    # جلب عدد المسؤولين والموزعين النشطين للمنظومة ككل
    admin_staff = db_session.query(SystemAdmin).all()
    active_resellers_count = db_session.query(User).filter_by(role='reseller', is_active=True).count()
    active_tab = request.args.get('active_tab', 'tab-dashboard')
    
    return render_template('global_settings.html', 
                           settings=settings, 
                           admin_staff=admin_staff, 
                           active_tab=active_tab, 
                           cpu_usage=cpu_usage, 
                           ram_used=ram_used, 
                           ram_total=ram_total,
                           active_resellers_count=active_resellers_count)

# ==============================================================================
# 2. مسارات بوابات الدفع المركزية وعمولات النظام (God Mode)
# ==============================================================================

@settings_bp.route('/settings/payment-gateways', methods=['GET'])
def payment_gateways_view():
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    
    payment_setting = db_session.query(GlobalSetting).filter_by(setting_key='payment_gateway_config').first()
    payment_config = json.loads(payment_setting.setting_value) if payment_setting and payment_setting.setting_value else {}

    app_setting = db_session.query(GlobalSetting).filter_by(setting_key='app_branding_config').first()
    app_config = json.loads(app_setting.setting_value) if app_setting and app_setting.setting_value else {}
    
    commission_setting = db_session.query(GlobalSetting).filter_by(setting_key='system_commission_config').first()
    commission_config = json.loads(commission_setting.setting_value) if commission_setting and commission_setting.setting_value else {}
    
    paypal_setting = db_session.query(GlobalSetting).filter_by(setting_key='paypal_production_config').first()
    paypal_config = json.loads(paypal_setting.setting_value) if paypal_setting and paypal_setting.setting_value else {}

    return render_template('payment_gateways.html', payment_config=payment_config, app_config=app_config, commission_config=commission_config, paypal_config=paypal_config)

@settings_bp.route('/settings/dynamic/save', methods=['POST'])
def save_dynamic_settings():
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
        
    payment_config = {
        'wallet_active': 'wallet_active' in request.form,
        'wallet_number': request.form.get('wallet_number', ''),
        'webhook_secret': request.form.get('webhook_secret', ''),
        'instapay_active': 'instapay_active' in request.form,
        'instapay_ipa': request.form.get('instapay_ipa', '')
    }
    
    app_config = {
        'app_name': request.form.get('app_name', 'Sakr Connect Pay'),
        'app_primary_color': request.form.get('app_primary_color', '#002366'), 
    }
    
    commission_config = {
        'type': request.form.get('commission_type', 'percentage'), 
        'value': float(request.form.get('commission_value', 0.0))
    }
    
    paypal_config = {
        'active': 'paypal_active' in request.form,
        'client_id': request.form.get('paypal_client_id', ''),
        'secret': request.form.get('paypal_secret', '')
    }
    
    save_to_global('payment_gateway_config', payment_config)
    save_to_global('app_branding_config', app_config)
    save_to_global('system_commission_config', commission_config)
    save_to_global('paypal_production_config', paypal_config)
    
    flash('✅ تم حفظ إعدادات الدفع والعمولات المركزية بنجاح.', 'success')
    return redirect(url_for('settings.payment_gateways_view'))

# ==============================================================================
# 3. إدارة المسؤولين والنسخ الاحتياطي (God Mode)
# ==============================================================================

@settings_bp.route('/settings/admin/add', methods=['POST'])
def add_new_manager():
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    fullname = request.form.get('fullname')
    username = request.form.get('username')
    password = request.form.get('password')
    
    existing = db_session.query(SystemAdmin).filter_by(username=username).first()
    if existing:
        flash('⚠️ اسم المستخدم مسجل مسبقاً.', 'error')
        return redirect(url_for('settings.global_settings_view', active_tab='rbac'))
        
    new_admin = SystemAdmin(fullname=fullname, username=username, password_hash=generate_password_hash(password), is_active=True)
    db_session.add(new_admin)
    db_session.commit()
    flash('✅ تمت إضافة المسؤول بنجاح.', 'success')
    return redirect(url_for('settings.global_settings_view', active_tab='rbac'))

@settings_bp.route('/settings/admin/update/<int:user_id>', methods=['POST'])
def update_admin_permissions(user_id):
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    admin = db_session.query(SystemAdmin).filter_by(id=user_id).first()
    if not admin: abort(404)
    
    # حماية الماستر أدمن من تعديل صلاحياته عن طريق الخطأ
    if admin.username == 'admin' and session.get('username') != 'admin':
        flash('⚠️ لا تملك صلاحية تعديل حساب الإدارة العليا (Master Admin)!', 'error')
        return redirect(url_for('settings.global_settings_view', active_tab='rbac'))

    if request.form.get('new_password'): 
        admin.password_hash = generate_password_hash(request.form.get('new_password'))
        
    admin.can_finance = 'can_finance' in request.form
    admin.can_routers = 'can_routers' in request.form
    admin.can_users = 'can_users' in request.form
    admin.can_settings = 'can_settings' in request.form
    admin.can_logs = 'can_logs' in request.form
    admin.can_backup = 'can_backup' in request.form
    db_session.commit()
    flash('✅ تم تحديث الصلاحيات بنجاح.', 'success')
    return redirect(url_for('settings.global_settings_view', active_tab='rbac'))

@settings_bp.route('/global-settings/delete-manager/<int:user_id>', methods=['POST'])
def delete_manager(user_id):
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    admin = db_session.query(SystemAdmin).filter_by(id=user_id).first()
    
    if admin:
        # حصانة برمجية تمنع حذف حساب الأدمن الأساسي نهائياً
        if admin.username == 'admin':
            flash('🛑 تحذير أمني: لا يمكن حذف حساب الإدارة المركزية الأساسي (Master Admin) بأي شكل!', 'error')
            return redirect(url_for('settings.global_settings_view', active_tab='rbac'))
            
        db_session.delete(admin)
        db_session.commit()
        flash('تم حذف حساب المسؤول بنجاح.', 'success')
    return redirect(url_for('settings.global_settings_view', active_tab='rbac'))

@settings_bp.route('/settings/backup/download', methods=['POST', 'GET'])
def download_backup():
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    db_path = 'sakr_connect.db' 
    if os.path.exists(db_path):
        return send_file(db_path, as_attachment=True, download_name=f"sakr_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
    flash('⚠️ ملف قاعدة البيانات غير موجود!', 'error')
    return redirect(url_for('settings.global_settings_view', active_tab='backup'))

@settings_bp.route('/settings/backup/restore', methods=['POST'])
def restore_backup():
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    file = request.files.get('backup_file')
    if file and file.filename.endswith('.db'):
        file.save('sakr_connect.db')
        flash('🔄 تم استعادة النسخة الاحتياطية بنجاح! يرجى إعادة تشغيل السيرفر فوراً.', 'success')
    return redirect(url_for('settings.global_settings_view', active_tab='backup'))

# ==============================================================================
# 4. التحكم المركزي في عملاء الشبكات والتطبيق (God Mode)
# ==============================================================================

@settings_bp.route('/settings/network-clients/update/<int:client_id>', methods=['POST'])
def update_network_client_god_mode(client_id):
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    
    client = db_session.query(NetworkClient).filter_by(id=client_id).first()
    if client:
        client.app_visible = 'app_visible' in request.form
        client.commission_mode = request.form.get('commission_mode', 'global')
        client.custom_commission_rate = float(request.form.get('custom_commission_rate', 0.0))
        
        db_session.commit()
        flash(f'✅ تم تحديث إعدادات التطبيق والعمولة للشبكة {client.client_name} بنجاح.', 'success')
        
    return redirect(url_for('settings.global_settings_view'))

# ==============================================================================
# [تكميلي]: كباري الربط لصفحات الإدارة واللوجات المركزية
# ==============================================================================

@settings_bp.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if 'user_id' not in session: abort(403)
    user = db_session.query(SystemAdmin).filter_by(id=session['user_id']).first()
    return render_template('admin_profile.html', user=user)

@settings_bp.route('/settings/general', methods=['GET'])
def global_settings_redirect():
    return redirect(url_for('settings.global_settings_view'))

@settings_bp.route('/security/logs', methods=['GET'])
def security_logs():
    if session.get('role') not in ['admin', 'super_admin']: abort(403)
    logs = db_session.query(AuditLog).order_by(AuditLog.id.desc()).limit(100).all()
    return render_template('security_logs.html', logs=logs)