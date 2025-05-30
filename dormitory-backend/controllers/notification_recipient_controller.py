from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models.notification_recipient import NotificationRecipient
from models.notification import Notification
from models.contract import Contract  # Import Contract model
from controllers.auth_controller import user_required
from datetime import datetime
import logging

# Thiết lập logging
logger = logging.getLogger(__name__)

notification_recipient_bp = Blueprint('notification_recipient', __name__)

# GetPersonalNotifications / GetMyNotifications (User)
@notification_recipient_bp.route('/me/notifications', methods=['GET'])
@user_required()
def get_user_notifications():
    identity = get_jwt_identity()
    user_id = int(identity)
    logger.info(f"Fetching notifications for user_id: {user_id}")
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)
    is_read = request.args.get('is_read', type=bool)

    # Lấy thông báo từ notification_recipients
    query = (
        NotificationRecipient.query
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == user_id)
        .filter(Notification.is_deleted == False)
        .filter(NotificationRecipient.is_deleted == False)
    )
    if is_read is not None:
        query = query.filter(NotificationRecipient.is_read == is_read)

    personal_notifications_from_recipients = query.all()
    logger.info(f"Found {len(personal_notifications_from_recipients)} personal notifications from recipients for user_id: {user_id}")

    # Lấy thông báo trực tiếp từ notification dựa trên target_id (target_type = 'USER' hoặc 'SYSTEM')
    user_notifications_query = (
        Notification.query
        .filter(Notification.target_type.in_(['USER', 'SYSTEM']))
        .filter(Notification.target_id == user_id)
        .filter(Notification.is_deleted == False)
    )
    user_notifications = user_notifications_query.all()
    logger.info(f"Found {len(user_notifications)} direct user notifications for user_id: {user_id} (target_type=USER or SYSTEM)")

    # Thêm thông báo cho ROOM: Kiểm tra nếu user có hợp đồng trong room
    room_notifications_query = (
        Notification.query
        .join(Contract, Notification.target_id == Contract.room_id)
        .filter(Notification.target_type == 'ROOM')
        .filter(Contract.user_id == user_id)
        .filter(Contract.status == 'ACTIVE')
        .filter(Notification.is_deleted == False)
    )
    room_notifications = room_notifications_query.all()
    logger.info(f"Found {len(room_notifications)} room notifications for user_id: {user_id} (target_type=ROOM)")

    # Đồng bộ: Tạo bản ghi trong notification_recipients nếu thiếu
    for notification in user_notifications + room_notifications:
        existing_recipient = NotificationRecipient.query.filter_by(
            notification_id=notification.id,
            user_id=user_id
        ).first()
        if not existing_recipient:
            new_recipient = NotificationRecipient(
                notification_id=notification.id,
                user_id=user_id,
                is_read=False
            )
            db.session.add(new_recipient)
            personal_notifications_from_recipients.append(new_recipient)
            logger.info(f"Created new recipient record for notification_id={notification.id}, user_id={user_id}")

    # Commit các bản ghi mới trong notification_recipients
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing new recipient records: {e}")
        return jsonify({'message': 'Lỗi khi lưu thông tin người nhận, vui lòng thử lại'}), 500

    # Phân trang thủ công cho danh sách thông báo cá nhân
    if is_read is not None:
        personal_notifications_from_recipients = [recipient for recipient in personal_notifications_from_recipients if recipient.is_read == is_read]

    total = len(personal_notifications_from_recipients)
    start = (page - 1) * limit
    end = start + limit
    personal_notifications_paginated = personal_notifications_from_recipients[start:end]

    # Lấy thông báo chung (ALL)
    public_query = (
        Notification.query
        .filter(Notification.target_type == 'ALL')
        .filter(Notification.is_deleted == False)
    )
    public_notifications = public_query.all()
    logger.info(f"Found {len(public_notifications)} public notifications")

    # Trả về personal_notifications bao gồm cả thông tin thông báo và recipientId
    personal_notifications_response = []
    for recipient in personal_notifications_paginated:
        notification_data = recipient.notification.to_dict()
        notification_data['recipientId'] = recipient.id
        notification_data['isRead'] = recipient.is_read
        personal_notifications_response.append(notification_data)

    return jsonify({
        'personal_notifications': personal_notifications_response,
        'public_notifications': [notification.to_dict() for notification in public_notifications],
        'personal_total': total,
        'personal_pages': (total + limit - 1) // limit,
        'personal_current_page': page
    }), 200

# MarkNotificationAsRead (User)
@notification_recipient_bp.route('/me/notifications/mark-as-read', methods=['PUT'])
@user_required()
def mark_notification_as_read():
    identity = get_jwt_identity()
    user_id = int(identity)
    notification_id = request.args.get('notification_id', type=int)

    if not notification_id:
        logger.warning("Missing notification_id parameter")
        return jsonify({'message': 'Yêu cầu notification_id'}), 400

    logger.info(f"Marking notification as read: notification_id={notification_id}, user_id={user_id}")

    # Tìm recipient dựa trên notification_id và user_id
    recipient = NotificationRecipient.query.filter_by(
        notification_id=notification_id,
        user_id=user_id,
        is_deleted=False
    ).first()

    if not recipient:
        logger.error(f"Recipient not found: notification_id={notification_id}, user_id={user_id}")
        return jsonify({'message': 'Không tìm thấy thông báo cho người dùng này'}), 404

    recipient.is_read = True
    recipient.read_at = datetime.utcnow()
    logger.info(f"Updated recipient: recipient_id={recipient.id}, is_read={recipient.is_read}, read_at={recipient.read_at}")

    try:
        db.session.commit()
        logger.info(f"Successfully committed changes for recipient_id={recipient.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing changes for recipient_id={recipient.id}: {e}")
        return jsonify({'message': 'Lỗi khi lưu thay đổi, vui lòng thử lại'}), 500

    return jsonify(recipient.to_dict()), 200

# MarkAllNotificationsAsRead (User)
@notification_recipient_bp.route('/me/notifications/mark-all-read', methods=['PUT'])
@user_required()
def mark_all_notifications_as_read():
    identity = get_jwt_identity()
    user_id = int(identity)
    logger.info(f"Marking all notifications as read for user_id: {user_id}")
    
    recipients = (
        NotificationRecipient.query
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == user_id, NotificationRecipient.is_read == False)
        .filter(Notification.is_deleted == False)
        .filter(NotificationRecipient.is_deleted == False)
        .all()
    )

    for recipient in recipients:
        recipient.is_read = True
        recipient.read_at = datetime.utcnow()
        logger.info(f"Updated recipient: recipient_id={recipient.id}, is_read={recipient.is_read}, read_at={recipient.read_at}")

    try:
        db.session.commit()
        logger.info(f"Successfully committed changes for user_id={user_id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing changes for user_id={user_id}: {e}")
        return jsonify({'message': 'Lỗi khi lưu thay đổi, vui lòng thử lại'}), 500

    return jsonify({'message': 'Đánh dấu tất cả thông báo là đã đọc'}), 200

# GetUnreadNotificationsCount (User)
@notification_recipient_bp.route('/me/notifications/unread-count', methods=['GET'])
@user_required()
def get_unread_notifications_count():
    identity = get_jwt_identity()
    user_id = int(identity)
    logger.info(f"Fetching unread notifications count for user_id: {user_id}")
    
    count = (
        NotificationRecipient.query
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == user_id, NotificationRecipient.is_read == False)
        .filter(Notification.is_deleted == False)
        .filter(NotificationRecipient.is_deleted == False)
        .count()
    )
    logger.info(f"Unread notifications count for user_id={user_id}: {count}")
    
    return jsonify({'count': count}), 200

# DeleteNotification (User)
@notification_recipient_bp.route('/me/notifications/delete', methods=['DELETE'])
@user_required()
def delete_notification():
    identity = get_jwt_identity()
    user_id = int(identity)
    notification_id = request.args.get('notification_id', type=int)

    if not notification_id:
        logger.warning("Missing notification_id parameter")
        return jsonify({'message': 'Yêu cầu notification_id'}), 400

    logger.info(f"Deleting notification: notification_id={notification_id}, user_id={user_id}")

    # Tìm recipient và join với Notification để lấy target_type
    recipient = (
        NotificationRecipient.query
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.notification_id == notification_id)
        .filter(NotificationRecipient.user_id == user_id)
        .filter(NotificationRecipient.is_deleted == False)
        .first()
    )

    if not recipient:
        logger.error(f"Recipient not found: notification_id={notification_id}, user_id={user_id}")
        return jsonify({'message': 'Không tìm thấy thông báo cho người dùng này'}), 404

    # Kiểm tra target_type của thông báo
    if recipient.notification.target_type in ['SYSTEM', 'USER']:
        # Xóa mềm cho thông báo SYSTEM hoặc USER
        recipient.is_deleted = True
        recipient.deleted_at = datetime.utcnow()
        logger.info(f"Soft deleted recipient: recipient_id={recipient.id}, is_deleted={recipient.is_deleted}, deleted_at={recipient.deleted_at}")
    else:
        # Xóa cứng cho thông báo không phải SYSTEM hoặc USER (ví dụ: ALL)
        db.session.delete(recipient)
        logger.info(f"Hard deleted recipient: recipient_id={recipient.id}")

    try:
        db.session.commit()
        logger.info(f"Successfully committed deletion for recipient_id={recipient.id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error committing deletion for recipient_id={recipient.id}: {e}")
        return jsonify({'message': 'Lỗi khi xóa thông báo, vui lòng thử lại'}), 500

    return jsonify({'message': 'Thông báo đã được xóa'}), 200