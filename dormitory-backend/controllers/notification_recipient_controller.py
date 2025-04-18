from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions  import db
from models.notification_recipient import NotificationRecipient
from models.notification import Notification
from models.contract import Contract
from models.notification_media import NotificationMedia
from controllers.auth_controller import user_required
from datetime import datetime

notification_recipient_bp = Blueprint('notification_recipient', __name__)

# GetPersonalNotifications / GetMyNotifications (User)
@notification_recipient_bp.route('/me/notifications', methods=['GET'])
@user_required()
def get_user_notifications():
    identity = get_jwt_identity()  # This is the user_id (string or integer)
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    is_read = request.args.get('is_read', type=bool)

    # Lấy thông báo riêng
    query = (
        NotificationRecipient.query
        .join(Contract, NotificationRecipient.user_id == Contract.user_id)
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == identity)
        .filter(Contract.start_date <= Notification.created_at)  # Only notifications after contract start_date
        .filter(Contract.status.in_(['PENDING', 'ACTIVE']))  # Only active or pending contracts
    )

    if is_read is not None:
        query = query.filter(NotificationRecipient.is_read == is_read)

    personal_notifications = query.paginate(page=page, per_page=limit)

    # Lấy thông báo chung (ALL)
    public_query = (
        Notification.query
        .join(Contract, Contract.user_id == identity)
        .filter(Notification.target_type == 'ALL')
        .filter(Contract.start_date <= Notification.created_at)  # Only notifications after contract start_date
        .filter(Contract.status.in_(['PENDING', 'ACTIVE']))  # Only active or pending contracts
    )

    public_notifications = public_query.all()

    return jsonify({
        'personal_notifications': [notification.to_dict() for notification in personal_notifications.items],
        'public_notifications': [notification.to_dict() for notification in public_notifications],
        'personal_total': personal_notifications.total,
        'personal_pages': personal_notifications.pages,
        'personal_current_page': personal_notifications.page
    }), 200

# MarkNotificationAsRead (User)
@notification_recipient_bp.route('/me/notifications/<int:recipient_id>', methods=['PUT'])
@user_required()
def mark_notification_as_read(recipient_id):
    identity = get_jwt_identity()
    recipient = NotificationRecipient.query.get(recipient_id)
    if not recipient:
        return jsonify({'message': 'Không tìm thấy thông báo'}), 404
    if recipient.user_id != identity['id']:
        return jsonify({'message': 'Bạn không có quyền chỉnh sửa thông báo này'}), 403

    recipient.is_read = True
    recipient.read_at = datetime.utcnow()
    db.session.commit()
    return jsonify(recipient.to_dict()), 200

# MarkAllNotificationsAsRead (User)
@notification_recipient_bp.route('/me/notifications/mark-all-read', methods=['PUT'])
@user_required()
def mark_all_notifications_as_read():
    identity = get_jwt_identity()
    recipients = (
        NotificationRecipient.query
        .join(Contract, NotificationRecipient.user_id == Contract.user_id)
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == identity, NotificationRecipient.is_read == False)
        .filter(Contract.start_date <= Notification.created_at)  # Only notifications after contract start_date
        .filter(Contract.status.in_(['PENDING', 'ACTIVE']))  # Only active or pending contracts
        .all()
    )

    for recipient in recipients:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()

    db.session.commit()
    return jsonify({'message': 'Đánh dấu tất cả thông báo là đã đọc'}), 200

# GetUnreadNotificationsCount (User)
@notification_recipient_bp.route('/me/notifications/unread-count', methods=['GET'])
@user_required()
def get_unread_notifications_count():
    identity = get_jwt_identity()
    count = (
        NotificationRecipient.query
        .join(Contract, NotificationRecipient.user_id == Contract.user_id)
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == identity, NotificationRecipient.is_read == False)
        .filter(Contract.start_date <= Notification.created_at)  # Only notifications after contract start_date
        .filter(Contract.status.in_(['PENDING', 'ACTIVE']))  # Only active or pending contracts
        .count()
    )
    return jsonify({'count': count}), 200