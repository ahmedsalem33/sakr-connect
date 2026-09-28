# ==============================================================================
# SAKR CONNECT - CLIENT SETTINGS LOGIC (LIVE / PRODUCTION FULL REWRITE)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: مسجلة باسم مشروع صقر كونكت (Sakr Connect)
# الدعم الفني: 01033379719 - 01033379719
# العنوان: 
# صفحة المطور الشخصية: https://www.facebook.com/ahmedsalemJournalist
# صفحة الوكالة: https://www.facebook.com/sakrmediaagency
# ==============================================================================

import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import sessionmaker

from core.db_manager import engine
from database.models import User, TemplateSetting, Router, FinancialTransaction, Subscriber, Offer, SaasPackage, PendingInvoice, AuditLog, Network

client_settings_bp = Blueprint('client_settings', __name__)

UPLOAD_FOLDER = os.path.join('public', 'uploads', 'logos')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==============================================================================
# 1. إعدادات النظام للعميل (صاحب الشبكة)
# ==============================================================================
@client_settings_bp.route('/admin/settings', methods=['GET', 'POST'])
def settings_page():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']
    role = session.get('role', 'network')

    Session = sessionmaker(bind=engine)
    db_session = Session()

    try:
        user = db_session.query(User).filter_by(id=user_id).first()
        settings = db_session.query(TemplateSetting).filter_by(user_id=user_id).first()
        
        if not settings:
            brand_name_default = user.fullname if user else 'مدير النظام'
            settings = TemplateSetting(user_id=user_id, brand_name=brand_name_default, portal_url='')
            db_session.add(settings)
            db_session.commit()

        current_router = db_session.query(Router).join(Router.network).filter(Router.network.has(owner_id=user_id)).first()
        server_type = current_router.server_type if current_router else ('كافيهات' if role == 'cafe' else 'شبكات')

        if request.method == 'POST':
            settings.brand_name = request.form.get('brand_name', settings.brand_name)
            settings.portal_url = request.form.get('portal_url', settings.portal_url)

            new_password = request.form.get('new_password')
            if new_password and new_password.strip() != "":
                if user:
                    user.password_hash = generate_password_hash(new_password)

            if 'logo_file' in request.files:
                file = request.files['logo_file']
                if file and file.filename != '' and allowed_file(file.filename):
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    
                    filename = secure_filename(f"user_{user_id}_{file.filename}")
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)
                    
                    settings.logo_path = f"uploads/logos/{filename}"

            db_session.commit()
            flash('تم حفظ الإعدادات بنجاح', 'success')
            return redirect(url_for('client_settings.settings_page'))

        return render_template('client_settings.html', 
                               server_type=server_type, 
                               settings=settings, 
                               user=user)

    except Exception as e:
        db_session.rollback()
        return f"<div style='text-align:center; margin-top:50px; font-family:tahoma;'><h2 style='color:red;'>🚨 تم اصطياد الخطأ:</h2><h3 style='color:blue;' dir='ltr'>{str(e)}</h3></div>"
    finally:
        db_session.close()

# ==============================================================================
# 2. حسابات صقر كونكت (الفواتير والمهلة والترميز المالي للأنظمة والفروع التابعة)
# ==============================================================================
@client_settings_bp.route('/client/account', methods=['GET'])
def client_account():
    if 'user_id' not in session:
        return redirect(url_for('auth.login')) 

    user_id = session['user_id']
    
    Session = sessionmaker(bind=engine)
    db_session = Session()

    is_locked = False 
    now_time = datetime.utcnow()

    try:
        user = db_session.query(User).filter_by(id=user_id).first()
        if not user:
            abort(404)

        if user.role in ['network', 'cafe', 'company', 'reseller', 'sub_client']:
            
            if not user.billing_code:
                prefix_map = {
                    'network': 'NET-', 
                    'cafe': 'CAF-', 
                    'company': 'COM-',
                    'reseller': 'RES-',   
                    'sub_client': 'SUB-'  
                }
                prefix = prefix_map.get(user.role, 'SYS-')
                user.billing_code = f"{prefix}{10000 + user.id}"
                db_session.commit()

            if user.account_status == 'grace_period':
                if not user.grace_period_end:
                    user.grace_period_end = now_time + timedelta(hours=48)
                    db_session.commit()
                
                if now_time > user.grace_period_end:
                    user.account_status = 'suspended'
                    db_session.commit()
                    is_locked = True
                else:
                    time_left = user.grace_period_end - now_time
                    hours_left = int(time_left.total_seconds() // 3600)
                    if hours_left > 0:
                        flash(f'⚠️ تنبيه فترة السماح: متبقي {hours_left} ساعة على انتهاء المهلة التجريبية للنظام المعتمد. يرجى سداد الفاتورة المستحقة لتفادي توقف الخدمة عن المشتركين.', 'warning')

            elif user.account_status == 'suspended':
                is_locked = True
            
            if user.saas_expiry_date and now_time > user.saas_expiry_date:
                is_locked = True

            pkg_model = db_session.query(SaasPackage).filter_by(id=user.package_id).first()
            
            actual_used_clients = db_session.query(Subscriber).join(Router, Subscriber.router_id == Router.id, isouter=True).join(Network, Subscriber.network_id == Network.id).filter(Network.owner_id == user.id).count()
            
            expiry_str = user.saas_expiry_date.strftime('%Y-%m-%d') if user.saas_expiry_date else (user.grace_period_end.strftime('%Y-%m-%d %H:%M') if user.grace_period_end else 'غير محدد')
            duration_days = getattr(pkg_model, 'duration_months', 1) * 30 if pkg_model else 30
            
            if user.saas_expiry_date:
                invoice_start_dt = user.saas_expiry_date - timedelta(days=duration_days)
                invoice_start_str = invoice_start_dt.strftime('%Y-%m-%d')
            else:
                if user.grace_period_end:
                    invoice_start_dt = user.grace_period_end - timedelta(hours=48)
                    invoice_start_str = invoice_start_dt.strftime('%Y-%m-%d')
                else:
                    invoice_start_str = now_time.strftime('%Y-%m-%d')

            billing = {
                'collect_code': user.billing_code,
                'balance': user.current_balance,
                'debts': user.debt, 
                'expiry_date': expiry_str,
                'invoice_start': invoice_start_str,
                'invoice_end': expiry_str,
                'duration_days': duration_days,
                'extra_fees': 0,
                'total_invoice': pkg_model.price if pkg_model else 0.0
            }
            
            package_display_name = pkg_model.name if pkg_model else ('لوحة السيطرة المركزية (نظام شبكات)' if user.role == 'network' else 'فترة تجريبية (لم يتم تحديد باقة)')
            max_clients_limit = pkg_model.max_subscribers if pkg_model else getattr(user, 'max_subscribers', 0)
            
            saas_package_info = {
                'name': package_display_name,
                'price': pkg_model.price if pkg_model else 0.0,
                'max_routers': getattr(pkg_model, 'max_servers', 0) if pkg_model and getattr(pkg_model, 'max_servers', 0) > 0 else 999999,
                'max_clients': max_clients_limit,
                'used_clients': actual_used_clients
            }
        
        else:
            abort(403)

        transfers = db_session.query(FinancialTransaction).filter_by(user_id=user.id).order_by(FinancialTransaction.created_at.desc()).all()

        return render_template('sakr_account.html', 
                               billing=billing, 
                               saas_package=saas_package_info, 
                               transfers=transfers, 
                               is_locked=is_locked)

    except Exception as e:
        db_session.rollback()
        return f"<div style='text-align:center; margin-top:50px; font-family:tahoma;'><h2 style='color:red;'>🚨 خطأ في تحميل الصفحة:</h2><h3 style='color:blue;' dir='ltr'>{str(e)}</h3></div>"
    finally:
        db_session.close()

# ==============================================================================
# 3. إدارة العروض والباقات لشبكة العميل
# ==============================================================================
@client_settings_bp.route('/manage/offers', methods=['GET', 'POST'])
def manage_offers():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
        
    current_user_id = session.get('user_id')
    Session = sessionmaker(bind=engine)
    db_session = Session()

    try:
        if request.method == 'POST':
            is_active = True if request.form.get('is_active') == 'on' else False
            allow_resellers = True if request.form.get('allow_resellers') == 'on' else False
            
            name = request.form.get('name')
            price = request.form.get('price', 0.0, type=float)
            speed_limit = request.form.get('speed_custom', '').strip() or request.form.get('speed', '')
            quota_limit = request.form.get('quota_limit', 0.0, type=float)
            quota_unit = request.form.get('quota_unit', 'GB')
            quota_gb = quota_limit if quota_unit == 'GB' else (quota_limit / 1024.0)
            
            peak_time_enabled = True if request.form.get('peak_time_enabled') == 'on' else False
            peak_start = request.form.get('peak_start')
            peak_end = request.form.get('peak_end')
            peak_speed = request.form.get('peak_speed')
            
            firewall_filter = request.form.get('firewall_filter', 'none')
            ip_pool = request.form.get('ip_pool', 'ip_ppp')
            duration = request.form.get('duration', 1, type=int)
            duration_type = request.form.get('duration_type', 'month')
            package_type = request.form.get('package_type', 'full')
            daily_quota = request.form.get('daily_quota', 0.0, type=float)
            after_quota_action = request.form.get('after_quota_action', 'disconnect')
            after_quota_gb = request.form.get('after_quota_gb', 0.0, type=float)
            after_quota_speed = request.form.get('after_quota_speed')
            after_time_action = request.form.get('after_time_action', 'disconnect')
            grace_period_action = request.form.get('grace_period_action', 'stop')

            if not name:
                flash('⚠️ يرجى إدخل اسم العرض أولاً قبل الحفظ.', 'danger')
                return redirect(url_for('client_settings.manage_offers'))

            new_offer = Offer(
                user_id=current_user_id, is_active=is_active, allow_resellers=allow_resellers,
                name=name, price=price, speed_limit=speed_limit, quota_gb=quota_gb,
                peak_time_enabled=peak_time_enabled, peak_start=peak_start, peak_end=peak_end,
                peak_speed=peak_speed, firewall_filter=firewall_filter, ip_pool=ip_pool,
                duration=duration, duration_type=duration_type, package_type=package_type,
                daily_quota_gb=daily_quota, after_quota_action=after_quota_action,
                after_quota_gb=after_quota_gb, after_quota_speed=after_quota_speed,
                after_time_action=after_time_action, grace_period_action=grace_period_action
            )
            db_session.add(new_offer)
            db_session.commit()
            flash('✅ تم حفظ العرض بكل تفاصيله بنجاح.', 'success')
            return redirect(url_for('client_settings.manage_offers'))

        offers_list = db_session.query(Offer).filter_by(user_id=current_user_id).all()
        return render_template('offers.html', offers=offers_list, page_title="إدارة باقات وعروض الشبكة")

    except Exception as e:
        db_session.rollback()
        flash('❌ حدث خطأ داخلي أثناء تحميل أو معالجة قاعدة البيانات.', 'danger')
        return render_template('offers.html', offers=[], page_title="إدارة باقات وعروض الشبكة")
    finally:
        db_session.close()

# ==============================================================================
# 4. إدارة فريق الشبكة (موزعين ومديرين مساعدين) - خاص بصاحب الشبكة فقط
# ==============================================================================
@client_settings_bp.route('/network/team', methods=['GET'])
def network_team_view():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    if session.get('role') not in ['network', 'cafe']: 
        abort(403)
        
    user_id = session['user_id']
    Session = sessionmaker(bind=engine)
    db_session = Session()
    
    try:
        resellers = db_session.query(User).filter_by(role='reseller', parent_id=user_id).all()
        managers = db_session.query(User).filter_by(role='manager', parent_id=user_id).all()
        
        networks = db_session.query(Network).filter_by(owner_id=user_id).all()
        user_networks = [net.id for net in networks]
        routers = db_session.query(Router).filter(Router.network_id.in_(user_networks), Router.is_deleted == False).all()
        
        return render_template('admin_managers.html', resellers=resellers, managers=managers, routers=routers)
    except Exception as e:
        db_session.rollback()
        return f"<div style='text-align:center; margin-top:50px; font-family:tahoma;'><h2 style='color:red;'>🚨 خطأ في تحميل إدارة الفريق:</h2><h3 style='color:blue;' dir='ltr'>{str(e)}</h3></div>"
    finally:
        db_session.close()

@client_settings_bp.route('/network/team/add-reseller', methods=['POST'])
def add_network_reseller():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    if session.get('role') not in ['network', 'cafe']: 
        abort(403)
        
    user_id = session['user_id']
    Session = sessionmaker(bind=engine)
    db_session = Session()
    
    try:
        username = request.form.get('username')
        existing = db_session.query(User).filter_by(username=username).first()
        if existing:
            flash('⚠️ اسم المستخدم للموزع مسجل مسبقاً في النظام.', 'error')
            return redirect(url_for('client_settings.network_team_view'))
            
        # صلاحيات الموزع يحددها صاحب الشبكة - كلها في ايده
        perms_raw = request.form.getlist('permissions[]')
        perms = {}
        for p in perms_raw:
            perms[p] = True
        # تحويل app_access لـ perm_app_access للتوافق مع app_routes - لو مش محدد يبقى False (صاحب الشبكة قرر)
        perms['perm_app_access'] = 'app_access' in perms_raw
        if 'app_access' in perms:
            perms.pop('app_access', None)
        # can_manage_subscribers مشتق من add/edit
        perms['can_manage_subscribers'] = any(k in perms_raw for k in ['add_subscriber','edit_subscriber','delete_subscriber','change_plan'])
        # السيرفرات المسموحة + الكوتا
        allowed_routers = request.form.getlist('allowed_routers[]')
        if allowed_routers:
            perms['allowed_routers'] = [int(x) for x in allowed_routers if x.isdigit()]
        # كوتا
        try:
            max_subs = int(request.form.get('max_subscribers', 0) or 0)
            max_vou = int(request.form.get('max_vouchers', 0) or 0)
        except: max_subs, max_vou = 0, 0

        new_reseller = User(
            fullname=request.form.get('fullname'),
            username=username,
            password_hash=generate_password_hash(request.form.get('password')),
            phone1=request.form.get('phone1'),
            role='reseller',
            parent_id=user_id,
            is_active=True,
            profit_type=request.form.get('profit_type'),
            profit_value=float(request.form.get('profit_value', 0) or 0),
            discount_rate=float(request.form.get('discount_rate', 0) or 0),
            current_balance=float(request.form.get('auto_balance', 0) or 0),
            permissions=perms if perms else None,
            max_subscribers=max_subs,
            max_vouchers=max_vou
        )
        
        db_session.add(new_reseller)
        db_session.commit()
        flash('✅ تم إضافة الموزع للشبكة بنجاح.', 'success')
        return redirect(url_for('client_settings.network_team_view'))
    except Exception as e:
        db_session.rollback()
        flash(f'❌ حدث خطأ أثناء إضافة الموزع: {str(e)}', 'danger')
        return redirect(url_for('client_settings.network_team_view'))
    finally:
        db_session.close()

@client_settings_bp.route('/network/team/add-manager', methods=['POST'])
def add_network_manager():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    if session.get('role') not in ['network', 'cafe']: 
        abort(403)
        
    user_id = session['user_id']
    Session = sessionmaker(bind=engine)
    db_session = Session()
    
    try:
        username = request.form.get('username')
        existing = db_session.query(User).filter_by(username=username).first()
        if existing:
            flash('⚠️ اسم المستخدم للمدير مسجل مسبقاً.', 'error')
            return redirect(url_for('client_settings.network_team_view'))
            
        # صلاحيات المدير يحددها صاحب الشبكة - كل حاجة في ايده
        mgr_perms = {}
        # checkboxes: perm_admin_finance, perm_admin_settings, perm_admin_resellers, perm_admin_managers, perm_admin_servers, perm_admin_packages, perm_admin_support, perm_admin_logs
        for key in ['perm_admin_finance','perm_admin_settings','perm_admin_resellers','perm_admin_managers','perm_admin_servers','perm_admin_packages','perm_admin_support','perm_admin_logs']:
            if key in request.form:
                mgr_perms[key] = True
            else:
                mgr_perms[key] = False
        # perm_app_access للمدير أيضاً
        mgr_perms['perm_app_access'] = True

        new_manager = User(
            fullname=request.form.get('fullname'),
            username=username,
            email=request.form.get('email'),
            password_hash=generate_password_hash(request.form.get('password')),
            phone1=request.form.get('phone1'),
            phone2=request.form.get('phone2'),
            role='manager',
            parent_id=user_id,
            is_active='is_active' in request.form,
            permissions=mgr_perms
        )
        
        db_session.add(new_manager)
        db_session.commit()
        flash('✅ تم إضافة المدير المساعد للشبكة بنجاح.', 'success')
        return redirect(url_for('client_settings.network_team_view'))
    except Exception as e:
        db_session.rollback()
        flash(f'❌ حدث خطأ أثناء إضافة المدير: {str(e)}', 'danger')
        return redirect(url_for('client_settings.network_team_view'))
    finally:
        db_session.close()