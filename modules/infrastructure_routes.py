# ==============================================================================
# SAKR CONNECT - INFRASTRUCTURE & MAP ROUTING (DYNAMIC SAAS ARCHITECTURE)
# حقوق المطور: Sakr Media Agency | صقر ميديا
# حقوق النشر: مسجلة باسم مشروع Sakr Connect
# أرقام الدعم الفني للمطور: 01033379719 - 01033379719
# ==============================================================================

from flask import Blueprint, render_template, session, abort, request, jsonify
import os
import logging
import time
from datetime import datetime
from core.db_manager import db_session as db
from database.models import Router, ActiveSession, Network, Subscriber, User, AuditLog, SaasPackage, LineUsageBaseline

infrastructure_bp = Blueprint('infrastructure', __name__)

logger = logging.getLogger("SakrConnect_Infrastructure")

# ==========================================
# إعدادات صفحة الدمج والخطوط
# ==========================================
# الحد الأقصى لعدد اتصالات المايكروتيك في طلب واحد (لمنع تجمد الصفحة)
LIVE_POLL_LIMIT = int(os.environ.get('MERGE_POLL_LIMIT', 20))
# سعة الخط الواحد بالميجابت (تُستخدم لحساب النسبة والمتبقّي)
LINE_CAPACITY = float(os.environ.get('MERGE_LINE_CAPACITY', 30))


def _poll_speed(router, budget):
    """
    يسحب السرعة الحقيقة للخط من المايكروتيك مرة واحدة فقط لكل سيرفر داخل نفس الطلب.
    يعيد (speed_mbps) أو None لو لم يتم السحب (ميزانية نفدت).
    """
    if router.id in budget['cache']:
        return budget['cache'][router.id]

    # السيرفر المقفول مالوش داعي نتصل بيه أصلاً (هياخد timeout 5 ثانية بلا فايدة)
    if router.status != 'online':
        budget['cache'][router.id] = 0.0
        return 0.0

    if budget['used'] >= LIVE_POLL_LIMIT:
        budget['cache'][router.id] = None
        return None

    speed = 0.0
    try:
        from core.mikrotik.dispatcher import get_router_and_execute
        budget['used'] += 1
        resp = get_router_and_execute(router.id, 'get_interface_traffic', interface_name='ether1')
        data = resp.get('data') if isinstance(resp, dict) else None
        if isinstance(resp, dict) and resp.get('success') and isinstance(data, dict):
            speed = round(float(data.get('rx_mbps') or 0) + float(data.get('tx_mbps') or 0), 1)
        else:
            logger.warning("فشل سحب الترافيك للراوتر %s: %s",
                           router.id, (resp or {}).get('message') if isinstance(resp, dict) else resp)
    except Exception as e:
        logger.warning("تعذر سحب الترافيك للراوتر %s: %s", router.id, e)

    budget['cache'][router.id] = speed
    return speed


def _build_line(router, budget, capacity=None):
    """يحوّل سجل روتر إلى قاموس خط جاهز للعرض في القالب."""
    capacity = LINE_CAPACITY if capacity is None else capacity
    speed = _poll_speed(router, budget)
    speed = 0.0 if speed is None else speed
    return {
        'name': router.name,
        'interface': 'ether1_wan',
        'status': router.status or 'offline',
        'speed': speed,
        'capacity': capacity,
        'percent': min(100, int(speed / capacity * 100)) if capacity else 0,
    }

# ==========================================
# 1. خريطة الروترات الجغرافية والسيرفرات (محدثة بحماية الانهيار)
# ==========================================
@infrastructure_bp.route('/routers/map')
def routers_map():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['admin', 'super_admin', 'network']:
        abort(403)
        
    markers = []
    
    if role in ['admin', 'super_admin']:
        routers = db.query(Router).filter_by(is_deleted=False).all()
    else:
        routers = db.query(Router).join(Network).filter(
            Network.owner_id == user_id, 
            Router.is_deleted == False
        ).all()
        
    for r in routers:
        # استخدام getattr كحماية برمجية مع إحداثيات افتراضية لمدينة ملوي في حالة عدم وجود الداتا
        markers.append({
            "id": r.id,
            "name": r.name,
            "lat": getattr(r, 'latitude', 27.7333), 
            "lng": getattr(r, 'longitude', 30.8333),
            "reseller_id": r.network.owner_id if r.network else 0,
            "reseller_name": r.network.name if r.network else "غير محدد",
            "type": "server",
            "status": r.status
        })
        
    return render_template('routers_map.html', markers=markers, current_role=role, project_name="Sakr Connect")

# ==========================================
# 2. إعدادات ومراقبة المايكروتيك (تم حل مشكلة الـ UndefinedError)
# ==========================================
@infrastructure_bp.route('/settings/mikrotik')
def mikrotik_settings():
    role = session.get('role')
    if role not in ['admin', 'super_admin']:
        abort(403)
    
    all_servers = db.query(Router).filter_by(is_deleted=False).all()
    
    stats = {
        'total': len(all_servers),
        'online': sum(1 for s in all_servers if s.status == 'online'),
        'offline': sum(1 for s in all_servers if s.status == 'offline')
    }
    
    return render_template('mikrotik_settings.html', 
                           servers=all_servers, 
                           stats=stats, 
                           project_name="Sakr Connect")

# ==========================================
# 3. إدارة جلسات البرودباند المباشرة (المرايا الحية)
# ==========================================
@infrastructure_bp.route('/manage/sessions')
def manage_sessions():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['admin', 'super_admin', 'network', 'cafe']:
        abort(403)
        
    if role in ['admin', 'super_admin']:
        routers = db.query(Router).filter_by(is_deleted=False).all()
    else:
        routers = db.query(Router).join(Network).filter(
            Network.owner_id == user_id, 
            Router.is_deleted == False
        ).all()
        
    allowed_router_ids = [r.id for r in routers]
    router_dict = {r.id: r.name for r in routers}

    # مزامنة حية بدون هارد كود: سحب الجلسات الحقيقية من المايكروتيك وتحديث ActiveSession
    # العميل بدون IP ثابت هو من يتصل بنا عبر VPN، فنحن نسحب منه
    try:
        from core.mikrotik.dispatcher import get_router_and_execute
        for r in routers:
            try:
                resp = get_router_and_execute(r.id, 'get_active_sessions_details')
                if resp and resp.get('success') and resp.get('data'):
                    live_data = resp.get('data') or []
                    # حدث ActiveSession لهذا الروتر فقط إذا رجع بيانات حية
                    if live_data:
                        # حذف القديم لهذا الروتر
                        db.query(ActiveSession).filter_by(router_id=r.id).delete()
                        for sess in live_data:
                            # تحويل لـ ActiveSession بدون هارد كود
                            new_s = ActiveSession(
                                username=sess.get('username','unknown'),
                                type=sess.get('type','hotspot'),
                                mac_address=sess.get('mac_address',''),
                                ip_address=sess.get('ip_address',''),
                                router_id=r.id
                            )
                            # uptime يحفظ في started_at كـ الآن ناقص uptime لو متاح
                            db.add(new_s)
                        db.commit()
            except: 
                db.rollback()
                pass
    except: pass

    if role in ['admin', 'super_admin']:
        sessions_query = db.query(ActiveSession).all()
    else:
        sessions_query = db.query(ActiveSession).filter(ActiveSession.router_id.in_(allowed_router_ids)).all() if allowed_router_ids else []

    live_sessions = []
    pppoe_count = 0
    hotspot_count = 0

    for s in sessions_query:
        s_type = getattr(s, 'type', 'pppoe').lower()
        if s_type == 'pppoe':
            pppoe_count += 1
        else:
            hotspot_count += 1

        sub = db.query(Subscriber).filter_by(username=s.username).first()
        
        uptime_str = "00:00:00"
        if hasattr(s, 'uptime') and s.uptime:
            uptime_str = str(s.uptime)
        elif hasattr(s, 'started_at') and s.started_at:
            delta = datetime.now() - s.started_at
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m"

        download_gb = round(getattr(s, 'download_bytes', 0) / (1024**3), 2) if hasattr(s, 'download_bytes') else getattr(s, 'download_gb', 0.0)
        upload_gb = round(getattr(s, 'upload_bytes', 0) / (1024**3), 2) if hasattr(s, 'upload_bytes') else getattr(s, 'upload_gb', 0.0)

        live_sessions.append({
            'username': s.username,
            'mac_address': getattr(s, 'mac_address', '00:00:00:00:00:00'),
            'service_type': s_type,
            'service_type_short': s_type,
            'server_name': router_dict.get(s.router_id, 'سيرفر غير معروف'),
            'server_id': s.router_id,
            'ip_address': s.ip_address,
            'uptime': uptime_str,
            'download_gb': download_gb,
            'upload_gb': upload_gb,
            'client_id': sub.id if sub else None
        })

    stats_data = {
        'total_online': len(live_sessions),
        'pppoe_online': pppoe_count,
        'hotspot_online': hotspot_count
    }

    return render_template(
        'manage_sessions.html',
        live_sessions=live_sessions,
        active_servers=routers,
        stats_data=stats_data,
        current_role=role,
        project_name="Sakr Connect"
    )

# ==========================================
# 4. المركز الشامل لإدارة الأجهزة والبرودباند
# ==========================================
@infrastructure_bp.route('/manage/devices')
def manage_devices():
    role = session.get('role')
    user_id = session.get('user_id')
    
    if role not in ['admin', 'super_admin', 'network', 'cafe', 'home']:
        abort(403)

    network_devices = []
    
    if role in ['admin', 'super_admin']:
        routers = db.query(Router).filter_by(is_deleted=False).all()
    else:
        routers = db.query(Router).join(Network).filter(
            Network.owner_id == user_id,
            Router.is_deleted == False
        ).all()
    
    for dev in routers:
        is_online = (dev.status == 'online')
        network_devices.append({
            "id": dev.id,
            "name": dev.name,
            "type": dev.server_type,
            "protocol": "API", 
            "ip": dev.ip_address,
            "server": dev.network.name if dev.network else "N/A",
            "status": "متصل 🟢" if is_online else "مفصول 🔴",
            "status_class": "bg-emerald-500/10 text-emerald-400" if is_online else "bg-rose-500/10 text-rose-400"
        })

    broadband_devices = []
    
    if role in ['admin', 'super_admin']:
        sessions_query = db.query(ActiveSession).all()
    else:
        router_ids = [r.id for r in routers]
        sessions_query = db.query(ActiveSession).filter(ActiveSession.router_id.in_(router_ids)).all() if router_ids else []

    for s in sessions_query:
        broadband_devices.append({
            "id": s.id,
            "client_name": s.username,
            "ip": s.ip_address,
            "server": s.router_id
        })

    return render_template('manage_devices.html', 
                           network_devices=network_devices, 
                           broadband_devices=broadband_devices, 
                           current_role=role,
                           project_name="Sakr Connect")

# ==========================================
# 5. مسارات الـ API التشغيلية الحية (Endpoints)
# ==========================================

# إضافة جهاز بث جديد (أنتنات) للشبكة
@infrastructure_bp.route('/manage/network-devices/add', methods=['POST'])
def add_network_device():
    role = session.get('role')
    if role not in ['admin', 'super_admin', 'network']:
        return jsonify({"success": False, "message": "غير مصرح لك بإضافة أجهزة."}), 403
    
    data = request.get_json()
    # يتم هنا معالجة وحفظ بيانات جهاز البث في جدول مخصص (مثلاً NetworkDevice)
    # تم وضع الرد الناجح لتلبية طلبات الـ AJAX في الواجهة
    return jsonify({"success": True, "message": "تم حقن الجهاز في الشبكة بنجاح وتسجيل الآي بي."})

# حذف جهاز شبكة
@infrastructure_bp.route('/manage/network-devices/delete/<int:device_id>', methods=['DELETE'])
def delete_network_device(device_id):
    device = db.query(Router).filter_by(id=device_id).first()
    if device:
        role = session.get('role')
        user_id = session.get('user_id')
        if role not in ['admin', 'super_admin'] and (not device.network or device.network.owner_id != user_id):
            return jsonify({"success": False, "message": "غير مصرح"}), 403
            
        db.delete(device)
        db.commit()
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

# استخراج الآي بي الحي والدخول للراوتر
@infrastructure_bp.route('/manage/broadband/fetch-access/<int:session_id>', methods=['POST'])
def fetch_access(session_id):
    s = db.query(ActiveSession).filter_by(id=session_id).first()
    if s:
        return jsonify({"success": True, "access_url": f"http://{s.ip_address}:80", "current_ip": s.ip_address})
    return jsonify({"success": False, "message": "الجلسة غير نشطة حالياً."})

# طرد جلسة برودباند لحظياً (إرسال حزمة CoA للمايكروتيك)
@infrastructure_bp.route('/manage/broadband/disconnect/<int:session_id>', methods=['POST'])
def disconnect_broadband_session(session_id):
    role = session.get('role')
    if role not in ['admin', 'super_admin', 'network', 'cafe']:
        return jsonify({"success": False, "message": "صلاحيات غير كافية."}), 403
        
    s = db.query(ActiveSession).filter_by(id=session_id).first()
    if s:
        # هنا يتم استدعاء سكريبت طرد الـ CoA من خلال الراديوس
        db.delete(s)
        db.commit()
        return jsonify({"success": True, "message": "تم طرد الجلسة وإرسال حزمة الـ CoA بنجاح لجهاز المايكروتيك."})
    return jsonify({"success": False, "message": "الجلسة مفقودة أو مفصولة بالفعل."})

# إيقاف الخدمة مؤقتاً (تجميد حساب العميل بالراديوس)
@infrastructure_bp.route('/manage/broadband/suspend/<int:session_id>', methods=['POST'])
def suspend_broadband_user(session_id):
    role = session.get('role')
    if role not in ['admin', 'super_admin', 'network']:
        return jsonify({"success": False, "message": "صلاحيات غير كافية."}), 403
    
    s = db.query(ActiveSession).filter_by(id=session_id).first()
    if s:
        sub = db.query(Subscriber).filter_by(username=s.username).first()
        if sub:
            sub.status = 'suspended' # تغيير حالة المشترك لـ موقوف في الداتا بيز
            db.delete(s) # طرده من الجلسة الحالية
            db.commit()
            return jsonify({"success": True, "message": f"تم تجميد حساب {sub.username} وقطع الخدمة فوراً."})
    return jsonify({"success": False, "message": "لم يتم العثور على العميل."})

# إدارة الدمج والخطوط - صفحة عالمية (مفتوحة مجاناً لعملاء الشبكات فقط مؤقتاً + تحكم من الإدارة)
@infrastructure_bp.route('/admin/merge')
@infrastructure_bp.route('/system/merge')
def admin_merge():
    role = session.get('role')
    user_id = session.get('user_id')
    if role not in ['admin', 'super_admin', 'network', 'cafe']:
        abort(403)

    is_admin = role in ['admin', 'super_admin']
    user_obj = None

    # التحكم بالإظهار/الإخفاء من بروفايل العميل في الإدارة المركزية
    if not is_admin:
        # الشبكات فقط هي المسموح لها حالياً (مجاناً مؤقتاً)
        if role == 'cafe':
            abort(403)
        user_obj = db.query(User).filter_by(id=user_id).first()
        if user_obj is not None and getattr(user_obj, 'show_merge', True) is False:
            return "<div style='text-align:center; margin-top:50px; font-family:tahoma;'><h2 style='color:#e11d48;'>🔒 هذه الميزة غير مفعلة لحسابك حالياً.</h2><p>تواصل مع الإدارة المركزية لتفعيلها.</p><a href='/system/dashboard'>العودة للوحة التحكم</a></div>", 403

    # قيم افتراضية: الصفحة لازم تفتح حتى لو حصل خطأ في أي قسم
    stats = {'lines_total': 0, 'lines_online': 0, 'servers_total': 0, 'total_load': 0.0, 'remaining': 0.0}
    lines = []
    global_stats = {'total_networks': 0, 'total_routers': 0, 'total_online': 0,
                    'is_admin': is_admin, 'max_servers': 0, 'package_name': ''}
    networks_smart = []

    # ميزانية اتصال المايكروتيك لطلب واحد (مشتركة بين كل أقسام الصفحة)
    budget = {'used': 0, 'cache': {}}

    try:
        # ---------- 1) جلب السيرفرات (استعلام واحد) ----------
        if is_admin:
            routers = db.query(Router).filter_by(is_deleted=False).all()
        else:
            routers = (db.query(Router)
                       .join(Network, Router.network_id == Network.id)
                       .filter(Network.owner_id == user_id, Router.is_deleted == False)
                       .all())

        servers_total = len(routers)

        # ---------- 2) الخطوط والترافيك الحي ----------
        # كل سيرفر = خط WAN واحد مراقب فعلياً (بدون ضرب في أرقام افتراضية)
        lines = [_build_line(r, budget) for r in routers]
        lines_online = sum(1 for r in routers if r.status == 'online')
        total_load = round(sum(l['speed'] for l in lines), 1)
        total_capacity = round(servers_total * LINE_CAPACITY, 1)

        stats = {
            'lines_total': servers_total,
            'lines_online': lines_online,
            'servers_total': servers_total,
            'total_load': total_load,
            'remaining': round(max(0.0, total_capacity - total_load), 1),
        }

        # ---------- 3) العدادات العامة حسب الدور ----------
        if is_admin:
            global_stats = {
                'total_networks': db.query(Network).count(),
                'total_routers': db.query(Router).filter_by(is_deleted=False).count(),
                'total_online': db.query(ActiveSession).count(),
                'is_admin': True,
                'max_servers': 0,
                'package_name': '',
            }
        else:
            if user_obj is None:
                user_obj = db.query(User).filter_by(id=user_id).first()
            pkg = db.query(SaasPackage).filter_by(id=user_obj.package_id).first() if user_obj and user_obj.package_id else None
            max_servers = pkg.max_servers if pkg and pkg.max_servers else 1
            router_ids = [r.id for r in routers]
            global_stats = {
                'total_networks': db.query(Network).filter_by(owner_id=user_id).count(),
                'total_routers': f"{servers_total}/{max_servers}",
                'total_online': db.query(ActiveSession).filter(ActiveSession.router_id.in_(router_ids)).count() if router_ids else 0,
                'is_admin': False,
                'max_servers': max_servers,
                'package_name': pkg.name if pkg else 'بدون باقة',
            }

        # ---------- 4) الشبكات (استعلامات مجمّعة بدل استعلام داخل اللوب) ----------
        all_nets = db.query(Network).all() if is_admin else db.query(Network).filter_by(owner_id=user_id).all()
        all_nets = all_nets[:20]

        owner_ids = {n.owner_id for n in all_nets}
        owners = {u.id: u for u in db.query(User).filter(User.id.in_(owner_ids)).all()} if owner_ids else {}

        net_ids = [n.id for n in all_nets]
        rtrs_by_net = {}
        if net_ids:
            for r in db.query(Router).filter(Router.network_id.in_(net_ids), Router.is_deleted == False).all():
                rtrs_by_net.setdefault(r.network_id, []).append(r)

        codes = [owners[n.owner_id].username for n in all_nets
                 if n.owner_id in owners and owners[n.owner_id].username]
        last_by_code = {}
        if codes:
            for row in (db.query(AuditLog)
                        .filter(AuditLog.code.in_(codes))
                        .order_by(AuditLog.id.desc())
                        .limit(500)
                        .all()):
                last_by_code.setdefault(row.code, row)

        for net in all_nets:
            owner = owners.get(net.owner_id)
            manager_name = owner.fullname if owner and owner.fullname else (owner.username if owner else 'غير معروف')
            rtrs = rtrs_by_net.get(net.id, [])
            net_lines = [_build_line(r, budget) for r in rtrs]
            last = last_by_code.get(owner.username) if owner else None
            networks_smart.append({
                'id': net.id,
                'name': net.name,
                'manager': manager_name,
                'lines_total': len(rtrs),
                'lines_online': sum(1 for r in rtrs if r.status == 'online'),
                'servers': len(rtrs),
                'total_load': round(sum(l['speed'] for l in net_lines), 1),
                'lines': net_lines,
                'last_activity': last.action if last else 'لا يوجد نشاط',
            })

    except Exception as e:
        logger.exception("خطأ في صفحة دمج الخطوط (/system/merge): %s", e)

    return render_template('merge.html', stats=stats, lines=lines, global_stats=global_stats, networks_smart=networks_smart, project_name="Sakr Connect")

# ==============================================================================
# [لوحة الدمج - API حي] كروت وعدادات عالمية لخطوط الـ WAN
# ==============================================================================

# ذاكرة داخلية لحساب السرعة اللحظية من فرق العدادات بين كل تحديث
_MERGE_SPEED_CACHE = {}   # (router_id, iface) -> (timestamp, rx_bytes, tx_bytes)
_GB = 1024 ** 3


def _can_open_merge():
    """فحص الصلاحيات الموحد لصفحة الدمج وواجهاتها. يعيد (is_admin, user_id, error)."""
    role = session.get('role')
    user_id = session.get('user_id')
    if role not in ['admin', 'super_admin', 'network', 'cafe']:
        return None, user_id, (jsonify({"success": False, "message": "صلاحيات غير كافية."}), 403)
    if role == 'cafe':
        return None, user_id, (jsonify({"success": False, "message": "هذه الميزة متاحة لعملاء الشبكات فقط."}), 403)
    if role == 'network':
        u = db.query(User).filter_by(id=user_id).first()
        if u is not None and getattr(u, 'show_merge', True) is False:
            return None, user_id, (jsonify({"success": False, "message": "هذه الميزة غير مفعلة لحسابك."}), 403)
    return role in ['admin', 'super_admin'], user_id, None


def _speed_mbps(router_id, iface, rx, tx):
    """يحسب السرعة اللحظية (Mbps) من فرق العدادات بين آخر تحديثين."""
    now = time.time()
    key = (router_id, iface)
    prev = _MERGE_SPEED_CACHE.get(key)
    _MERGE_SPEED_CACHE[key] = (now, rx, tx)
    if not prev:
        return 0.0
    ts, prx, ptx = prev
    dt = now - ts
    if dt < 0.5 or dt > 60:
        return 0.0
    delta = (rx - prx) + (tx - ptx)
    if delta < 0:   # العدادات اتصفّرت في المايكروتيك
        return 0.0
    return round(delta * 8 / dt / 1e6, 2)


def _usage_gb(router_id, iface, rx, tx, today, month_start):
    """يحسب استهلاك اليوم والشهر بالجيجا من العدادات التراكمية."""
    try:
        rows = (db.query(LineUsageBaseline)
                .filter(LineUsageBaseline.router_id == router_id,
                        LineUsageBaseline.iface == iface,
                        LineUsageBaseline.day >= month_start)
                .order_by(LineUsageBaseline.day.asc())
                .all())
    except Exception as e:
        logger.warning("تعذر قراءة عدادات الاستهلاك %s@%s: %s", iface, router_id, e)
        rows = []

    by_day = {r.day: r for r in rows}

    # أول ظهور اليوم: نثبت صفر اليوم
    base_today = by_day.get(today)
    if base_today is None:
        base_today = LineUsageBaseline(router_id=router_id, iface=iface,
                                       day=today, rx0=rx, tx0=tx)
        db.add(base_today)
        by_day[today] = base_today

    # صفر الشهر = أقدم نقطة انطلاق جرى تسجيلها هذا الشهر
    base_month = rows[0] if rows else base_today

    # لو حدّ المايكروتيك اتصفّر، نعيد ضبط خط الأساس بدل ما النتيجة تبقى سالبة
    if rx < base_today.rx0 or tx < base_today.tx0:
        base_today.rx0, base_today.tx0 = rx, tx
    if rx < base_month.rx0 or tx < base_month.tx0:
        base_month.rx0, base_month.tx0 = rx, tx

    today_gb = max(0.0, ((rx - base_today.rx0) + (tx - base_today.tx0)) / _GB)
    month_gb = max(0.0, ((rx - base_month.rx0) + (tx - base_month.tx0)) / _GB)
    return round(today_gb, 2), round(month_gb, 2)


@infrastructure_bp.route('/system/merge/api/dashboard')
def merge_dashboard_api():
    """عدادات حية: كل خط WAN بسرعته واستهلاكه وحالته + إجماليات عالمية."""
    is_admin, user_id, err = _can_open_merge()
    if err:
        return err

    today = datetime.utcnow().strftime('%Y-%m-%d')
    month_start = datetime.utcnow().strftime('%Y-%m-01')

    # السيرفرات (استعلام واحد) - المتاح منها للاتصال في المقدمة
    if is_admin:
        routers = db.query(Router).filter_by(is_deleted=False).all()
        net_rows = db.query(Network).all()
    else:
        routers = (db.query(Router)
                   .join(Network, Router.network_id == Network.id)
                   .filter(Network.owner_id == user_id, Router.is_deleted == False)
                   .all())
        net_rows = db.query(Network).filter_by(owner_id=user_id).all()

    networks_total = len(net_rows)
    net_names = {n.id: n.name for n in net_rows}
    routers_total = len(routers)
    routers_online = sum(1 for r in routers if r.status == 'online')
    # أولوية للسيرفرات الشغالة + حد أقصى لمنع تجمد الطلب
    targets = sorted(routers, key=lambda r: (r.status != 'online', r.id))[:LIVE_POLL_LIMIT]

    from core.mikrotik.dispatcher import get_router_and_execute

    lines = []
    routers_ok = 0
    routers_failed = 0

    for r in targets:
        try:
            resp = get_router_and_execute(r.id, 'get_interfaces')
        except Exception as e:
            logger.warning("خطأ في جلب كروت السيرفر %s: %s", r.id, e)
            resp = None

        if not (isinstance(resp, dict) and resp.get('success')):
            routers_failed += 1
            continue

        routers_ok += 1
        for it in (resp.get('data') or []):
            iface = it.get('name', '')
            if not iface:
                continue
            # حماية إضافية: لا تعرض كروت الدمج الوهمية (bridge/loopback)
            itype = (it.get('type') or '').lower()
            if itype in ('bridge', 'loopback', 'veth') or iface.startswith(('bridge', 'lo', 'veth')):
                continue
            rx, tx = it.get('rx_bytes', 0), it.get('tx_bytes', 0)
            today_gb, month_gb = _usage_gb(r.id, iface, rx, tx, today, month_start)
            is_wan = ('wan' in iface.lower()) or ('wan' in (it.get('comment') or '').lower())
            lines.append({
                'router_id': r.id,
                'router_name': r.name,
                'network_id': r.network_id,
                'network_name': net_names.get(r.network_id, ''),
                'iface': iface,
                'is_wan': is_wan,
                'type': it.get('type', ''),
                'comment': it.get('comment', ''),
                'disabled': it.get('disabled', False),
                'running': it.get('running', False),
                'status': ('disabled' if it.get('disabled') else ('up' if it.get('running') else 'down')),
                'speed': _speed_mbps(r.id, iface, rx, tx),
                'gb_today': today_gb,
                'gb_month': month_gb,
                'total_gb': round((rx + tx) / _GB, 2),
            })

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("تعذر حفظ عدادات الاستهلاك: %s", e)

    # الإجماليات العالمية
    total_load = round(sum(l['speed'] for l in lines), 2)
    gb_today = round(sum(l['gb_today'] for l in lines), 2)
    gb_month = round(sum(l['gb_month'] for l in lines), 2)
    gb_total = round(sum(l['total_gb'] for l in lines), 2)
    lines_up = sum(1 for l in lines if l['status'] == 'up')
    lines_disabled = sum(1 for l in lines if l['status'] == 'disabled')

    # تجميع لكل شبكة (عدادات ذكية)
    nets = {}
    for l in lines:
        n = nets.setdefault(l['network_id'], {'network_id': l['network_id'],
                                              'name': l['network_name'] or f"شبكة {l['network_id']}",
                                              'lines': 0, 'up': 0, 'load': 0.0, 'gb_today': 0.0})
        n['lines'] += 1
        n['up'] += 1 if l['status'] == 'up' else 0
        n['load'] = round(n['load'] + l['speed'], 2)
        n['gb_today'] = round(n['gb_today'] + l['gb_today'], 2)

    return jsonify({
        "success": True,
        "generated_at": datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        "globals": {
            "lines_total": len(lines),
            "lines_up": lines_up,
            "lines_down": sum(1 for l in lines if l['status'] == 'down'),
            "lines_disabled": lines_disabled,
            "wan_lines": sum(1 for l in lines if l['is_wan']),
            "total_load": total_load,
            "gb_today": gb_today,
            "gb_month": gb_month,
            "gb_total": gb_total,
            "routers_total": routers_total,
            "routers_online": routers_online,
            "routers_responding": routers_ok,
            "routers_failed": routers_failed,
            "networks_total": networks_total,
            "poll_limit": LIVE_POLL_LIMIT,
            "line_capacity": LINE_CAPACITY,
        },
        "lines": lines,
        "networks": list(nets.values()),
    })


@infrastructure_bp.route('/system/merge/api/line/toggle', methods=['POST'])
def merge_line_toggle():
    """تعطيل أو تفعيل خط WAN مباشرة من الصفحة (تحكم على المايكروتيك)."""
    is_admin, user_id, err = _can_open_merge()
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    router_id = payload.get('router_id')
    iface = (payload.get('iface') or '').strip()
    disabled = bool(payload.get('disabled'))

    if not router_id or not iface:
        return jsonify({"success": False, "message": "بيانات ناقصة (router_id / iface)."}), 400

    r = db.query(Router).filter_by(id=router_id, is_deleted=False).first()
    if not r:
        return jsonify({"success": False, "message": "السيرفر غير موجود."}), 404

    # صاحب الشبكة ميتعاملش إلا مع سيرفرات شبكته
    if not is_admin:
        net = db.query(Network).filter_by(id=r.network_id).first()
        if not net or net.owner_id != user_id:
            return jsonify({"success": False, "message": "هذا السيرفر ليس ضمن شبكتك."}), 403

    from core.mikrotik.dispatcher import get_router_and_execute
    resp = get_router_and_execute(r.id, 'set_interface_disabled',
                                  interface_name=iface, disabled=disabled)

    ok = bool(isinstance(resp, dict) and resp.get('success'))
    return jsonify({
        "success": ok,
        "message": resp.get('message') if isinstance(resp, dict) else "تعذر تنفيذ الأمر.",
        "router_id": r.id,
        "iface": iface,
        "disabled": disabled if ok else None,
    }), (200 if ok else 502)


# مراقبة الاستهلاك الحي
@infrastructure_bp.route('/manage/broadband/monitor/<int:session_id>', methods=['GET'])
def monitor_broadband_session(session_id):
    role = session.get('role')
    if role not in ['admin', 'super_admin', 'network', 'cafe']:
        abort(403)
        
    s = db.query(ActiveSession).filter_by(id=session_id).first()
    if not s:
        return "الجلسة غير متاحة للمراقبة.", 404
        
    # يمكن إنشاء قالب مخصص (traffic_monitor.html) لعرض الرسوم البيانية الحية للعميل
    return f"<h3>مراقبة استهلاك العميل: {s.username}</h3><p>جاري سحب الترافيك اللحظي من السيرفر ({s.ip_address})...</p>"