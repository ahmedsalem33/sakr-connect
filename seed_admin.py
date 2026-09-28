import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.auth.security import SecurityManager
# يتشغل على جهاز WIN7 مرة واحدة لو الدخول فشل
# python seed_admin.py
if __name__ == "__main__":
    SecurityManager.create_first_admin()
    print("[OK] admin ensured: sakr_admin / sakr2026!@#")
