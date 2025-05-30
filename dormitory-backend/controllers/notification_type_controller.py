from flask import Blueprint, request, jsonify
from extensions import db
from models.notification_type import NotificationType
from controllers.auth_controller import admin_required
import logging

logger = logging.getLogger(__name__)

notification_type_bp = Blueprint('notification_type', __name__)

# GetAllNotificationTypes (Public)
@notification_type_bp.route('/notification-types', methods=['GET'])
def get_all_notification_types():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    types = NotificationType.query.paginate(page=page, per_page=limit)
    return jsonify({
        'notification_types': [type.to_dict() for type in types.items],
        'total': types.total,
        'pages': types.pages,
        'current_page': types.page
    }), 200

# CreateNotificationType (Admin)
@notification_type_bp.route('/admin/notification-types', methods=['POST'])
@admin_required()
def create_notification_type():
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    status = data.get('status')  # Thêm trường status

    if not name:
        logger.warning("Thiếu trường name")
        return jsonify({'message': 'Yêu cầu name'}), 400

    if not status:
        logger.warning("Thiếu trường status")
        return jsonify({'message': 'Yêu cầu status'}), 400

    if status not in ['ALL', 'ROOM', 'USER']:
        logger.warning("status không hợp lệ: %s", status)
        return jsonify({'message': 'status phải là ALL, ROOM hoặc USER'}), 400

    if NotificationType.query.filter_by(name=name).first():
        logger.warning("Tên loại thông báo đã tồn tại: name=%s", name)
        return jsonify({'message': 'Tên loại thông báo đã tồn tại'}), 400

    notification_type = NotificationType(name=name, description=description, status=status)
    db.session.add(notification_type)
    db.session.commit()
    logger.info("Tạo loại thông báo thành công: id=%s, name=%s, status=%s", notification_type.id, name, status)
    return jsonify(notification_type.to_dict()), 201

# UpdateNotificationType (Admin)
@notification_type_bp.route('/admin/notification-types/<int:type_id>', methods=['PUT'])
@admin_required()
def update_notification_type(type_id):
    notification_type = NotificationType.query.get(type_id)
    if not notification_type:
        logger.warning("Không tìm thấy loại thông báo: type_id=%s", type_id)
        return jsonify({'message': 'Không tìm thấy loại thông báo'}), 404

    data = request.get_json()
    name = data.get('name', notification_type.name)
    description = data.get('description', notification_type.description)
    status = data.get('status', notification_type.status)  # Thêm trường status

    if not status:
        logger.warning("Thiếu trường status")
        return jsonify({'message': 'Yêu cầu status'}), 400

    if status not in ['ALL', 'ROOM', 'USER']:
        logger.warning("status không hợp lệ: %s", status)
        return jsonify({'message': 'status phải là ALL, ROOM hoặc USER'}), 400

    if NotificationType.query.filter(NotificationType.name == name, NotificationType.id != type_id).first():
        logger.warning("Tên loại thông báo đã tồn tại: name=%s", name)
        return jsonify({'message': 'Tên loại thông báo đã tồn tại'}), 400

    notification_type.name = name
    notification_type.description = description
    notification_type.status = status
    db.session.commit()
    logger.info("Cập nhật loại thông báo thành công: id=%s, name=%s, status=%s", type_id, name, status)
    return jsonify(notification_type.to_dict()), 200

# DeleteNotificationType (Admin)
@notification_type_bp.route('/admin/notification-types/<int:type_id>', methods=['DELETE'])
@admin_required()
def delete_notification_type(type_id):
    notification_type = NotificationType.query.get(type_id)
    if not notification_type:
        logger.warning("Không tìm thấy loại thông báo: type_id=%s", type_id)
        return jsonify({'message': 'Không tìm thấy loại thông báo'}), 404

    # Không cho phép xóa loại "General" (id: 3)
    if type_id == 3:
        logger.warning("Không cho phép xóa loại thông báo General: type_id=%s", type_id)
        return jsonify({'message': 'Không thể xóa loại thông báo General'}), 403

    db.session.delete(notification_type)
    db.session.commit()
    logger.info("Xóa loại thông báo thành công: type_id=%s", type_id)
    return jsonify({'message': 'Xóa loại thông báo thành công'}), 200