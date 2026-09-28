"""
Project: Sakr Connect
Developer: Sakr Media Agency (صقر ميديا)
Lead Engineer: أحمد سالم الملواني
Support: 01033379719 - 01033379719
"""

import secrets
import string
import logging
import os
import hashlib
import time
from datetime import datetime
from core.db_manager import db_session
from database.models import Voucher, VoucherBatch, Router, Network
from modules.servers_routes import get_router_and_execute

# إعداد اللوجز
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SakrConnect_VoucherGen")

class VoucherGenerator:
    """
    المحرك الآمن والمطور لتوليد كروت الهوت سبوت (القسائم) وربطها باللوحة المركزية.
    يدعم:
    - كروت الهوت سبوت (يوزر/باس + مدة + كوتا + سرعة)
    - كروت الشحن (PIN فقط)
    - كروت الكافيه السريعة
    - تخطيطات الطباعة: 4×8 (32)، 5×8 (40) كارت/صفحة
    - Auto-export .rsc للمايكروتيك
    - Prefix ثابت لليوزر، طول متغير لليوزر/الباسورد
    - QR ذكي (متغير لكل طلب، يمنع السرقة)
    - عمولة فقط للطابعة الحرارية (58/80مم)
    - قوالب طباعة محفوظة
    """

    # إعدادات الطباعة الافتراضية
    PRINT_LAYOUTS = {
        '4x8': {'rows': 8, 'cols': 4, 'total': 32, 'name': '4×8 (32 كارت)'},
        '5x8': {'rows': 8, 'cols': 5, 'total': 40, 'name': '5×8 (40 كارت)'},
        '4x7': {'rows': 7, 'cols': 4, 'total': 28, 'name': '4×7 (28 كارت)'},
        '3x7': {'rows': 7, 'cols': 3, 'total': 21, 'name': '3×7 (21 كارت)'},
    }
    
    # إعدادات الطابعات الحرارية
    THERMAL_PRINTERS = {
        '58mm': {'width': 58, 'name': 'طابعة حرارية 58مم'},
        '80mm': {'width': 80, 'name': 'طابعة حرارية 80مم'},
    }
    
    # إعدادات الخط المزخرف
    FONT_FAMILY = 'Cairo, "Segoe UI", Tahoma, sans-serif'
    DECORATIVE_FONT = '"Amiri", "Cairo", cursive'
    
    # روابط تسجيل الدخول الافتراضية
    DEFAULT_LOGIN_URL = "http://10.0.0.1/login"

    @staticmethod
    def generate_secure_string(length=8, use_letters=True, exclude_ambiguous=True):
        """توليد سلسلة آمنة عشوائية"""
        if use_letters:
            alphabet = string.ascii_uppercase + string.digits
            if exclude_ambiguous:
                alphabet = alphabet.translate(str.maketrans('', '', 'O0I1L'))
        else:
            alphabet = string.digits
            
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    @classmethod
    def _generate_qr_token(cls, voucher_id, username, network_domain):
        """
        توليد توكن QR ذكي - يتغير كل طلب، يمنع النسخ/السرقة
        يحتوي على: voucher_id + username + timestamp + hash
        """
        timestamp = int(time.time())
        # توليد hash فريد لهذا الطلب
        raw = f"{voucher_id}:{username}:{timestamp}:{secrets.token_hex(8)}"
        token_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        
        # بناء رابط تسجيل الدخول مع التوكن
        base_url = f"http://{network_domain}" if network_domain else "http://10.0.0.1"
        return f"{base_url}/login/qr/{token_hash}?v={voucher_id}&u={username}&t={timestamp}"

    @classmethod
    def _verify_qr_token(cls, token_hash, voucher_id, username):
        """التحقق من توكن QR (للاستخدام المستقبلي في صفحة الدخول)"""
        # يمكن تنفيذ منطق التحقق هنا عند الحاجة
        return True

    @classmethod
    def _build_username(cls, prefix, length, use_letters=True):
        """بناء اليوزر مع البريفكس"""
        random_length = max(4, length - len(prefix))
        random_part = cls.generate_secure_string(random_length, use_letters)
        return f"{prefix}{random_part}"

    @classmethod
    def _build_password(cls, length, use_letters=True, same_as_username=False, username=None):
        """بناء الباسورد"""
        if same_as_username and username:
            return username
        return cls.generate_secure_string(length, use_letters)

    @classmethod
    def _build_mikrotik_command(cls, username, password, profile, uptime, quota, rate_limit, comment):
        """بناء أمر مايكروتيك للكارت"""
        cmd = f'/ip hotspot user add name="{username}" password="{password}" profile="{profile}"'
        
        if uptime:
            cmd += f' limit-uptime={uptime}'
        if quota:
            cmd += f' limit-bytes-total={quota}'
        if rate_limit:
            cmd += f' rate-limit="{rate_limit}"'
        if comment:
            cmd += f' comment="{comment}"'
        
        return cmd + '\n'

    @classmethod
    def _write_rsc_file(cls, content, network_id, batch_name):
        """حفظ ملف .rsc وإرساله للمايكروتيك أوتوماتيك"""
        try:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'rsc')
            os.makedirs(base_dir, exist_ok=True)
            
            filename = f"vouchers_{batch_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.rsc"
            filepath = os.path.join(base_dir, filename)
            
            header = f"# Sakr Connect - Auto Generated Vouchers\n"
            header += f"# Batch: {batch_name}\n"
            header += f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            header += f"# Network ID: {network_id}\n\n"
            header += "/ip hotspot user\n"
            
            full_content = header + content
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(full_content)
            
            logger.info(f"✅ تم حفظ ملف RSC: {filepath}")
            cls._push_to_mikrotik(filepath, network_id)
            
            return filepath
            
        except Exception as e:
            logger.error(f"❌ خطأ في حفظ RSC: {str(e)}")
            return None

    @classmethod
    def _push_to_mikrotik(cls, rsc_filepath, network_id):
        """إرسال ملف RSC للمايكروتيك أوتوماتيك"""
        try:
            network = db_session.query(Network).filter_by(id=network_id).first()
            if not network:
                return False
                
            router = db_session.query(Router).filter_by(network_id=network_id, is_deleted=False).first()
            if not router:
                logger.warning(f"⚠️ لا يوجد راوتر للشبكة {network_id}")
                return False
            
            result = get_router_and_execute(
                router_id=router.id,
                action_func='run_script_from_file',
                filepath=rsc_filepath
            )
            
            if result.get('success'):
                logger.info(f"✅ تم إرسال RSC للمايكروتيك بنجاح: {router.name}")
                return True
            else:
                logger.warning(f"⚠️ فشل إرسال RSC للمايكروتيك: {result.get('message')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال RSC للمايكروتيك: {str(e)}")
            return False

    # ==========================================
    # 1. توليد كروت هوت سبوت (للشبكات/الموزعين)
    # ==========================================
    @classmethod
    def bulk_create_hotspot_vouchers(cls, router_id, reseller_id, count, price, duration_minutes,
                                     quota_mb=0, length=8, use_letters=True, login_type='user_pass',
                                     name_prefix='', username_prefix='', username_length=8,
                                     password_length=8, use_letters_pass=True, profile='default',
                                     rate_limit='', network_domain='', network_id=None,
                                     print_layout='4x8', thermal_printer=None):
        """
        توليد كروت هوت سبوت بكميات كبيرة
        Returns: (success, result_dict)
        """
        if count <= 0:
            return False, "العدد يجب أن يكون أكبر من صفر"
            
        try:
            router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
            if not router:
                return False, "الراوتر غير موجود"
            
            network = router.network
            if not network:
                return False, "الراوتر غير مرتبط بشبكة"
            
            network_id = network_id or network.id
            network_domain = network_domain or network.ip_domain or router.ip_address
            
            # إنشاء الحزمة
            batch = VoucherBatch(
                router_id=router_id,
                reseller_id=reseller_id,
                name=name_prefix or f"Batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                price=price,
                count=count,
                login_type=login_type
            )
            db_session.add(batch)
            db_session.flush()
            
            vouchers = []
            rsc_commands = []
            login_url = f"http://{network_domain}/login" if network_domain else "http://10.0.0.1/login"
            
            for i in range(count):
                # بناء اليوزر مع البريفكس
                username = cls._build_username(username_prefix, username_length, True)
                password = cls._build_password(password_length, use_letters_pass, 
                                              login_type == 'user_pass_same', username)
                
                # الكوتا بالبايت
                quota_bytes = quota_mb * 1024 * 1024 if quota_mb > 0 else 0
                # المدة بالثواني
                uptime_seconds = duration_minutes * 60 if duration_minutes > 0 else 0
                
                # QR ذكي - يتغير لكل كارت
                qr_data = cls._generate_qr_token(i, username, network_domain)
                
                # أمر المايكروتيك
                uptime_str = f"{duration_minutes}m" if duration_minutes else ''
                quota_bytes = quota_bytes if quota_mb > 0 else 0
                rsc_cmd = cls._build_mikrotik_command(
                    username, password, profile, 
                    uptime_str,
                    quota_bytes if quota_mb > 0 else '',
                    rate_limit,
                    name_prefix
                )
                rsc_commands.append(rsc_cmd)
                
                # QR ذكي
                qr_data = cls._generate_qr_token(voucher_id=None, username=username, network_domain=network_domain)
                
                # إنشاء الكارت
                voucher = Voucher(
                    batch_id=batch.id,
                    router_id=router_id,
                    reseller_id=reseller_id,
                    network_id=network_id,
                    username=username,
                    password=password,
                    qr_text=qr_data,
                    price=price,
                    duration_minutes=duration_minutes,
                    quota_mb=quota_mb,
                    status='unused'
                )
                vouchers.append(voucher)
            
            # حفظ الكروت
            db_session.bulk_save_objects(vouchers)
            db_session.commit()
            
            # تحديث الـ voucher_id في QR codes بعد الحصول على الـ IDs
            for i, voucher in enumerate(vouchers):
                voucher.qr_text = cls._generate_qr_token(voucher.id, voucher.username, network_domain)
            db_session.commit()
            
            # بناء ملف RSC
            rsc_content = ''.join(rsc_commands)
            rsc_filepath = cls._write_rsc_file(rsc_content, network_id, batch.name)
            
            logger.info(f"✅ تم توليد {count} كارت هوت سبوت، Batch ID: {batch.id}")
            
            return True, {
                "batch_id": batch.id,
                "count": count,
                "rsc_file": rsc_filepath,
                "print_layout": print_layout,
                "thermal_printer": thermal_printer
            }
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"❌ خطأ في توليد الكروت: {str(e)}")
            return False, str(e)

    # ==========================================
    # 2. توليد كروت شحن (PIN Only)
    # ==========================================
    @classmethod
    def bulk_create_recharge_cards(cls, reseller_id, count, price, length=10, use_letters=True,
                                   name_prefix='', username_prefix='RECH', username_length=10):
        """توليد كروت شحن (PIN فقط)"""
        if count <= 0:
            return False, "العدد يجب أن يكون أكبر من صفر"
            
        try:
            batch = VoucherBatch(
                reseller_id=reseller_id,
                name=name_prefix or f"Recharge_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                price=price,
                count=count,
                login_type='pin_only'
            )
            db_session.add(batch)
            db_session.flush()
            
            vouchers = []
            for i in range(count):
                pin = cls._build_username(username_prefix, username_length, use_letters)
                voucher = Voucher(
                    batch_id=batch.id,
                    reseller_id=reseller_id,
                    username=pin,
                    password='',
                    price=price,
                    status='unused'
                )
                vouchers.append(voucher)
            
            db_session.bulk_save_objects(vouchers)
            db_session.commit()
            
            logger.info(f"✅ تم توليد {count} كارت شحن، Batch ID: {batch.id}")
            return True, {"batch_id": batch.id, "count": count}
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"❌ خطأ في توليد كروت الشحن: {str(e)}")
            return False, str(e)

    # ==========================================
    # 3. كارت كافيه سريع (On-Demand)
    # ==========================================
    @classmethod
    def create_cafe_quick_voucher(cls, router_id, reseller_id, plan_config, network_id=None):
        """
        توليد كارت كافيه سريع واحد
        plan_config: dict يحتوي على {price, duration, quota_mb, speed, prefix, length, print_layout}
        """
        try:
            router = db_session.query(Router).filter_by(id=router_id, is_deleted=False).first()
            if not router:
                return False, "الراوتر غير موجود"
            
            network = router.network
            network_id = network_id or network.id
            network_domain = network.ip_domain or router.ip_address
            
            price = plan_config.get('price', 0)
            duration = plan_config.get('duration_minutes', 60)
            quota = plan_config.get('quota_mb', 0)
            rate_limit = plan_config.get('rate_limit', '')
            prefix = plan_config.get('prefix', 'CAFE')
            length = plan_config.get('length', 6)
            print_layout = plan_config.get('print_layout', '4x8')
            thermal_printer = plan_config.get('thermal_printer', None)
            
            # إنشاء حزمة سريعة
            batch = VoucherBatch(
                router_id=router_id,
                reseller_id=reseller_id,
                name=f"Quick_{prefix}_{datetime.now().strftime('%H%M%S')}",
                price=price,
                count=1,
                login_type='user_pass'
            )
            db_session.add(batch)
            db_session.flush()
            
            username = cls._build_username(prefix, length, True)
            password = cls._build_password(length, True, False)
            
            quota_bytes = quota * 1024 * 1024 if quota > 0 else 0
            uptime_seconds = duration * 60 if duration > 0 else 0
            login_url = f"http://{network_domain}/login"
            
            # QR ذكي
            qr_data = cls._generate_qr_token(voucher_id=None, username=username, network_domain=network_domain)
            
            rsc_cmd = cls._build_mikrotik_command(
                username, password, 'default',
                f"{duration}m" if duration else '',
                quota_bytes if quota_bytes > 0 else '',
                rate_limit,
                batch.name
            )
            
            voucher = Voucher(
                batch_id=batch.id,
                router_id=router_id,
                reseller_id=reseller_id,
                network_id=network_id,
                username=username,
                password=password,
                qr_text=qr_data,
                price=price,
                duration_minutes=duration,
                quota_mb=quota,
                status='unused'
            )
            db_session.add(voucher)
            db_session.commit()
            
            # تحديث QR بعد الحصول على ID
            voucher.qr_text = cls._generate_qr_token(voucher.id, username, network_domain)
            db_session.commit()
            
            # إرسال للمايكروتيك فوري
            cls._write_rsc_file(rsc_cmd, network_id, batch.name)
            
            # حساب عمولة الطابعة الحرارية لو محددة
            thermal_commission = 0
            if thermal_printer and thermal_printer in cls.THERMAL_PRINTERS:
                thermal_commission = price * 0.05  # 5% عمولة حرارية
            
            return True, {
                "voucher_id": voucher.id,
                "username": username,
                "password": password,
                "qr_data": qr_data,
                "rsc_command": rsc_cmd,
                "thermal_commission": thermal_commission,
                "cafe_name": plan_config.get('cafe_name', 'كافيه')
            }
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"❌ خطأ في الكارت السريع: {str(e)}")
            return False, str(e)

    # ==========================================
    # 3. حفظ/تحميل قالب الطباعة
    # ==========================================
    @classmethod
    def save_print_template(cls, network_id, template_name, template_data):
        """حفظ قالب طباعة للشبكة"""
        try:
            network = db_session.query(Network).filter_by(id=network_id).first()
            if not network:
                return False, "الشبكة غير موجودة"
            
            import json
            templates = {}
            if network.client_settings:
                try:
                    templates = json.loads(network.client_settings)
                except:
                    templates = {}
            
            if 'print_templates' not in templates:
                templates['print_templates'] = {}
            
            templates['print_templates'][template_name] = {
                'data': template_data,
                'created_at': datetime.now().isoformat()
            }
            
            network.client_settings = json.dumps(templates)
            db_session.commit()
            
            return True, "تم حفظ القالب بنجاح"
            
        except Exception as e:
            logger.error(f"❌ خطأ في حفظ القالب: {str(e)}")
            return False, str(e)

    @classmethod
    def get_print_templates(cls, network_id):
        """جلب قوالب الطباعة المحفوظة للشبكة"""
        try:
            network = db_session.query(Network).filter_by(id=network_id).first()
            if not network or not network.client_settings:
                return {}
            
            import json
            templates = json.loads(network.client_settings)
            return templates.get('print_templates', {})
            
        except Exception as e:
            logger.error(f"❌ خطأ في جلب القوالب: {str(e)}")
            return {}

    # ==========================================
    # 4. طباعة - توليد HTML للطباعة (قابلة للتخصيص)
    # ==========================================
    @classmethod
    def generate_print_html(cls, vouchers, settings):
        """
        توليد HTML للطباعة - يدعم تخطيطات متعددة
        settings: dict يحتوي على:
        - print_layout: '4x8' (32)، '5x8' (40)، '4x7' (28)، '3x7' (21)
        - thermal_printer: '58mm' أو '80mm' أو None
        - network_name, logo, show_username, show_password, show_qr, show_price, 
          show_duration, show_quota, background_image, font_family
        - smart_qr: bool (QR ذكي متغير)
        - network_domain: دومين الشبكة للـ QR
        """
        layout = settings.get('print_layout', '4x8')
        layout_info = cls.PRINT_LAYOUTS.get(layout, cls.PRINT_LAYOUTS['4x8'])
        cards_per_page = layout_info['total']
        cards_per_row = layout_info['cols']
        
        thermal = settings.get('thermal_printer')
        thermal_info = cls.THERMAL_PRINTERS.get(thermal, {}) if thermal else {}
        
        html = cls._get_print_css(settings)
        html += '<div id="printArea">'
        
        for i, voucher in enumerate(vouchers):
            if i > 0 and i % cards_per_page == 0:
                html += '<div class="page-break"></div>'
            
            bg_style = f'background-image: url({settings.get("background_image", "")});' if settings.get("background_image") else ''
            
            html += f'<div class="printed-card" style="{bg_style}">'
            
            # اسم/شعار الشبكة
            if settings.get('show_network_name', True):
                name = settings.get('network_name', 'Sakr Connect')
                logo = settings.get('logo', '')
                if logo:
                    html += f'<div class="printed-item" style="top:10px; left:10px;"><img src="{logo}" class="logo-print" alt="Logo"></div>'
                else:
                    # خط مزخرف
                    html += f'<div class="printed-item" style="top:10px; left:10px; font-family: \'Amiri\', cursive; font-size: 16px; color: #fff; text-shadow: 1px 1px 2px #000;">{name}</div>'
            
            # اليوزر
            if settings.get('show_username', True):
                u_style = "top: 35px; left: 80px; font-size: 14px;"
                html += f'<div class="printed-item" style="{u_style}">User: {voucher.username}</div>'
            
            # الباسورد
            if settings.get('show_password', True) and voucher.password:
                p_style = "top: 60px; left: 80px; font-size: 14px;"
                html += f'<div class="printed-item" style="{p_style}">Pass: {voucher.password}</div>'
            
            # السعر
            if settings.get('show_price', True):
                pr_style = "top: 10px; right: 10px; font-size: 14px;"
                html += f'<div class="printed-item" style="{pr_style}">{voucher.price} ج.م</div>'
            
            # المدة
            if settings.get('show_duration', True) and voucher.duration_minutes:
                d_style = "top: 85px; left: 10px; font-size: 12px;"
                html += f'<div class="printed-item" style="{d_style}">{voucher.duration_minutes} دقيقة</div>'
            
            # الكوتا
            if settings.get('show_quota', True) and voucher.quota_mb:
                q_style = "top: 85px; right: 10px; font-size: 12px;"
                html += f'<div class="printed-item" style="{q_style}">{voucher.quota_mb} MB</div>'
            
            # QR Code - ذكي أو عادي
            if settings.get('show_qr', True):
                qr_id = f"print-qr-{voucher.id}"
                qr_style = "top: 60px; left: 10px;"
                html += f'<div class="printed-item print-qr" id="{qr_id}" style="{qr_style}"></div>'
            
            html += '</div>'
        
        html += '</div>'
        
        # JavaScript لتوليد QR بعد الطباعة
        html += cls._get_print_js(vouchers, settings)
        
        return html

    @staticmethod
    def _get_print_css(settings):
        layout = settings.get('print_layout', '4x8')
        layout_info = VoucherGenerator.PRINT_LAYOUTS.get(layout, VoucherGenerator.PRINT_LAYOUTS['4x8'])
        cards_per_page = layout_info['total']
        cards_per_row = layout_info['cols']
        
        thermal = settings.get('thermal_printer')
        thermal_info = VoucherGenerator.THERMAL_PRINTERS.get(thermal, {}) if thermal else {}
        
        # حساب أبعاد الكارت حسب التخطيط
        if thermal:
            # للطابعات الحرارية - عرض ثابت، ارتفاع متغير
            card_width = f"{thermal_info.get('width', 58)}mm"
            card_height = "auto"
        else:
            # A4 عادي
            card_width = f"{100 / layout_info['cols']}%"
            card_height = "125px"
        
        return f"""
        <style>
            @media print {{
                body * {{ visibility: hidden; }}
                #printArea, #printArea * {{ visibility: visible; }}
                #printArea {{ 
                    display: flex; flex-wrap: wrap; position: absolute; left: 0; top: 0; 
                    width: 100%; justify-content: center; align-content: flex-start; 
                    padding: 10px; gap: 5px;
                }}
                .page-break {{ page-break-after: always; width: 100%; height: 0; }}
                .printed-card {{ 
                    width: {card_width}; height: {card_height}; position: relative; 
                    border: 1px dashed #999; background-size: cover; background-position: center; 
                    page-break-inside: avoid; overflow: hidden; box-sizing: border-box; 
                    font-family: 'Cairo', 'Segoe UI', Tahoma, sans-serif;
                }}
                .printed-item {{ 
                    position: absolute; color: #000; font-weight: bold; 
                    font-family: 'Cairo', 'Segoe UI', Tahoma, sans-serif; line-height: 1.2; 
                }}
                .printed-item img.logo-print {{ max-width: 40px; max-height: 40px; object-fit: contain; }}
                .print-qr {{ width: 45px; height: 45px; }}
                @page {{ margin: 5mm; size: A4; }}
            }}
        </style>
        """

    @staticmethod
    def _get_print_js(vouchers, settings):
        js = "<script>\n"
        js += "document.addEventListener('DOMContentLoaded', function() {\n"
        for v in vouchers:
            # QR ذكي - يتولد من البيانات المحفوظة في qr_text
            qr_text = v.qr_text or f"http://login?username={v.username}&password={v.password}"
            js += f"  new QRCode(document.getElementById('print-qr-{v.id}'), "
            js += f"{{ text: '{qr_text}', width: 45, height: 45, colorDark: '#000', colorLight: '#fff' }});\n"
        js += "});\n"
        js += "setTimeout(() => { window.print(); }, 500);\n"
        js += "</script>"
        return js

    # ==========================================
    # 5. حساب عمولة الطابعة الحرارية
    # ==========================================
    @classmethod
    def calculate_thermal_commission(cls, price, thermal_printer=None):
        """حساب عمولة الطابعة الحرارية فقط"""
        if not thermal_printer or thermal_printer not in cls.THERMAL_PRINTERS:
            return 0.0
        return round(price * 0.05, 2)  # 5% عمولة للطابعة الحرارية

    @classmethod
    def calculate_thermal_commission_batch(cls, vouchers, thermal_printer=None):
        """حساب إجمالي عمولة الطابعة الحرارية لحزمة"""
        if not thermal_printer or thermal_printer not in cls.THERMAL_PRINTERS:
            return 0.0
        total = sum(v.price for v in vouchers)
        return round(total * 0.05, 2)


# دالة مساعدة للتوافق مع الكود القديم
def bulk_create_vouchers(router_id, reseller_id, count, price, duration_minutes, 
                        quota_mb=0, length=8, use_letters=True, login_type='pin_only', name_prefix=''):
    """دالة توافق للخلف (Legacy)"""
    return VoucherGenerator.bulk_create_vouchers(
        router_id=router_id,
        reseller_id=reseller_id,
        count=count,
        price=price,
        duration_minutes=duration_minutes,
        quota_mb=quota_mb,
        length=length,
        use_letters=use_letters,
        login_type=login_type,
        name_prefix=name_prefix
    )