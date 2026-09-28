import logging
import routeros_api
from core.config import Config

# إعداد نظام تسجيل ومراقبة أوامر المايكروتيك
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SakrConnect_MikroTik")

class MikrotikHandler:
    """
    العقل المدبر للتحكم اللحظي في أجهزة المايكروتيك.
    يقوم بالاتصال عبر الـ API لإرسال أوامر الفصل، التحديد، والحظر دون الحاجة لفتح Winbox.
    كما يحتوي على دوال سحب البيانات اللحظية لتغذية عدادات لوحة التحكم.
    """
    def __init__(self, host, username, password, port=None):
        self.host = host
        self.username = username
        self.password = password
        self.port = port or Config.MK_API_PORT
        self.connection = None
        self.api = None

    def connect(self):
        """تأسيس الاتصال الآمن مع راوتر المايكروتيك"""
        try:
            # استخدام RouterOsApiPool لضمان ثبات الاتصال وعدم تقطعه
            self.connection = routeros_api.RouterOsApiPool(
                self.host,
                username=self.username,
                password=self.password,
                port=self.port,
                plaintext_login=True
            )
            self.api = self.connection.get_api()
            logger.info(f"✅ تم الاتصال بنجاح بسيرفر المايكروتيك: {self.host}")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بالمايكروتيك {self.host}: {str(e)}")
            return False

    def disconnect(self):
        """إنهاء الاتصال وتنظيف الذاكرة"""
        if self.connection:
            self.connection.disconnect()
            logger.info(f"تم إنهاء الاتصال بالمايكروتيك ({self.host}) بأمان.")

    # ==========================================
    # دعم مدير السياق (Context Manager) لفتح وإغلاق الاتصال تلقائياً
    # ==========================================
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    # ==========================================
    # دوال التحكم في الهوت سبوت (الكافيهات والشبكات وإدارتها)
    # ==========================================
    def kick_hotspot_user(self, username):
        """طرد مستخدم هوت سبوت نشط فوراً (يُستخدم عند انتهاء باقة الكارت أو إعادة التوجيه)"""
        if not self.api: return False
        try:
            active_users = self.api.get_resource('/ip/hotspot/active')
            users = active_users.get(user=username)
            for u in users:
                active_users.remove(id=u['id'])
            logger.info(f"تم طرد مستخدم الهوت سبوت: {username}")
            return True
        except Exception as e:
            logger.error(f"خطأ أثناء طرد مستخدم الهوت سبوت {username}: {str(e)}")
            return False

    def change_hotspot_profile(self, username, new_profile):
        """
        تغيير بروفايل كارت الهوت سبوت (لتقييد الصلاحيات وتوجيهه لصفحة انتهاء الباقة بدل حذفه)
        """
        if not self.api: return False
        try:
            users_resource = self.api.get_resource('/ip/hotspot/user')
            users = users_resource.get(name=username)
            if users:
                users_resource.set(id=users[0]['id'], profile=new_profile)
                logger.info(f"⚙️ تم تحويل كارت الهوت سبوت {username} إلى البروفايل المقيد: {new_profile}")
                # طرد الجلسة الحالية ليجبره الراوتر على سحب البروفايل الجديد والتوجه لصفحة التنبيه
                self.kick_hotspot_user(username)
                return True
            return False
        except Exception as e:
            logger.error(f"خطأ أثناء تغيير بروفايل كارت الهوت سبوت {username}: {str(e)}")
            return False

    def reset_hotspot_mac(self, username):
        """
        [تحكم يدوي] فك ارتباط الماك أدرس (MAC Address) عن الكارت
        يُستخدم عندما يريد المشترك تشغيل الكارت على جهاز أو موبايل آخر.
        """
        if not self.api: return False
        try:
            users_resource = self.api.get_resource('/ip/hotspot/user')
            users = users_resource.get(name=username)
            if users:
                # تصفير حقل الماك أدرس في المايكروتيك لجعله متاحاً لأي جهاز جديد
                users_resource.set(id=users[0]['id'], **{'mac-address': '00:00:00:00:00:00'})
                logger.info(f"🔓 [تحكم يدوي] تم فك ارتباط الماك أدرس بنجاح للكارت: {username}")
                return True
            return False
        except Exception as e:
            logger.error(f"خطأ أثناء فك ارتباط الماك أدرس للكارت {username}: {str(e)}")
            return False

    def clear_zombies(self):
        """
        [تحكم يدوي وأوتوماتيكي] تنظيف الجلسات المعلقة (Zombie Sessions)
        يقوم بمسح الجلسات النشطة التي فقدت اتصالها الفعلي بالواي فاي لتوفير موارد السيرفر وحماية وقت الكروت.
        """
        if not self.api: return False
        try:
            active_resource = self.api.get_resource('/ip/hotspot/active')
            active_users = active_resource.get()
            cleared_count = 0
            
            for user in active_users:
                # الجلسات المعلقة غالباً تكون بلا حركة مرور أو تجاوزت الـ idle-time المتوقع
                # هنا نقوم بإنهاء الجلسات التي يحددها النظام كجلسات معلقة لتحديث جدول الإحصائيات
                if user.get('idle-time') and 'm' in user.get('idle-time'):  # مثال كشف الخمول
                    active_resource.remove(id=user['id'])
                    cleared_count += 1
            
            logger.info(f"🧹 تم تنظيف وتصفير {cleared_count} جلسة معلقة (Zombie) في السيرفر.")
            return True
        except Exception as e:
            logger.error(f"خطأ أثناء تنظيف الجلسات المعلقة بالسيرفر: {str(e)}")
            return False

    # ==========================================
    # دوال التحكم في البرودباند وعملاء الإدارة (المنازل)
    # ==========================================
    def kick_pppoe_user(self, username):
        """طرد مستخدم برودباند نشط (لقطع الخدمة أو تطبيق سرعة جديدة)"""
        if not self.api: return False
        try:
            active_users = self.api.get_resource('/ppp/active')
            users = active_users.get(name=username)
            for u in users:
                active_users.remove(id=u['id'])
            logger.info(f"تم طرد مستخدم البرودباند: {username}")
            return True
        except Exception as e:
            logger.error(f"خطأ أثناء طرد مستخدم البرودباند {username}: {str(e)}")
            return False

    def change_pppoe_profile(self, username, new_profile):
        """تغيير سرعة المشترك المنزلي برمجياً عبر تغيير الـ Profile دون حذف بياناته"""
        if not self.api: return False
        try:
            secrets = self.api.get_resource('/ppp/secret')
            users = secrets.get(name=username)
            if users:
                secrets.set(id=users[0]['id'], profile=new_profile)
                logger.info(f"تم تعديل باقة المستخدم {username} إلى السرعة: {new_profile}")
                # طرد المستخدم ليقوم الراوتر الخاص به بإعادة الاتصال وسحب السرعة الجديدة فوراً
                self.kick_pppoe_user(username)
                return True
            return False
        except Exception as e:
            logger.error(f"خطأ أثناء تعديل سرعة {username}: {str(e)}")
            return False

    # ==========================================
    # دوال الحماية والأمان (Firewall & Security)
    # ==========================================
    def block_mac_address(self, mac_address, comment="Blocked by Sakr Connect System"):
        """عزل وحظر ماك أدرس تماماً من الشبكة (لمنع الهكرز أو سارقي الخدمة)"""
        if not self.api: return False
        try:
            firewall = self.api.get_resource('/ip/firewall/filter')
            firewall.add(
                chain='forward',
                src_mac_address=mac_address,
                action='drop',
                comment=comment
            )
            logger.info(f"تم حظر الماك أدرس نهائياً: {mac_address}")
            return True
        except Exception as e:
            logger.error(f"خطأ أثناء حظر الماك أدرس {mac_address}: {str(e)}")
            return False

    # ==========================================
    # دوال المراقبة والعدادات اللحظية (Monitoring) للوحة التحكم
    # ==========================================
    def get_system_resources(self):
        """جلب بيانات استهلاك المعالج (CPU) والذاكرة (RAM) والقرص (Disk) وتحديث العدادات"""
        if not self.api: return None
        try:
            resource = self.api.get_resource('/system/resource').get()[0]
            
            # حساب نسبة استهلاك الرامات
            total_memory = int(resource.get('total-memory', 1))
            free_memory = int(resource.get('free-memory', 0))
            used_memory_percent = ((total_memory - free_memory) / total_memory) * 100

            # حساب نسبة استهلاك القرص
            total_hdd = int(resource.get('total-hdd-space', 1))
            free_hdd = int(resource.get('free-hdd-space', 0))
            used_hdd_percent = ((total_hdd - free_hdd) / total_hdd) * 100

            data = {
                "cpu_load": float(resource.get('cpu-load', 0)),
                "ram_usage_percent": round(used_memory_percent, 1),
                "disk_usage_percent": round(used_hdd_percent, 1),
                "uptime": resource.get('uptime', '0s'),
                "board_name": resource.get('board-name', 'Unknown')
            }
            return data
        except Exception as e:
            logger.error(f"خطأ أثناء جلب موارد النظام: {str(e)}")
            return None

    def get_active_users_count(self):
        """جلب إجمالي عدد المستخدمين النشطين (هوت سبوت + برودباند)"""
        if not self.api: return {"hotspot": 0, "pppoe": 0, "total": 0}
        try:
            hotspot_active = len(self.api.get_resource('/ip/hotspot/active').get())
            pppoe_active = len(self.api.get_resource('/ppp/active').get())
            
            return {
                "hotspot": hotspot_active,
                "pppoe": pppoe_active,
                "total": hotspot_active + pppoe_active
            }
        except Exception as e:
            logger.error(f"خطأ أثناء جلب عدد المتصلين: {str(e)}")
            return {"hotspot": 0, "pppoe": 0, "total": 0}

    def get_active_sessions_details(self):
        """جلب تفاصيل الجلسات الحية (هوت سبوت + برودباند) بدون هارد كود"""
        if not self.api: return []
        try:
            sessions = []
            # هوت سبوت
            try:
                hotspot = self.api.get_resource('/ip/hotspot/active').get()
                for h in hotspot:
                    sessions.append({
                        'username': h.get('user', 'unknown'),
                        'type': 'hotspot',
                        'ip_address': h.get('address', ''),
                        'mac_address': h.get('mac-address', ''),
                        'uptime': h.get('uptime', ''),
                        'server': h.get('server', '')
                    })
            except: pass
            # برودباند
            try:
                ppp = self.api.get_resource('/ppp/active').get()
                for p in ppp:
                    sessions.append({
                        'username': p.get('name', 'unknown'),
                        'type': 'pppoe',
                        'ip_address': p.get('address', ''),
                        'mac_address': p.get('caller-id', ''),
                        'uptime': p.get('uptime', ''),
                        'server': p.get('service', 'pppoe')
                    })
            except: pass
            return sessions
        except Exception as e:
            logger.error(f"خطأ أثناء جلب تفاصيل الجلسات: {str(e)}")
            return []

    def get_interface_traffic(self, interface_name="ether1"):
        """جلب سرعة السحب والرفع اللحظية لـ Interface محدد لقراءة الترافيك الإجمالي وعرضه"""
        if not self.api: return {"rx_mbps": 0, "tx_mbps": 0}
        try:
            traffic_cmd = self.api.get_binary_resource('/interface')
            result = traffic_cmd.call('monitor-traffic', {'interface': interface_name, 'once': 'yes'})[0]
            
            rx_bps = int(result.get('rx-bits-per-second', 0))
            tx_bps = int(result.get('tx-bits-per-second', 0))
            
            rx_mbps = round(rx_bps / 1000000, 2)
            tx_mbps = round(tx_bps / 1000000, 2)
            
            return {"rx_mbps": rx_mbps, "tx_mbps": tx_mbps}
        except Exception as e:
            logger.error(f"خطأ أثناء قراءة الترافيك لـ {interface_name}: {str(e)}")
            return {"rx_mbps": 0, "tx_mbps": 0}

    # ==========================================
    # دوال لوحة مراقبة الخطوط (WAN Lines Monitor)
    # ==========================================
    def get_interfaces(self):
        """
        جلب كل كروت الشبكة + عداداتها في استدعاء واحد (طلب واحد فقط = سريع جداً
        حتى مع 50 كرت). يعيد الاسم، النوع، الحالة، وعدد البايتات المتراكمة rx/tx.
        """
        if not self.api:
            return []
        try:
            rows = self.api.get_resource('/interface').get()
            result = []
            for r in rows:
                name = r.get('name') or ''
                if not name:
                    continue
                itype = (r.get('type') or '').lower()
                # استبعاد الكروت الافتراضية اللي مش خطوط حقيقية
                if itype in ('bridge', 'loopback', 'veth') or name.startswith(('bridge', 'lo', 'veth')):
                    continue
                result.append({
                    'name': name,
                    'type': r.get('type', ''),
                    'comment': r.get('comment', ''),
                    'mac': r.get('mac-address', ''),
                    'mtu': r.get('mtu', ''),
                    'disabled': str(r.get('disabled', 'false')).lower() in ('true', 'yes'),
                    'running': str(r.get('running', 'false')).lower() in ('true', 'yes'),
                    'rx_bytes': int(r.get('rx-byte', 0) or 0),
                    'tx_bytes': int(r.get('tx-byte', 0) or 0),
                })
            return result
        except Exception as e:
            logger.error(f"خطأ أثناء جلب الكروت من {self.host}: {str(e)}")
            return []

    def set_interface_disabled(self, interface_name, disabled):
        """تعطيل أو تفعيل كرت شبكة معين (تحكم في الخط من لوحة الدمج)"""
        if not self.api:
            return False
        try:
            self.api.get_resource('/interface').set(
                numbers=interface_name,
                disabled='yes' if disabled else 'no'
            )
            logger.info(f"تم {'تعطيل' if disabled else 'تفعيل'} الكرت {interface_name} على {self.host}")
            return True
        except Exception as e:
            logger.error(f"فشل تغيير حالة الكرت {interface_name} على {self.host}: {str(e)}")
            return False