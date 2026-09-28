# ==============================================================================
# SAKR CONNECT - VOUCHER & RADIUS ROUTES (ISOLATED MULTI-TENANT)
# حقوق المطور: Sakr Media Agency (صقر ميديا)
# حقوق النشر: مسجلة باسم مشروع صقر كونكت
# الدعم الفني للمطور: 01033379719 - 01033379719
# ==============================================================================

from flask import Blueprint, render_template, session, abort, request, jsonify
from database.models import Router, Voucher, VoucherBatch, Network, User
from core.db_manager import db_session
from core.vouchers.generator import VoucherGenerator
from datetime import datetime

vouchers_bp = Blueprint('vouchers', __name__)

# ==============================================================================
# 1. مسار إدارة وتوليد كروت الهوت سبوت (manage_vouchers.html)
# ==============================================================================
@vouchers_bp.route('/manage/vouchers', methods=['GET', 'POST'])
def manage_vouchers():
    # 1. جلب الصلاحية والمعرف من الجلسة لضمان العزل
    role = session.get('role')
    user_id = session.get('user_id') 
    
    # حظر أي وصول لحسابات المنازل
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        abort(403)
        
    # 2. معالجة طلبات الـ POST (التوليد، الفحص)
    if request.method == 'POST':
        req_data = request.json if request.is_json else request.form
        action = req_data.get('action')
        
        # أ. توليد الكروت (Bulk Generation) مع حماية الصلاحيات
        if action == 'generate':
            router_id = int(req_data.get('router_id'))
            
            # [تأمين صارم]: التأكد من أن الروتر المختار مملوك للعميل الحالي (إلا لو كان أدمن)
            if role not in ['super_admin', 'admin']:
                owns_router = db_session.query(Router).join(Network).filter(
                    Network.owner_id == user_id,
                    Router.id == router_id,
                    Router.is_deleted == False
                ).first()
                if not owns_router:
                    return jsonify({"status": "error", "message": "إجراء مرفوض: هذا الروتر غير تابع لشبكتك."}), 403

            quantity = int(req_data.get('count', 0))
            pkg_price = float(req_data.get('price', 0.0))
            duration = int(req_data.get('duration_minutes', 0))
            quota = int(req_data.get('quota_mb', 0))
            length = int(req_data.get('length', 8))
            login_type = req_data.get('login_type', 'pin_only') 
            name_prefix = req_data.get('name_prefix', '')
            use_letters = str(req_data.get('use_letters', 'true')).lower() == 'true'

            # استدعاء دالة الحقن المركزي
            success, result = VoucherGenerator.bulk_create_vouchers(
                router_id=router_id,
                reseller_id=user_id,
                count=quantity,
                price=pkg_price,
                duration_minutes=duration,
                quota_mb=quota,
                length=length,
                use_letters=use_letters,
                login_type=login_type,
                name_prefix=name_prefix
            )
            
            if success:
                return jsonify({
                    "status": "success", 
                    "message": f"تم توليد حزمة الكروت بنجاح (رقم الحزمة: {result['batch_id']}) وإدراجها ككروت غير مستخدمة."
                })
            else:
                return jsonify({
                    "status": "error", 
                    "message": f"فشل التوليد: {result}"
                })
                
        # ب. أداة الفحص (X-Ray PIN Check) مع العزل
        elif action == 'check_pin':
            pin = req_data.get('pin', '').strip()
            
            voucher = db_session.query(Voucher).filter(
                (Voucher.username == pin) | (Voucher.password == pin)
            ).first()
            
            if not voucher:
                return jsonify({"status": "error", "message": "هذا الكارت غير مسجل في النظام."})
            
            # [تأمين صارم]: منع موزع من رؤية تفاصيل كارت شبكة أخرى
            if role not in ['super_admin', 'admin']:
                batch = db_session.query(VoucherBatch).filter_by(id=voucher.batch_id).first()
                if not batch or batch.reseller_id != user_id:
                    return jsonify({"status": "error", "message": "غير مصرح لك باستعراض بيانات هذا الكارت."}), 403
            
            router_name = voucher.router.name if getattr(voucher, 'router', None) else "غير محدد"
            
            status_ar = {
                'unused': 'متاح للبيع',
                'sold': 'مباع (رصيد محصل)',
                'active': 'متصل الآن',
                'expired': 'منتهي الصلاحية',
                'suspended': 'موقوف'
            }.get(voucher.status, voucher.status)
            
            return jsonify({
                "status": "success",
                "data": {
                    "pin": voucher.username,
                    "status": status_ar,
                    "router": router_name,
                    "price": f"{voucher.price} EGP",
                    "package": f"صلاحية {voucher.duration_minutes} دقيقة",
                    "quota": f"{voucher.quota_mb} MB" if voucher.quota_mb > 0 else "غير محدود",
                    "mac": voucher.used_by_mac if voucher.used_by_mac else "لم يربط بعد",
                    "first_login": voucher.sold_at.strftime('%Y-%m-%d %H:%M') if getattr(voucher, 'sold_at', None) else "لم يستخدم",
                    "expiry": "محدد بالباقة" if voucher.duration_minutes > 0 else "مفتوح"
                }
            })

    # ==========================================
    # 3. سحب الحزم والكروت الفردية والإحصائيات وتوجيه الواجهة
    # ==========================================
    if role in ['super_admin', 'admin']:
        batches = db_session.query(VoucherBatch).order_by(VoucherBatch.created_at.desc()).all()
        total_generated = db_session.query(Voucher).count()
        total_unused = db_session.query(Voucher).filter_by(status='unused').count()
        network_routers = db_session.query(Router).all()
        
        # التعديل الأهم: سحب الكروت الفردية وتمريرها للجدول (آخر 500 كارت منعاً للتهنيج)
        vouchers = db_session.query(Voucher).order_by(Voucher.created_at.desc()).limit(500).all()
    else:
        batches = db_session.query(VoucherBatch).filter_by(reseller_id=user_id).order_by(VoucherBatch.created_at.desc()).all()
        total_generated = db_session.query(Voucher).join(VoucherBatch).filter(VoucherBatch.reseller_id == user_id).count()
        total_unused = db_session.query(Voucher).join(VoucherBatch).filter(VoucherBatch.reseller_id == user_id, Voucher.status.in_(['unused', 'sold'])).count()
        network_routers = db_session.query(Router).join(Network).filter(Network.owner_id == user_id).order_by(Router.name.asc()).all()
        
        # التعديل الأهم: سحب كروت الموزع الحالي فقط وتمريرها للجدول
        vouchers = db_session.query(Voucher).join(VoucherBatch).filter(VoucherBatch.reseller_id == user_id).order_by(Voucher.created_at.desc()).limit(500).all()

    total_used = total_generated - total_unused

    stats = {
        "generated": total_generated, 
        "unused": total_unused, 
        "used": total_used
    }

    return render_template(
        'manage_vouchers.html', 
        role=role, 
        batches=batches,
        stats=stats,
        routers=network_routers,
        vouchers=vouchers # تم التمرير بنجاح ليقرأها الجدول
    )

# ==============================================================================
# 2. [جديد] مسار التحكم الجراحي الفردي في الكروت (AJAX)
# ==============================================================================
@vouchers_bp.route('/api/voucher/action', methods=['POST'])
def voucher_action():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        return jsonify({"status": "error", "message": "غير مصرح لك"}), 403

    data = request.get_json()
    action = data.get('action')
    voucher_id = data.get('id')

    try:
        voucher = db_session.query(Voucher).filter_by(id=voucher_id).first()
        if not voucher:
            return jsonify({"status": "error", "message": "الكارت غير موجود"}), 404

        # التحقق من أن الكارت يتبع للموزع/الشبكة الطالبة للعملية
        if role not in ['super_admin', 'admin']:
            batch = db_session.query(VoucherBatch).filter_by(id=voucher.batch_id).first()
            if not batch or batch.reseller_id != user_id:
                return jsonify({"status": "error", "message": "غير مصرح لك بالتحكم في هذا الكارت"}), 403

        message = "تم تنفيذ الإجراء بنجاح."

        if action == 'delete':
            db_session.delete(voucher)
            message = "تم حذف الكارت نهائياً من النظام."
        elif action == 'suspend':
            voucher.status = 'suspended' if voucher.status != 'suspended' else 'active'
            message = "تم تغيير حالة الكارت (إيقاف/تفعيل)."
        elif action == 'clear_mac':
            voucher.used_by_mac = None
            message = "تم تصفير الماك أدريس المربوط بالكارت بنجاح."
        elif action == 'reset':
            voucher.status = 'unused'
            voucher.used_by_mac = None
            voucher.sold_at = None
            message = "تم إعادة تعيين الكارت ليصبح كارت جديد متاح للبيع."

        db_session.commit()
        return jsonify({"status": "success", "message": message})
    
    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================================================================
# SAKR CONNECT - VOUCHER & RADIUS ROUTES (ISOLATED MULTI-TENANT)
# حقوق المطور: Sakr Media Agency (صقر ميديا)
# حقوق النشر: مسجلة باسم مشروع صقر كونكت
# الدعم الفني للمطور: 01033379719 - 01033379719
# ==============================================================================

from flask import Blueprint, render_template, session, abort, request, jsonify, send_file
from database.models import Router, Voucher, VoucherBatch, Network, User
from core.db_manager import db_session
from core.vouchers.generator import VoucherGenerator
from datetime import datetime
import json
import os
import tempfile

vouchers_bp = Blueprint('vouchers', __name__)

# ==============================================================================
# 1. مسار إدارة وتوليد كروت الهوت سبوت (manage_vouchers.html)
# ==============================================================================
@vouchers_bp.route('/manage/vouchers', methods=['GET', 'POST'])
def manage_vouchers():
    # 1. جلب الصلاحية والمعرف من الجلسة لضمان العزل
    role = session.get('role')
    user_id = session.get('user_id') 
    
    # حظر أي وصول لحسابات المنازل
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        abort(403)
        
    # 2. معالجة طلبات الـ POST (التوليد، الفحص)
    if request.method == 'POST':
        req_data = request.json if request.is_json else request.form
        action = req_data.get('action')
        
        # أ. توليد الكروت (Bulk Generation) مع حماية الصلاحيات
        if action == 'generate':
            router_id = int(req_data.get('router_id'))
            
            # [تأمين صارم]: التأكد من أن الروتر المختار مملوك للعميل الحالي (إلا لو كان أدمن)
            if role not in ['super_admin', 'admin']:
                owns_router = db_session.query(Router).join(Network).filter(
                    Network.owner_id == user_id,
                    Router.id == router_id,
                    Router.is_deleted == False
                ).first()
                if not owns_router:
                    return jsonify({"status": "error", "message": "إجراء مرفوض: هذا الروتر غير تابع لشبكتك."}), 403

            quantity = int(req_data.get('count', 0))
            pkg_price = float(req_data.get('price', 0.0))
            duration = int(req_data.get('duration_minutes', 0))
            quota = int(req_data.get('quota_mb', 0))
            length = int(req_data.get('length', 8))
            login_type = req_data.get('login_type', 'pin_only') 
            name_prefix = req_data.get('name_prefix', '')
            use_letters = str(req_data.get('use_letters', 'true')).lower() == 'true'
            
            # المعاملات الجديدة
            username_prefix = req_data.get('username_prefix', '')
            username_length = int(req_data.get('username_length', 8))
            password_length = int(req_data.get('password_length', 8))
            use_letters_pass = str(req_data.get('use_letters_pass', 'true')).lower() == 'true'
            profile = req_data.get('profile', 'default')
            rate_limit = req_data.get('rate_limit', '')
            network_domain = req_data.get('network_domain', '')
            thermal_printer = req_data.get('thermal_printer', None)  # 58mm/80mm
            print_layout = req_data.get('print_layout', '4x8')  # 4x8, 5x8, 4x7, 3x7

            # استدعاء دالة الحقن المركزي المحدثة
            success, result = VoucherGenerator.bulk_create_vouchers(
                router_id=router_id,
                reseller_id=user_id,
                count=quantity,
                price=pkg_price,
                duration_minutes=duration,
                quota_mb=quota,
                length=length,
                use_letters=use_letters,
                login_type=login_type,
                name_prefix=name_prefix,
                username_prefix=req_data.get('username_prefix', ''),
                username_length=username_length,
                password_length=password_length,
                use_letters_pass=use_letters_pass,
                profile=profile,
                rate_limit=rate_limit,
                network_domain=req_data.get('network_domain', ''),
                thermal_printer=req_data.get('thermal_printer', None),
                print_layout=print_layout
            )
            
            if success:
                return jsonify({
                    "status": "success", 
                    "message": f"تم توليد حزمة الكروت بنجاح (رقم الحزمة: {result['batch_id']}) وإدراجها ككروت غير مستخدمة.",
                    "batch_id": result.get('batch_id'),
                    "rsc_file": result.get('rsc_file')
                })
            else:
                return jsonify({
                    "status": "error", 
                    "message": f"فشل التوليد: {result}"
                })
                
        # ب. أداة الفحص (X-Ray PIN Check) مع العزل
        elif action == 'check_pin':
            pin = req_data.get('pin', '').strip()
            
            voucher = db_session.query(Voucher).filter(
                (Voucher.username == pin) | (Voucher.password == pin)
            ).first()
            
            if not voucher:
                return jsonify({"status": "error", "message": "هذا الكارت غير مسجل في النظام."})
            
            # [تأمين صارم]: منع موزع من رؤية تفاصيل كارت شبكة أخرى
            if role not in ['super_admin', 'admin']:
                batch = db_session.query(VoucherBatch).filter_by(id=voucher.batch_id).first()
                if not batch or batch.reseller_id != user_id:
                    return jsonify({"status": "error", "message": "غير مصرح لك باستعراض بيانات هذا الكارت."}), 403
            
            router_name = voucher.router.name if getattr(voucher, 'router', None) else "غير محدد"
            
            status_ar = {
                'unused': 'متاح للبيع',
                'sold': 'مباع (رصيد محصل)',
                'active': 'متصل الآن',
                'expired': 'منتهي الصلاحية',
                'suspended': 'موقوف'
            }.get(voucher.status, voucher.status)
            
            return jsonify({
                "status": "success",
                "data": {
                    "pin": voucher.username,
                    "status": status_ar,
                    "router": router_name,
                    "price": f"{voucher.price} EGP",
                    "package": f"صلاحية {voucher.duration_minutes} دقيقة",
                    "quota": f"{voucher.quota_mb} MB" if voucher.quota_mb > 0 else "غير محدود",
                    "mac": voucher.used_by_mac if voucher.used_by_mac else "لم يربط بعد",
                    "first_login": voucher.sold_at.strftime('%Y-%m-%d %H:%M') if getattr(voucher, 'sold_at', None) else "لم يستخدم",
                    "expiry": "محدد بالباقة" if voucher.duration_minutes > 0 else "مفتوح"
                }
            })

        # ج. حفظ قالب طباعة
        elif action == 'save_print_template':
            template_data = req_data.get('template')
            network_id = req_data.get('network_id')
            
            if not network_id:
                return jsonify({"status": "error", "message": "معرف الشبكة مطلوب"}), 400
            
            network = db_session.query(Network).filter_by(id=network_id).first()
            if not network:
                return jsonify({"status": "error", "message": "الشبكة غير موجودة"}), 404
            
            # التحقق من الصلاحية
            if role not in ['super_admin', 'admin'] and network.owner_id != user_id:
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
            
            # حفظ القالب في إعدادات الشبكة
            import json
            current_settings = json.loads(network.client_settings) if network.client_settings else {}
            current_settings['print_template'] = template_data
            network.client_settings = json.dumps(current_settings)
            db_session.commit()
            
            return jsonify({"status": "success", "message": "تم حفظ القالب بنجاح"})

        # د. تحميل قالب طباعة
        elif action == 'load_print_template':
            network_id = req_data.get('network_id')
            
            network = db_session.query(Network).filter_by(id=network_id).first()
            if not network:
                return jsonify({"status": "error", "message": "الشبكة غير موجودة"}), 404
            
            if role not in ['super_admin', 'admin'] and network.owner_id != user_id:
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
            
            import json
            settings = json.loads(network.client_settings) if network.client_settings else {}
            template = settings.get('print_template', {})
            
            return jsonify({"status": "success", "template": template})

        # هـ. توليد HTML للطباعة
        elif action == 'generate_print_html':
            batch_id = req_data.get('batch_id')
            layout = req_data.get('layout', '4x8')
            thermal = req_data.get('thermal_printer')
            settings = req_data.get('settings', {})
            
            batch = db_session.query(VoucherBatch).filter_by(id=batch_id).first()
            if not batch:
                return jsonify({"status": "error", "message": "الحزمة غير موجودة"}), 404
            
            # التحقق من الصلاحية
            if role not in ['super_admin', 'admin'] and batch.reseller_id != user_id:
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
            
            vouchers = db_session.query(Voucher).filter_by(batch_id=batch_id).all()
            
            # إعداد إعدادات الطباعة
            print_settings = {
                'print_layout': layout,
                'thermal_printer': thermal,
                'network_name': batch.network.name if batch.network else 'Sakr Connect',
                'logo': batch.network.logo if batch.network and batch.network.logo else '',
                'background_image': settings.get('background_image', ''),
                'show_username': settings.get('show_username', True),
                'show_password': settings.get('show_password', True),
                'show_price': settings.get('show_price', True),
                'show_duration': settings.get('show_duration', True),
                'show_quota': settings.get('show_quota', True),
                'show_qr': settings.get('show_qr', True),
                'show_duration': settings.get('show_duration', True),
                'show_quota': settings.get('show_quota', True),
                'show_network_name': settings.get('show_network_name', True),
                'background_image': settings.get('background_image', ''),
                'print_layout': layout,
                'thermal_printer': thermal,
            }
            
            html = VoucherGenerator.generate_print_html(vouchers, print_settings)
            
            return jsonify({
                "status": "success",
                "html": html,
                "count": len(vouchers)
            })

        # و. كارت كافيه سريع
        elif action == 'quick_cafe_voucher':
            router_id = int(req_data.get('router_id'))
            plan = req_data.get('plan', {})
            
            # التحقق من الملكية
            if role not in ['super_admin', 'admin']:
                owns_router = db_session.query(Router).join(Network).filter(
                    Network.owner_id == user_id,
                    Router.id == router_id,
                    Router.is_deleted == False
                ).first()
                if not owns_router:
                    return jsonify({"status": "error", "message": "هذا الروتر غير تابع لشبكتك."}), 403
            
            success, result = VoucherGenerator.create_cafe_quick_voucher(router_id, user_id, plan)
            
            if success:
                # حساب عمولة الطابعة الحرارية لو مختارة
                thermal = req_data.get('thermal_printer')
                commission = 0
                if thermal:
                    commission = VoucherGenerator.calculate_thermal_commission(plan.get('price', 0), thermal)
                
                return jsonify({
                    "status": "success",
                    "message": "تم توليد كارت الكافيه بنجاح",
                    "voucher": result,
                    "commission": commission
                })
            else:
                return jsonify({"status": "error", "message": result})
                
    # ==========================================
    # 3. سحب الحزم والكروت الفردية والإحصائيات وتوجيه الواجهة
    # ==========================================
    if role in ['super_admin', 'admin']:
        batches = db_session.query(VoucherBatch).order_by(VoucherBatch.created_at.desc()).all()
        total_generated = db_session.query(Voucher).count()
        total_unused = db_session.query(Voucher).filter_by(status='unused').count()
        network_routers = db_session.query(Router).all()
        
        vouchers = db_session.query(Voucher).order_by(Voucher.created_at.desc()).limit(500).all()
    else:
        batches = db_session.query(VoucherBatch).filter_by(reseller_id=user_id).order_by(VoucherBatch.created_at.desc()).all()
        total_generated = db_session.query(Voucher).join(VoucherBatch).filter(VoucherBatch.reseller_id == user_id).count()
        total_unused = db_session.query(Voucher).join(VoucherBatch).filter(VoucherBatch.reseller_id == user_id, Voucher.status.in_(['unused', 'sold'])).count()
        network_routers = db_session.query(Router).join(Network).filter(Network.owner_id == user_id).order_by(Router.name.asc()).all()
        
        vouchers = db_session.query(Voucher).join(VoucherBatch).filter(VoucherBatch.reseller_id == user_id).order_by(Voucher.created_at.desc()).limit(500).all()

    total_used = total_generated - total_unused

    stats = {
        "generated": total_generated, 
        "unused": total_unused, 
        "used": total_used
    }

    return render_template(
        'manage_vouchers.html', 
        role=role, 
        batches=batches,
        stats=stats,
        routers=network_routers,
        vouchers=vouchers
    )

# ==============================================================================
# 2. [جديد] مسار التحكم الجراحي الفردي في الكروت (AJAX)
# ==============================================================================
@vouchers_bp.route('/api/voucher/action', methods=['POST'])
def voucher_action():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        return jsonify({"status": "error", "message": "غير مصرح لك"}), 403

    data = request.get_json()
    action = data.get('action')
    voucher_id = data.get('id')

    try:
        voucher = db_session.query(Voucher).filter_by(id=voucher_id).first()
        if not voucher:
            return jsonify({"status": "error", "message": "الكارت غير موجود"}), 404

        # التحقق من أن الكارت يتبع للموزع/الشبكة الطالبة للعملية
        if role not in ['super_admin', 'admin']:
            batch = db_session.query(VoucherBatch).filter_by(id=voucher.batch_id).first()
            if not batch or batch.reseller_id != user_id:
                return jsonify({"status": "error", "message": "غير مصرح لك بالتحكم في هذا الكارت"}), 403

        message = "تم تنفيذ الإجراء بنجاح."

        if action == 'delete':
            db_session.delete(voucher)
            message = "تم حذف الكارت نهائياً من النظام."
        elif action == 'suspend':
            voucher.status = 'suspended' if voucher.status != 'suspended' else 'active'
            message = "تم تغيير حالة الكارت (إيقاف/تفعيل)."
        elif action == 'clear_mac':
            voucher.used_by_mac = None
            message = "تم تصفير الماك أدريس المربوط بالكارت بنجاح."
        elif action == 'reset':
            voucher.status = 'unused'
            voucher.used_by_mac = None
            voucher.sold_at = None
            message = "تم إعادة تعيين الكارت ليصبح كارت جديد متاح للبيع."

        db_session.commit()
        return jsonify({"status": "success", "message": message})
    
    except Exception as e:
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================================================================
# 3. مسار تصميم وطباعة كروت الشحن (recharge_cards.html)
# ==============================================================================
@vouchers_bp.route('/manage/recharge_cards', methods=['GET'])
def manage_recharge_cards():
    role = session.get('role')
    user_id = session.get('user_id') 
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        abort(403)
        
    if role in ['super_admin', 'admin']:
        batches = db_session.query(VoucherBatch).order_by(VoucherBatch.created_at.desc()).all()
    else:
        batches = db_session.query(VoucherBatch).filter_by(reseller_id=user_id).order_by(VoucherBatch.created_at.desc()).all()

    return render_template(
        'recharge_cards.html', 
        role=role, 
        batches=batches
    )

# ==============================================================================
# 4. API: حفظ/تحميل قالب طباعة
# ==============================================================================
@vouchers_bp.route('/api/print_template', methods=['POST'])
def api_print_template():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    data = request.get_json()
    action = data.get('action')
    network_id = data.get('network_id')
    
    network = db_session.query(Network).filter_by(id=network_id).first()
    if not network:
        return jsonify({"status": "error", "message": "الشبكة غير موجودة"}), 404
    
    if role not in ['super_admin', 'admin'] and network.owner_id != user_id:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    import json
    if action == 'save':
        template_data = data.get('template')
        current_settings = json.loads(network.client_settings) if network.client_settings else {}
        current_settings['print_template'] = data.get('template')
        network.client_settings = json.dumps(current_settings)
        db_session.commit()
        return jsonify({"status": "success", "message": "تم حفظ القالب بنجاح"})
    
    elif action == 'load':
        settings = json.loads(network.client_settings) if network.client_settings else {}
        template = settings.get('print_template', {})
        return jsonify({"status": "success", "template": template})
    
    return jsonify({"status": "error", "message": "إجراء غير معروف"}), 400

# ==============================================================================
# 5. توليد HTML للطباعة
# ==============================================================================
@vouchers_bp.route('/api/generate_print_html', methods=['POST'])
def api_generate_print_html():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    data = request.get_json()
    batch_id = data.get('batch_id')
    layout = data.get('layout', '4x8')
    thermal = data.get('thermal_printer')
    settings = data.get('settings', {})
    
    batch = db_session.query(VoucherBatch).filter_by(id=batch_id).first()
    if not batch:
        return jsonify({"status": "error", "message": "الحزمة غير موجودة"}), 404
    
    if role not in ['super_admin', 'admin'] and batch.reseller_id != user_id:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    vouchers = db_session.query(Voucher).filter_by(batch_id=batch_id).all()
    
    print_settings = {
        'print_layout': layout,
        'thermal_printer': thermal,
        'network_name': batch.network.name if batch.network else 'Sakr Connect',
        'logo': batch.network.logo if batch.network and batch.network.logo else '',
        'background_image': settings.get('background_image', ''),
        'show_username': settings.get('show_username', True),
        'show_password': settings.get('show_password', True),
        'show_price': settings.get('show_price', True),
        'show_duration': settings.get('show_duration', True),
        'show_quota': settings.get('show_quota', True),
        'show_qr': settings.get('show_qr', True),
        'show_network_name': settings.get('show_network_name', True),
        'background_image': settings.get('background_image', ''),
        'print_layout': layout,
        'thermal_printer': thermal,
    }
    
    html = VoucherGenerator.generate_print_html(vouchers, print_settings)
    
    return jsonify({
        "status": "success",
        "html": html,
        "count": len(vouchers)
    })

# ==============================================================================
# 6. كارت كافيه سريع
# ==============================================================================
@vouchers_bp.route('/api/quick_cafe_voucher', methods=['POST'])
def api_quick_cafe_voucher():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    data = request.get_json()
    router_id = data.get('router_id')
    plan = data.get('plan', {})
    thermal = data.get('thermal_printer')
    
    if role not in ['super_admin', 'admin']:
        owns_router = db_session.query(Router).join(Network).filter(
                    Network.owner_id == user_id,
                    Router.id == router_id,
                    Router.is_deleted == False
                ).first()
        if not owns_router:
            return jsonify({"status": "error", "message": "هذا الروتر غير تابع لشبكتك."}), 403
    
    success, result = VoucherGenerator.create_cafe_quick_voucher(router_id, user_id, plan)
    
    if success:
        commission = 0
        if thermal:
            commission = VoucherGenerator.calculate_thermal_commission(plan.get('price', 0), thermal)
        
        return jsonify({
            "status": "success",
            "message": "تم توليد كارت الكافيه بنجاح",
            "voucher": result,
            "commission": commission
        })
    else:
        return jsonify({"status": "error", "message": result})

# ==============================================================================
# 7. تحميل ملف RSC للمايكروتيك
# ==============================================================================
@vouchers_bp.route('/download/rsc/<int:batch_id>')
def download_rsc(batch_id):
    role = session.get('role')
    user_id = session.get('user_id')
    
    batch = db_session.query(VoucherBatch).filter_by(id=batch_id).first()
    if not batch:
        abort(404)
    
    if role not in ['super_admin', 'admin'] and batch.reseller_id != user_id:
        abort(403)
    
    # البحث عن ملف RSC المحفوظ
    rsc_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'rsc')
    if not os.path.exists(rsc_dir):
        abort(404)
    
    for f in os.listdir(rsc_dir):
        if f.startswith(f"vouchers_{batch.name}_") and f.endswith('.rsc'):
            filepath = os.path.join(rsc_dir, f)
            return send_file(filepath, as_attachment=True, download_name=f)
    
    abort(404)

# ==============================================================================
# 8. طابعة حرارية - API
# ==============================================================================
@vouchers_bp.route('/api/thermal_print', methods=['POST'])
def api_thermal_print():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['super_admin', 'admin', 'network', 'reseller', 'cafe']:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    data = request.get_json()
    voucher_id = data.get('voucher_id')
    printer_type = data.get('printer_type', '58mm')  # 58mm أو 80mm
    
    voucher = db_session.query(Voucher).filter_by(id=voucher_id).first()
    if not voucher:
        return jsonify({"status": "error", "message": "الكارت غير موجود"}), 404
    
    # التحقق من الصلاحية
    if role not in ['super_admin', 'admin']:
        batch = db_session.query(VoucherBatch).filter_by(id=voucher.batch_id).first()
        if not batch or batch.reseller_id != user_id:
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
    
    # حساب العمولة للطابعة الحرارية
    commission = VoucherGenerator.calculate_thermal_commission(voucher.price, printer_type)
    
    # إنشاء محتوى الطباعة للطابعة الحرارية
    thermal_content = f"""
{voucher.batch.network.name if voucher.batch.network else 'Sakr Connect'}
{'='*32}
User: {voucher.username}
Pass: {voucher.password}
Price: {voucher.price} EGP
{'='*32}
Valid: {voucher.duration_minutes} min
Quota: {voucher.quota_mb} MB
{'='*32}
Commission: {commission} EGP
    """.strip()
    
    # هنا يتم إرسال المحتوى للطابعة الحرارية عبر API الطابعة
    # في التطبيق الحقيقي: يتصل بخدمة الطابعة الحرارية
    
    return jsonify({
        "status": "success",
        "content": thermal_content,
        "commission": commission,
        "message": "تم تجهيز محتوى الطباعة الحرارية"
    })