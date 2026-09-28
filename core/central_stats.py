"""
Project: Sakr Connect
Central live stats builder (single source for all dashboards).
All values are read live from the database - zero hardcoding.
Every block is guarded: any failure degrades to 0/empty, never 500.
"""

from datetime import datetime, timedelta


def build_central_stats():
    from sqlalchemy import func as _func
    from core.db_manager import db_session
    from database.models import (
        User, Subscriber, Router, Network,
        ActiveSession, AuditLog, Voucher, FinancialTransaction,
    )

    stats = {
        'cpu': None, 'ram': None, 'db_ms': None,
        'routers_total': 0, 'routers_online': 0,
        'home_total': 0, 'home_online': 0,
        'cafe_total': 0, 'net_total': 0,
        'vouchers_total': 0, 'vouchers_today': 0,
        'sessions_now': 0,
        'revenue_today': 0.0, 'revenue_total': 0.0,
        'balances_total': 0.0, 'debts_total': 0.0,
        'alerts_total': 0,
        'top_network': 'لا توجد شبكات بعد',
        'v_days': [], 'v_counts': [],
        'r_days': [], 'r_sums': [],
        'live_logs': [],
    }
    try:
        try:
            import psutil as _psutil
            stats['cpu'] = int(_psutil.cpu_percent(interval=None))
            stats['ram'] = int(_psutil.virtual_memory().percent)
        except Exception:
            pass

        try:
            import time as _time
            _t0 = _time.time()
            db_session.query(User.id).first()
            stats['db_ms'] = int((_time.time() - _t0) * 1000)
        except Exception:
            pass

        stats['routers_total'] = db_session.query(Router).count()
        active_router_ids = set(
            r[0] for r in db_session.query(ActiveSession.router_id).distinct().all() if r[0]
        )
        if active_router_ids:
            stats['routers_online'] = db_session.query(Router).filter(
                Router.id.in_(list(active_router_ids))).count()
        stats['sessions_now'] = db_session.query(ActiveSession).count()

        stats['home_total'] = db_session.query(Subscriber).filter_by(sub_type='home').count()
        stats['home_online'] = db_session.query(ActiveSession).filter_by(type='pppoe').count()
        stats['cafe_total'] = db_session.query(User).filter_by(role='cafe').count()
        stats['net_total'] = db_session.query(User).filter(User.role.in_(['network', 'reseller'])).count()

        stats['vouchers_total'] = db_session.query(Voucher).count()
        _today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            stats['vouchers_today'] = db_session.query(Voucher).filter(
                Voucher.created_at >= _today).count()
        except Exception:
            pass

        try:
            stats['revenue_today'] = float(db_session.query(
                _func.coalesce(_func.sum(FinancialTransaction.amount), 0)).filter(
                    FinancialTransaction.created_at >= _today,
                    FinancialTransaction.payment_status == 'paid').scalar() or 0)
            stats['revenue_total'] = float(db_session.query(
                _func.coalesce(_func.sum(FinancialTransaction.amount), 0)).filter(
                    FinancialTransaction.payment_status == 'paid').scalar() or 0)
        except Exception:
            pass
        try:
            stats['balances_total'] = float(db_session.query(
                _func.coalesce(_func.sum(User.current_balance), 0)).filter(
                    User.role.notin_(['admin', 'super_admin'])).scalar() or 0)
            stats['debts_total'] = float(db_session.query(
                _func.coalesce(_func.sum(User.debt), 0)).filter(
                    User.role.notin_(['admin', 'super_admin'])).scalar() or 0)
        except Exception:
            pass
        try:
            stats['alerts_total'] = db_session.query(AuditLog).filter(
                AuditLog.action.in_(['login_failed', 'admin_login_failed', 'blocked_login'])).count()
        except Exception:
            pass

        try:
            best_name, best_n = 'لا توجد شبكات بعد', 0
            for _n in db_session.query(Network).all():
                _c = db_session.query(Subscriber).filter_by(network_id=_n.id).count()
                if _c > best_n:
                    best_name, best_n = _n.name, _c
            if best_n > 0:
                stats['top_network'] = '{} ({} مشترك)'.format(best_name, best_n)
        except Exception:
            pass

        try:
            rows = db_session.query(
                _func.date(Voucher.created_at), _func.count(Voucher.id)
            ).filter(Voucher.created_at >= datetime.utcnow() - timedelta(days=6)
            ).group_by(_func.date(Voucher.created_at)
            ).order_by(_func.date(Voucher.created_at)).all()
            stats['v_days'] = [str(r[0]) for r in rows]
            stats['v_counts'] = [int(r[1]) for r in rows]
        except Exception:
            pass
        try:
            rows = db_session.query(
                _func.date(FinancialTransaction.created_at),
                _func.coalesce(_func.sum(FinancialTransaction.amount), 0)
            ).filter(FinancialTransaction.created_at >= datetime.utcnow() - timedelta(days=9),
                     FinancialTransaction.payment_status == 'paid'
            ).group_by(_func.date(FinancialTransaction.created_at)
            ).order_by(_func.date(FinancialTransaction.created_at)).all()
            stats['r_days'] = [str(r[0]) for r in rows]
            stats['r_sums'] = [float(r[1] or 0) for r in rows]
        except Exception:
            pass

        try:
            for _l in db_session.query(AuditLog).order_by(AuditLog.id.desc()).limit(12).all():
                _ts = getattr(_l, 'timestamp', None)
                stats['live_logs'].append({
                    'time': _ts.strftime('%H:%M:%S') if _ts else '#{}'.format(_l.id),
                    'action': _l.action or '',
                    'code': _l.code or '',
                })
        except Exception:
            pass
    except Exception as e:
        print('build_central_stats error: {}'.format(e))

    return stats
