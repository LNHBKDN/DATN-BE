from flask import Blueprint, request, jsonify
from extensions  import db
from models.notification_type import NotificationType
from controllers.auth_controller import admin_required

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

    if not name:
        return jsonify({'message': 'Yêu cầu name'}), 400

    if NotificationType.query.filter_by(name=name).first():
        return jsonify({'message': 'Tên loại thông báo đã tồn tại'}), 400

    notification_type = NotificationType(name=name, description=description)
    db.session.add(notification_type)
    db.session.commit()
    return jsonify(notification_type.to_dict()), 201

# UpdateNotificationType (Admin)
@notification_type_bp.route('/admin/notification-types/<int:type_id>', methods=['PUT'])
@admin_required()
def update_notification_type(type_id):
    notification_type = NotificationType.query.get(type_id)
    if not notification_type:
        return jsonify({'message': 'Không tìm thấy loại thông báo'}), 404

    data = request.get_json()
    notification_type.name = data.get('name', notification_type.name)
    notification_type.description = data.get('description', notification_type.description)

    if NotificationType.query.filter(NotificationType.name == notification_type.name, NotificationType.id != type_id).first():
        return jsonify({'message': 'Tên loại thông báo đã tồn tại'}), 400

    db.session.commit()
    return jsonify(notification_type.to_dict()), 200

# DeleteNotificationType (Admin)
@notification_type_bp.route('/admin/notification-types/<int:type_id>', methods=['DELETE'])
@admin_required()
def delete_notification_type(type_id):
    notification_type = NotificationType.query.get(type_id)
    if not notification_type:
        return jsonify({'message': 'Không tìm thấy loại thông báo'}), 404

    db.session.delete(notification_type)
    db.session.commit()
    return jsonify({'message': 'Xóa loại thông báo thành công'}), 200