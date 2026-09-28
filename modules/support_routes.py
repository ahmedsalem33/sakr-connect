import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, abort
from core.db_manager import db_session
from database.models import Ticket, TicketReply, Subscriber, User

# ==============================================================================
# SAKR CONNECT - SUPPORT MODULE (نظام التذاكر والدعم الفني)
# حقوق النشر: تُسجل باسم المشروع
# حقوق المطور: Sakr Media Agency (صقر ميديا)
# الدعم الفني: 01033379719 - 01033379719
# العنوان: 
# ==============================================================================

support_bp = Blueprint('support', __name__)

# ------------------------------------------------------------------------------
# 1. مسارات العميل (المشتركين والموزعين)
# ------------------------------------------------------------------------------

@support_bp.route('/support', methods=['GET', 'POST'])
def user_support():
    user_id = session.get('user_id')
    user_type = session.get('role') # 'home', 'cafe', أو 'network'
    
    if not user_id:
        return redirect(url_for('dev_login', role='home'))

    if request.method == 'POST':
        # استقبال طلب فتح تذكرة جديدة من العميل
        subject = request.form.get('subject')
        priority = request.form.get('priority', 'normal')
        message = request.form.get('message')
        
        if subject and message:
            new_ticket = Ticket(
                user_id=user_id,
                user_type=user_type,
                subject=subject,
                priority=priority,
                status='open'
            )
            db_session.add(new_ticket)
            db_session.commit()
            
            # إضافة الرسالة الأولى كـ Reply تابع للتذكرة
            initial_reply = TicketReply(
                ticket_id=new_ticket.id,
                sender_type='user',
                message=message
            )
            db_session.add(initial_reply)
            db_session.commit()
            
            return redirect(url_for('support.user_support'))

    # جلب التذاكر الخاصة بهذا العميل فقط
    tickets = db_session.query(Ticket).filter_by(user_id=user_id, user_type=user_type).order_by(Ticket.created_at.desc()).all()
    return render_template('user_support.html', tickets=tickets)


@support_bp.route('/support/ticket/<int:ticket_id>', methods=['GET', 'POST'])
def view_ticket_user(ticket_id):
    user_id = session.get('user_id')
    user_type = session.get('role')
    
    if not user_id:
        return redirect(url_for('dev_login', role='home'))
        
    ticket = db_session.query(Ticket).filter_by(id=ticket_id, user_id=user_id, user_type=user_type).first()
    if not ticket:
        abort(404)

    if request.method == 'POST' and ticket.status != 'closed':
        # إضافة رد جديد من العميل
        message = request.form.get('message')
        if message:
            new_reply = TicketReply(
                ticket_id=ticket.id,
                sender_type='user',
                message=message
            )
            # إعادة فتح التذكرة تلقائياً إذا كانت قيد المراجعة ورد العميل
            if ticket.status == 'in_progress':
                ticket.status = 'open'
                
            db_session.add(new_reply)
            db_session.commit()
            return redirect(url_for('support.view_ticket_user', ticket_id=ticket.id))

    replies = db_session.query(TicketReply).filter_by(ticket_id=ticket.id).order_by(TicketReply.created_at.asc()).all()
    return render_template('user_ticket_view.html', ticket=ticket, replies=replies)


# ------------------------------------------------------------------------------
# 2. مسارات الإدارة المركزية (الأدمن)
# ------------------------------------------------------------------------------

@support_bp.route('/admin/support', methods=['GET'])
def admin_support():
    if session.get('role') != 'admin':
        abort(403)
        
    # جلب كافة التذاكر من جميع العملاء للإدارة المركزية
    tickets = db_session.query(Ticket).order_by(
        # ترتيب التذاكر المفتوحة أولاً ثم الأحدث
        Ticket.status == 'open', 
        Ticket.created_at.desc()
    ).all()
    
    return render_template('admin_support.html', tickets=tickets)


@support_bp.route('/admin/support/ticket/<int:ticket_id>', methods=['GET', 'POST'])
def admin_manage_ticket(ticket_id):
    if session.get('role') != 'admin':
        abort(403)
        
    ticket = db_session.query(Ticket).filter_by(id=ticket_id).first()
    if not ticket:
        abort(404)

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'reply':
            # الإدارة ترد على العميل
            message = request.form.get('message')
            if message:
                new_reply = TicketReply(
                    ticket_id=ticket.id,
                    sender_type='admin',
                    message=message
                )
                ticket.status = 'in_progress' # تحويل الحالة لقيد المراجعة بمجرد رد الإدارة
                db_session.add(new_reply)
                db_session.commit()
                
        elif action == 'close':
            # الإدارة تغلق التذكرة
            ticket.status = 'closed'
            db_session.commit()
            return redirect(url_for('support.admin_support'))
            
        return redirect(url_for('support.admin_manage_ticket', ticket_id=ticket.id))

    replies = db_session.query(TicketReply).filter_by(ticket_id=ticket.id).order_by(TicketReply.created_at.asc()).all()
    
    # جلب بيانات العميل صاحب التذكرة للعرض في لوحة الإدارة
    client_name = "غير معروف"
    if ticket.user_type in ['home', 'cafe']:
        client = db_session.query(Subscriber).filter_by(id=ticket.user_id).first()
        if client: client_name = client.username
    elif ticket.user_type == 'network':
        client = db_session.query(User).filter_by(id=ticket.user_id).first()
        if client: client_name = client.fullname

    return render_template('admin_ticket_view.html', ticket=ticket, replies=replies, client_name=client_name)