from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.notification import Notification
from models.notification_type import NotificationType
from models.notification_recipient import NotificationRecipient
from models.notification_media import NotificationMedia
from models.room import Room
from models.user import User
from models.contract import Contract
from controllers.auth_controller import admin_required
import os
from werkzeug.utils import secure_filename
import logging
import re
from unidecode import unidecode
from datetime import datetime
import bleach 

# Thiết lập logging
logger = logging.getLogger(__name__)

notification_bp = Blueprint('notification', __name__)
UPLOAD_FOLDER = 'uploads/notification_media'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'mp4', 'avi'}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}
VIDEO_EXTENSIONS = {'mp4', 'avi'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB mỗi file
MAX_FILES = 10  # Tối đa 10 file mỗi yêu cầu
MAX_TOTAL_SIZE = 1000 * 1024 * 1024  # 1000MB tổng kích thước
MAX_MESSAGE_LENGTH = 5000  # Tối đa 5000 ký tự cho message
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return 'video' if ext in VIDEO_EXTENSIONS else 'image'

def generate_filename(notification_type_name, created_at, extension, folder):
    # Chuẩn hóa notification_type_name (loại bỏ ký tự đặc biệt, không dấu)
    base_name = re.sub(r'[^\w]', '', unidecode(notification_type_name)).lower()
    
    # Định dạng created_at thành YYYYMMDD
    date_str = created_at.strftime('%Y%m%d')
    
    # Tạo tên file cơ bản
    filename = f"{base_name}_{date_str}.{extension.lower()}"
    
    # Xử lý trùng tên bằng cách thêm hậu tố _1, _2, ...
    counter = 1
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"{base_name}_{date_str}_{counter}.{extension.lower()}"
        counter += 1
    
    return filename


os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# GetPublicGeneralNotifications (Public)
@notification_bp.route('/public/notifications/general', methods=['GET'])
def get_public_general_notifications():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    notifications = Notification.query.filter_by(target_type='ALL').paginate(page=page, per_page=limit)
    return jsonify({
        'notifications': [notification.to_dict() for notification in notifications.items],
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page
    }), 200

# GetGeneralNotifications (Admin)
@notification_bp.route('/notifications/general', methods=['GET'])
@admin_required()
def get_general_notifications():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    notifications = Notification.query.filter_by(target_type='ALL').paginate(page=page, per_page=limit)
    return jsonify({
        'notifications': [notification.to_dict() for notification in notifications.items],
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page
    }), 200

# GetNotifications (Admin)
@notification_bp.route('/notifications', methods=['GET'])
@admin_required()
def get_all_notifications():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    target_type = request.args.get('target_type')
    type_id = request.args.get('type_id', type=int)

    query = Notification.query
    if target_type:
        query = query.filter_by(target_type=target_type.upper())
    if type_id:
        query = query.filter_by(type_id=type_id)

    notifications = query.paginate(page=page, per_page=limit)
    return jsonify({
        'notifications': [notification.to_dict() for notification in notifications.items],
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page
    }), 200

# GetRecipients (Admin)
@notification_bp.route('/admin/notifications/<int:notification_id>/recipients', methods=['GET'])
@admin_required()
def get_notification_recipients(notification_id):
    notification = Notification.query.get(notification_id)
    if not notification:
        return jsonify({'message': 'Không tìm thấy thông báo'}), 404

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    is_read = request.args.get('is_read', type=bool)

    query = NotificationRecipient.query.filter_by(notification_id=notification_id)
    if is_read is not None:
        query = query.filter_by(is_read=is_read)

    recipients = query.paginate(page=page, per_page=limit)
    return jsonify({
        'recipients': [recipient.to_dict() for recipient in recipients.items],
        'total': recipients.total,
        'pages': recipients.pages,
        'current_page': recipients.page
    }), 200

# CreateNotification (Admin)
@notification_bp.route('/admin/notifications', methods=['POST'])
@admin_required()
def create_notification():
    try:
        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Yêu cầu không phải multipart/form-data")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        data = request.form
        title = data.get('title')
        message = data.get('message')
        type_id = data.get('type_id')
        target_type = data.get('target_type')
        target_id = data.get('target_id')
        related_entity_type = data.get('related_entity_type')
        related_entity_id = data.get('related_entity_id')

        if not all([title, message, type_id, target_type]):
            logger.warning("Thiếu các trường bắt buộc: title, message, type_id, target_type")
            return jsonify({'message': 'Yêu cầu title, message, type_id và target_type'}), 400

        # Kiểm tra độ dài message
        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"Message vượt quá độ dài tối đa: {len(message)} ký tự")
            return jsonify({'message': f'Message không được vượt quá {MAX_MESSAGE_LENGTH} ký tự'}), 400

        # Vệ sinh message nếu chứa HTML
        allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li']  # Các thẻ HTML cho phép
        message = bleach.clean(message, tags=allowed_tags, strip=True)

        target_type = target_type.upper()
        if target_type not in ['ALL', 'ROOM', 'USER']:
            logger.warning("target_type không hợp lệ: %s", target_type)
            return jsonify({'message': 'target_type phải là ALL, ROOM hoặc USER'}), 400

        try:
            type_id = int(type_id)
        except (ValueError, TypeError):
            logger.warning("type_id không phải số nguyên: %s", type_id)
            return jsonify({'message': 'type_id phải là số nguyên hợp lệ'}), 400

        notification_type = NotificationType.query.get(type_id)
        if not notification_type:
            logger.warning("Không tìm thấy loại thông báo: type_id=%s", type_id)
            return jsonify({'message': 'Không tìm thấy loại thông báo'}), 404

        target_id_value = None
        if target_id and target_id != 'null':
            try:
                target_id_value = int(target_id)
            except (ValueError, TypeError):
                logger.warning("target_id không hợp lệ: %s", target_id)
                return jsonify({'message': 'target_id phải là số nguyên hợp lệ hoặc null'}), 400

        related_entity_id_value = None
        if related_entity_id and related_entity_id != 'null':
            try:
                related_entity_id_value = int(related_entity_id)
            except (ValueError, TypeError):
                logger.warning("related_entity_id không hợp lệ: %s", related_entity_id)
                return jsonify({'message': 'related_entity_id phải là số nguyên hợp lệ hoặc null'}), 400

        if target_type == 'ROOM' and target_id_value:
            if not Room.query.get(target_id_value):
                logger.warning("Không tìm thấy phòng: target_id=%s", target_id_value)
                return jsonify({'message': 'Không tìm thấy phòng'}), 404
        elif target_type == 'USER' and target_id_value:
            if not User.query.get(target_id_value):
                logger.warning("Không tìm thấy người dùng: target_id=%s", target_id_value)
                return jsonify({'message': 'Không tìm thấy người dùng'}), 404
        elif target_type != 'ALL' and not target_id_value:
            logger.warning("Yêu cầu target_id cho ROOM hoặc USER: target_type=%s", target_type)
            return jsonify({'message': 'Yêu cầu target_id cho ROOM hoặc USER'}), 400

        # Lấy thông tin admin từ JWT
        claims = get_jwt()
        admin_id = int(claims.get('sub'))
        admin_fullname = claims.get('fullname', 'Admin')

        # Tạo thông báo
        notification = Notification(
            title=title,
            message=message,
            type_id=type_id,
            target_type=target_type,
            target_id=target_id_value,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id_value,
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        db.session.flush()

        # Xử lý media
        files = request.files.getlist('media')
        if len(files) > MAX_FILES:
            logger.warning("Số lượng file vượt quá giới hạn: count=%s, max=%s", len(files), MAX_FILES)
            return jsonify({'message': f'Tối đa {MAX_FILES} file được phép upload'}), 400

        total_size = 0
        for file in files:
            file.seek(0, os.SEEK_END)
            total_size += file.tell()
            file.seek(0)
        if total_size > MAX_TOTAL_SIZE:
            logger.warning("Tổng kích thước file quá lớn: total=%s, max=%s", total_size, MAX_TOTAL_SIZE)
            return jsonify({'message': f'Tổng kích thước file vượt quá {MAX_TOTAL_SIZE // (1024 * 1024)}MB'}), 400

        uploaded_media = []
        base_url = request.host_url.rstrip('/')
        admin_name = re.sub(r'[^\w\-]', '_', admin_fullname)
        folder_name = f"{notification.id}_{target_type}_{admin_name}"
        media_folder = os.path.join(UPLOAD_FOLDER, folder_name)
        try:
            os.makedirs(media_folder, exist_ok=True)
            logger.debug("Tạo thư mục media: %s", media_folder)
        except OSError as e:
            logger.error("Lỗi khi tạo thư mục: folder=%s, error=%s", media_folder, str(e))
            return jsonify({'message': 'Lỗi khi tạo thư mục lưu trữ'}), 500

        image_count = 0
        video_count = 0
        for index, file in enumerate(files):
            if file.filename == '':
                logger.warning("File không có tên: index=%s", index)
                continue

            if not allowed_file(file.filename):
                logger.warning("Định dạng file không hỗ trợ: filename=%s", file.filename)
                return jsonify({'message': f'File {file.filename} có định dạng không hỗ trợ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            if file_size > MAX_FILE_SIZE:
                file_type = get_file_type(file.filename)
                logger.warning("File %s quá lớn: filename=%s, size=%s, max=%s", file_type, file.filename, file_size, MAX_FILE_SIZE)
                return jsonify({'message': f'File {file.filename} ({file_type}) quá lớn. Tối đa {MAX_FILE_SIZE // (1024 * 1024)}MB'}), 400

            extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            filename = generate_filename(notification_type.name, notification.created_at, extension, media_folder)
            file_path = os.path.join(media_folder, filename)

            try:
                file.save(file_path)
                logger.debug("Lưu file media tại: %s", file_path)
            except OSError as e:
                logger.error("Lỗi khi lưu file media: filename=%s, error=%s", filename, str(e))
                return jsonify({'message': f'Lỗi khi lưu file {filename}'}), 500

            media_url = f"{base_url}/notification_media/{folder_name}/{filename}"
            file_type = get_file_type(filename)
            if file_type == 'image':
                image_count += 1
            else:
                video_count += 1

            media = NotificationMedia(
                notification_id=notification.id,
                media_url=media_url,
                alt_text=data.get(f'alt_text_{index}', ''),
                is_primary=(index == 0),
                sort_order=index,
                file_type=file_type,
                file_size=file_size,
                uploaded_at=datetime.utcnow()
            )
            db.session.add(media)
            uploaded_media.append(media)

        # Tạo danh sách người nhận
        recipients = []
        if target_type == 'ROOM':
            contracts = Contract.query.filter_by(room_id=target_id_value, status='ACTIVE').all()
            recipients = [contract.user_id for contract in contracts]
        elif target_type == 'USER':
            recipients = [target_id_value]
        elif target_type == 'ALL':
            recipients = [user.user_id for user in User.query.all()]

        media_message = f" (kèm {image_count} ảnh, {video_count} video)" if (image_count + video_count) > 0 else ""

        for user_id in recipients:
            recipient = NotificationRecipient(notification_id=notification.id, user_id=user_id)
            db.session.add(recipient)
            user = User.query.get(user_id)
            if user and user.email:
                logger.debug("Chuẩn bị gửi email cho user_id=%s, email=%s", user_id, user.email)

        try:
            db.session.commit()
            logger.info("Tạo thông báo và lưu %s file media thành công: notification_id=%s", len(uploaded_media), notification.id)
            return jsonify(notification.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi lưu thông báo/media: %s", str(e))
            for media in uploaded_media:
                file_path = os.path.join(media_folder, os.path.basename(media.media_url))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info("Xóa file media do rollback: %s", file_path)
            return jsonify({'message': 'Lỗi khi lưu thông báo, vui lòng thử lại'}), 500

    except Exception as e:
        logger.error("Lỗi server khi xử lý yêu cầu: %s", str(e))
        return jsonify({'message': 'Lỗi server nội bộ, vui lòng thử lại sau'}), 500

# UpdateNotification (Admin)
@notification_bp.route('/admin/notifications/<int:notification_id>', methods=['PUT'])
@admin_required()
def update_notification(notification_id):
    try:
        # Tìm thông báo
        notification = Notification.query.get(notification_id)
        if not notification:
            logger.warning("Không tìm thấy thông báo: notification_id=%s", notification_id)
            return jsonify({'message': 'Không tìm thấy thông báo'}), 404

        if notification.is_deleted:
            logger.warning("Thông báo đã bị xóa: notification_id=%s", notification_id)
            return jsonify({'message': 'Thông báo đã bị xóa'}), 400

        # Kiểm tra request là multipart/form-data
        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Yêu cầu không phải multipart/form-data")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        data = request.form
        message = data.get('message')

        # Kiểm tra message
        if not message:
            logger.warning("Thiếu trường message")
            return jsonify({'message': 'Yêu cầu trường message'}), 400

        # Kiểm tra độ dài message
        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"Message vượt quá độ dài tối đa: {len(message)} ký tự")
            return jsonify({'message': f'Message không được vượt quá {MAX_MESSAGE_LENGTH} ký tự'}), 400

        # Vệ sinh message nếu chứa HTML
        allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li']
        message = bleach.clean(message, tags=allowed_tags, strip=True)

        # Cập nhật message
        notification.message = message

        # Lấy thông tin admin từ JWT
        claims = get_jwt()
        admin_id = int(claims.get('sub'))
        admin_fullname = claims.get('fullname', 'Admin')

        # Xử lý xóa media
        media_ids_to_delete = data.get('media_ids_to_delete', '').split(',')
        media_ids_to_delete = [int(id) for id in media_ids_to_delete if id.strip().isdigit()]
        if media_ids_to_delete:
            media_to_delete = NotificationMedia.query.filter(
                NotificationMedia.media_id.in_(media_ids_to_delete),
                NotificationMedia.notification_id == notification_id,
                NotificationMedia.is_deleted == False
            ).all()
            for media in media_to_delete:
                media.is_deleted = True
                media.deleted_at = datetime.utcnow()
                logger.debug("Soft delete media: media_id=%s", media.media_id)

        # Xử lý thêm media mới
        files = request.files.getlist('media')
        current_media_count = NotificationMedia.query.filter_by(
            notification_id=notification_id,
            is_deleted=False
        ).count()
        if len(files) + current_media_count > MAX_FILES:
            logger.warning("Số lượng file vượt quá giới hạn: count=%s, max=%s", len(files) + current_media_count, MAX_FILES)
            return jsonify({'message': f'Tổng số file (hiện tại + mới) không được vượt quá {MAX_FILES}'}), 400

        total_size = 0
        for file in files:
            file.seek(0, os.SEEK_END)
            total_size += file.tell()
            file.seek(0)
        if total_size > MAX_TOTAL_SIZE:
            logger.warning("Tổng kích thước file quá lớn: total=%s, max=%s", total_size, MAX_TOTAL_SIZE)
            return jsonify({'message': f'Tổng kích thước file vượt quá {MAX_TOTAL_SIZE // (1024 * 1024)}MB'}), 400

        uploaded_media = []
        base_url = request.host_url.rstrip('/')
        admin_name = re.sub(r'[^\w\-]', '_', admin_fullname)
        folder_name = f"{notification.id}_{notification.target_type}_{admin_name}"
        media_folder = os.path.join(UPLOAD_FOLDER, folder_name)
        try:
            os.makedirs(media_folder, exist_ok=True)
            logger.debug("Tạo thư mục media: %s", media_folder)
        except OSError as e:
            logger.error("Lỗi khi tạo thư mục: folder=%s, error=%s", media_folder, str(e))
            return jsonify({'message': 'Lỗi khi tạo thư mục lưu trữ'}), 500

        notification_type = NotificationType.query.get(notification.type_id)
        image_count = 0
        video_count = 0
        for index, file in enumerate(files):
            if file.filename == '':
                logger.warning("File không có tên: index=%s", index)
                continue

            if not allowed_file(file.filename):
                logger.warning("Định dạng file không hỗ trợ: filename=%s", file.filename)
                return jsonify({'message': f'File {file.filename} có định dạng không hỗ trợ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            if file_size > MAX_FILE_SIZE:
                file_type = get_file_type(file.filename)
                logger.warning("File %s quá lớn: filename=%s, size=%s, max=%s", file_type, file.filename, file_size, MAX_FILE_SIZE)
                return jsonify({'message': f'File {file.filename} ({file_type}) quá lớn. Tối đa {MAX_FILE_SIZE // (1024 * 1024)}MB'}), 400

            extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            filename = generate_filename(notification_type.name, notification.created_at, extension, media_folder)
            file_path = os.path.join(media_folder, filename)

            try:
                file.save(file_path)
                logger.debug("Lưu file media tại: %s", file_path)
            except OSError as e:
                logger.error("Lỗi khi lưu file media: filename=%s, error=%s", filename, str(e))
                return jsonify({'message': f'Lỗi khi lưu file {filename}'}), 500

            media_url = f"{base_url}/notification_media/{folder_name}/{filename}"
            file_type = get_file_type(filename)
            if file_type == 'image':
                image_count += 1
            else:
                video_count += 1

            media = NotificationMedia(
                notification_id=notification.id,
                media_url=media_url,
                alt_text=data.get(f'alt_text_{index}', ''),
                is_primary=(index == 0 and current_media_count == 0),
                sort_order=index + current_media_count,
                file_type=file_type,
                file_size=file_size,
                uploaded_at=datetime.utcnow()
            )
            db.session.add(media)
            uploaded_media.append(media)

        try:
            db.session.commit()
            logger.info("Cập nhật thông báo và xử lý %s file media thành công: notification_id=%s", len(uploaded_media), notification.id)
            return jsonify(notification.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi cập nhật thông báo/media: %s", str(e))
            for media in uploaded_media:
                file_path = os.path.join(media_folder, os.path.basename(media.media_url))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info("Xóa file media do rollback: %s", file_path)
            return jsonify({'message': 'Lỗi khi cập nhật thông báo, vui lòng thử lại'}), 500

    except Exception as e:
        logger.error("Lỗi server khi cập nhật thông báo: %s", str(e))
        return jsonify({'message': 'Lỗi server nội bộ, vui lòng thử lại sau'}), 500

# DeleteNotification (Admin)
@notification_bp.route('/admin/notifications/<int:notification_id>', methods=['DELETE'])
@admin_required()
def delete_notification(notification_id):
    try:
        logger.info("Bắt đầu xóa thông báo: notification_id=%s", notification_id)
        notification = Notification.query.get(notification_id)
        if not notification:
            logger.warning("Không tìm thấy thông báo: notification_id=%s", notification_id)
            return jsonify({'message': 'Không tìm thấy thông báo'}), 404

        if notification.is_deleted:
            logger.warning("Thông báo đã bị xóa: notification_id=%s", notification_id)
            return jsonify({'message': 'Thông báo đã bị xóa trước đó'}), 400

        # Soft delete thông báo
        notification.is_deleted = True
        notification.deleted_at = datetime.utcnow()
        logger.debug("Đánh dấu soft delete thông báo: notification_id=%s", notification_id)

        # Soft delete tất cả media liên quan
        media_items = NotificationMedia.query.filter_by(notification_id=notification_id, is_deleted=False).all()
        for media in media_items:
            media.is_deleted = True
            media.deleted_at = datetime.utcnow()
            logger.debug("Đánh dấu soft delete media: media_id=%s", media.media_id)

        try:
            db.session.commit()
            logger.info("Xóa thông báo và media thành công: notification_id=%s, media_count=%s", notification_id, len(media_items))
            return jsonify({'message': 'Xóa thông báo thành công'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi xóa thông báo/media: %s", str(e))
            return jsonify({'message': 'Lỗi khi xóa thông báo, vui lòng thử lại'}), 500

    except Exception as e:
        logger.error("Lỗi server khi xóa thông báo: %s", str(e))
        return jsonify({'message': 'Lỗi server nội bộ, vui lòng thử lại sau'}), 500

# SearchNotifications (Admin)
@notification_bp.route('/admin/notifications/search', methods=['GET'])
@admin_required()
def search_notifications():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    keyword = request.args.get('keyword')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = Notification.query

    if keyword:
        query = query.filter(
            (Notification.title.ilike(f'%{keyword}%')) |
            (Notification.message.ilike(f'%{keyword}%'))
        )
    if start_date:
        query = query.filter(Notification.created_at >= start_date)
    if end_date:
        query = query.filter(Notification.created_at <= end_date)

    notifications = query.paginate(page=page, per_page=limit)
    return jsonify({
        'notifications': [notification.to_dict() for notification in notifications.items],
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page
    }), 200