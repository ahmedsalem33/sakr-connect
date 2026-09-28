from core.db_manager import db_session
from database.models import User, Subscriber, Router, Network, ActiveSession, Voucher, VoucherBatch

def clean_simulation_data():
    try:
        # البحث عن الحساب الوهمي اللي زرع الداتا
        sim_user = db_session.query(User).filter_by(username='king_network').first()
        
        if not sim_user:
            print("✔️ لم يتم العثور على الحساب الوهمي (king_network). الداتابيز نظيفة.")
            return

        print("⏳ جاري تنظيف البيانات الوهمية (الكروت والمشتركين والشبكة)...")

        # البحث عن شبكة الحساب الوهمي
        sim_net = db_session.query(Network).filter_by(owner_id=sim_user.id).first()
        
        if sim_net:
            # 1. مسح الجلسات الحية والروترات
            routers = db_session.query(Router).filter_by(network_id=sim_net.id).all()
            for r in routers:
                db_session.query(ActiveSession).filter_by(router_id=r.id).delete(synchronize_session=False)
            db_session.query(Router).filter_by(network_id=sim_net.id).delete(synchronize_session=False)
            
            # 2. مسح المشتركين الوهميين
            db_session.query(Subscriber).filter_by(network_id=sim_net.id).delete(synchronize_session=False)

        # 3. مسح الكروت الوهمية (Vouchers) ومجموعاتها
        batches = db_session.query(VoucherBatch).filter_by(reseller_id=sim_user.id).all()
        for b in batches:
            db_session.query(Voucher).filter_by(batch_id=b.id).delete(synchronize_session=False)
        db_session.query(VoucherBatch).filter_by(reseller_id=sim_user.id).delete(synchronize_session=False)

        # 4. مسح الشبكة والحساب
        if sim_net:
            db_session.delete(sim_net)
            
        db_session.delete(sim_user)
        
        # حفظ التعديلات
        db_session.commit()
        print("✅ تم مسح جميع البيانات الوهمية بنجاح! العدادات هترجع أصفار دلوقتي.")

    except Exception as e:
        db_session.rollback()
        print(f"❌ حدث خطأ أثناء التنظيف: {e}")

if __name__ == "__main__":
    clean_simulation_data()