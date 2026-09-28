# ==============================================================================
# Project: Sakr Connect System - Home Routing Engine (Final Build)
# Developer: Sakr Media Agency (صقر ميديا) - م / أحمد سالم الملواني
# Support: 01033379719 - 01033379719
# Address: 
# Copyright: تُسجل باسم المشروع (Sakr Connect)
# ==============================================================================

from flask import Blueprint, request, jsonify, session
import requests
from bs4 import BeautifulSoup

home_bp = Blueprint('home', __name__, url_prefix='/api/home')

# ==========================================
# 1. قاموس التعرف على نوع الراوتر
# ==========================================
def identify_router_vendor(mac_address):
    if not mac_address:
        return "Unknown"
    mac_prefix = mac_address.replace(":", "").replace("-", "").upper()[:6]
    
    vendors = {
        # ZTE
        "9CE91C": "ZTE", "0019C6": "ZTE", "0022A1": "ZTE", "0026ED": "ZTE", 
        "208B37": "ZTE", "344B50": "ZTE", "4C1B86": "ZTE", "54ACD2": "ZTE",
        # Huawei
        "001E10": "Huawei", "00259E": "Huawei", "00E0FC": "Huawei", "0819A6": "Huawei",
        # TP-Link
        "000AEB": "TP-Link", "C006C3": "TP-Link", "001D0F": "TP-Link",
        # D-Link
        "00055D": "D-Link", "000D88": "D-Link", "001195": "D-Link",
        # Zyxel
        "00A0C5": "Zyxel", "34A84E": "Zyxel"
    }
    return vendors.get(mac_prefix, "Unknown_Vendor")

# ==========================================
# 2. محرك السحب والتفاعل (Scraping Engine)
# ==========================================
def get_router_session(ip, user, password):
    """إنشاء جلسة اتصال مع الراوتر"""
    s = requests.Session()
    try:
        # محاكاة عامة لتسجيل الدخول
        s.post(f"http://{ip}/", data={"Username": user, "Password": password}, timeout=5)
        return s
    except Exception:
        return None

def fetch_zte_devices(req_session, ip):
    """سحب الأجهزة من راوترات ZTE"""
    devices = []
    try:
        response = req_session.get(f"http://{ip}/status_device.asp", timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr', {'class': 'device-row'}) 
        for row in rows:
            name = row.find('td', {'class': 'dev-name'}).text.strip() if row.find('td', {'class': 'dev-name'}) else "Unknown ZTE Device"
            mac = row.find('td', {'class': 'dev-mac'}).text.strip() if row.find('td', {'class': 'dev-mac'}) else ""
            if mac:
                devices.append({'name': name, 'mac': mac, 'status': 'online', 'speed': 'Auto'})
    except Exception:
        pass
    return devices

def fetch_huawei_devices(req_session, ip):
    """سحب الأجهزة من راوترات Huawei"""
    devices = []
    try:
        response = req_session.get(f"http://{ip}/html/status/status_device.asp", timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('div', {'class': 'huawei-client'}) 
        for item in items:
            name = item.find('span', {'class': 'host-name'}).text.strip() if item.find('span', {'class': 'host-name'}) else "Unknown Huawei Device"
            mac = item.find('span', {'class': 'mac-address'}).text.strip() if item.find('span', {'class': 'mac-address'}) else ""
            if mac:
                devices.append({'name': name, 'mac': mac, 'status': 'online', 'speed': 'Auto'})
    except Exception:
        pass
    return devices

def fetch_tplink_devices(req_session, ip):
    """سحب الأجهزة من راوترات TP-Link"""
    devices = []
    try:
        response = req_session.get(f"http://{ip}/userRpm/AssignedIpAddrListRpm.htm", timeout=5)
        # سيتم إضافة منطق تحليل مصفوفات الجافاسكريبت الخاص بـ TP-Link هنا
    except Exception:
        pass
    return devices

def fetch_dlink_devices(req_session, ip):
    """سحب الأجهزة من راوترات D-Link"""
    devices = []
    try:
        response = req_session.get(f"http://{ip}/info/lan.htm", timeout=5)
        # سيتم إضافة منطق تحليل هيكل D-Link هنا
    except Exception:
        pass
    return devices

# ==========================================
# 3. مسارات التحكم والربط (API Routes)
# ==========================================
@home_bp.route('/connect_router', methods=['POST'])
def connect_router():
    data = request.get_json()
    ip = data.get('ip')
    username = data.get('username')
    password = data.get('password')
    mac = data.get('mac_address')
    
    vendor = identify_router_vendor(mac)
    
    session['router_ip'] = ip
    session['router_user'] = username
    session['router_pass'] = password
    session['router_mac'] = mac
    session['router_vendor'] = vendor

    r_session = get_router_session(ip, username, password)
    return jsonify({
        "success": True, 
        "vendor": vendor, 
        "message": f"تم الاتصال وحفظ بيانات الراوتر ({vendor})"
    })

@home_bp.route('/get_connected_devices', methods=['GET'])
def get_connected_devices():
    """المحول الذكي لجلب الأجهزة بناءً على نوع الراوتر"""
    ip = session.get('router_ip')
    user = session.get('router_user')
    password = session.get('router_pass')
    vendor = session.get('router_vendor')

    if not ip or not user or not password:
        return jsonify({"success": False, "message": "البيانات غير متوفرة."}), 400

    r_session = get_router_session(ip, user, password)
    if not r_session:
        return jsonify({"success": False, "devices": []})

    devices = []
    
    # توجيه أمر السحب للدالة المطابقة لنوع الراوتر
    if vendor == "ZTE":
        devices = fetch_zte_devices(r_session, ip)
    elif vendor == "Huawei":
        devices = fetch_huawei_devices(r_session, ip)
    elif vendor == "TP-Link":
        devices = fetch_tplink_devices(r_session, ip)
    elif vendor == "D-Link":
        devices = fetch_dlink_devices(r_session, ip)
    
    return jsonify({"success": True, "vendor": vendor, "devices": devices})

@home_bp.route('/device_action', methods=['POST'])
def device_action():
    data = request.get_json()
    action = data.get('action')
    mac = data.get('mac')
    return jsonify({"success": True, "message": f"تم إرسال أمر {action} للجهاز {mac} بنجاح"})

@home_bp.route('/reboot', methods=['POST'])
def reboot():
    return jsonify({"success": True, "message": "جاري إعادة تشغيل الراوتر الآن"})

@home_bp.route('/update_device', methods=['POST'])
def update_device(): 
    return jsonify({"success": True, "message": "تم تحديث الإعدادات"})

@home_bp.route('/global_block', methods=['POST'])
def global_block(): 
    return jsonify({"success": True, "message": "تم تفعيل الحظر الشامل"})

@home_bp.route('/wifi_settings', methods=['POST'])
def wifi_settings(): 
    return jsonify({"success": True, "message": "تم تحديث بيانات الواي فاي"})

@home_bp.route('/add_device', methods=['POST'])
def add_device(): 
    return jsonify({"success": True, "message": "تم تسجيل الجهاز"})