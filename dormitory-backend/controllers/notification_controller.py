from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from extensions import db
from models.notification import Notification
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
from datetime import datetime
import bleach
import imghdr  # Thư viện để kiểm tra định dạng hình ảnh
from PIL import Image  # Thư viện Pillow để xử lý hình ảnh
from utils.fcm import send_fcm_notification

# Thiết lập logging
logger = logging.getLogger(__name__)

notification_bp = Blueprint('notification', __name__)
UPLOAD_FOLDER = 'Uploads/notification_media'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'mp4', 'avi', 'pdf', 'doc', 'docx'}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}
VIDEO_EXTENSIONS = {'mp4', 'avi'}
DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_FILES = 20  # Tăng từ 15 lên 20
MAX_IMAGES = 10
MAX_DOCUMENTS = 5
MAX_IMAGE_SIZE = 50 * 1024 * 1024  # 50MB mỗi ảnh
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB mỗi video
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB mỗi tài liệu
MAX_TOTAL_SIZE = 1000 * 1024 * 1024  # 1000MB tổng kích thước
MAX_MESSAGE_LENGTH = 5000  # Tối đa 5000 ký tự cho message

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    elif ext in DOCUMENT_EXTENSIONS:
        return 'document'
    return 'image'

def generate_filename(created_at, notification_id, extension, folder):
    date_str = created_at.strftime('%Y%m%d_%H%M%S')
    filename = f"notification_{date_str}_{notification_id}.{extension.lower()}"
    counter = 1
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"notification_{date_str}_{notification_id}_{counter}.{extension.lower()}"
        counter += 1
    return filename

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Function to send FCM notifications to multiple users
def send_fcm_notification_to_multiple(user_ids, title, message, data=None):
    for user_id in user_ids:
        send_fcm_notification(user_id, title, message, data)

# GetPublicGeneralNotifications (Public)
@notification_bp.route('/public/notifications/general', methods=['GET'])
def get_public_general_notifications():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)

    # Lọc thông báo có target_type='ALL' và không phải SYSTEM
    notifications = Notification.query.filter_by(target_type='ALL', is_deleted=False).filter(Notification.target_type != 'SYSTEM').paginate(page=page, per_page=limit)

    # Thêm danh sách media vào phản hồi
    notifications_list = []
    for notification in notifications.items:
        media_query = NotificationMedia.query.filter_by(
            notification_id=notification.id,
            is_deleted=False
        )
        media_items = media_query.all()
        media_list = [m.to_dict() for m in media_items]
        notification_dict = notification.to_dict()
        notification_dict['media'] = media_list  # Thêm danh sách media
        notifications_list.append(notification_dict)

    logger.info(f"Public general notifications fetched: {len(notifications_list)} items")
    return jsonify({
        'notifications': notifications_list,
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

    # Lọc thông báo có target_type='ALL' và không phải SYSTEM
    notifications = Notification.query.filter_by(target_type='ALL', is_deleted=False).filter(Notification.target_type != 'SYSTEM').paginate(page=page, per_page=limit)

    # Thêm danh sách media vào phản hồi
    notifications_list = []
    for notification in notifications.items:
        media_query = NotificationMedia.query.filter_by(
            notification_id=notification.id,
            is_deleted=False
        )
        media_items = media_query.all()
        media_list = [m.to_dict() for m in media_items]
        notification_dict = notification.to_dict()
        notification_dict['media'] = media_list  # Thêm danh sách media
        notifications_list.append(notification_dict)

    logger.info(f"General notifications fetched: {len(notifications_list)} items")
    return jsonify({
        'notifications': notifications_list,
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page
    }), 200

# GetNotifications (Admin)
@notification_bp.route('/notifications', methods=['GET'])
@admin_required()
def get_all_notifications():
    logger.info("Received GET request for /notifications")
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    target_type = request.args.get('target_type')

    if limit < 1 or limit > 100:
        logger.warning("Invalid limit value: %s", limit)
        return jsonify({'message': 'Limit must be between 1 and 100'}), 422

    # Lọc thông báo không phải SYSTEM
    query = Notification.query.filter_by(is_deleted=False).filter(Notification.target_type != 'SYSTEM')
    if target_type:
        target_type = target_type.upper()
        if target_type not in ['ALL', 'ROOM', 'USER']:
            logger.warning("Invalid target_type: %s", target_type)
            return jsonify({'message': 'target_type must be ALL, ROOM, or USER'}), 422
        query = query.filter_by(target_type=target_type)

    notifications = query.paginate(page=page, per_page=limit, error_out=False)
    # Thêm danh sách media vào phản hồi
    notifications_list = []
    for notification in notifications.items:
        media_query = NotificationMedia.query.filter_by(
            notification_id=notification.id,
            is_deleted=False
        )
        media_items = media_query.all()
        media_list = [m.to_dict() for m in media_items]
        notification_dict = notification.to_dict()
        notification_dict['media'] = media_list  # Thêm danh sách media
        notifications_list.append(notification_dict)
        logger.info(f"Notification ID {notification.id} has {len(media_list)} media items: {media_list}")

    logger.info(f"All notifications fetched: {len(notifications_list)} items")
    return jsonify({
        'notifications': notifications_list,
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
    if notification.is_deleted:
        return jsonify({'message': 'Thông báo đã bị xóa'}), 400

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
        target_type = data.get('target_type')
        email = data.get('email')
        room_name = data.get('room_name')
        area_id = data.get('area_id')
        related_entity_type = data.get('related_entity_type')
        related_entity_id = data.get('related_entity_id')

        if not all([title, message, target_type]):
            logger.warning("Thiếu các trường bắt buộc: title, message, target_type")
            return jsonify({'message': 'Yêu cầu title, message và target_type'}), 400

        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"Message vượt quá độ dài tối đa: {len(message)} ký tự")
            return jsonify({'message': f'Message không được vượt quá {MAX_MESSAGE_LENGTH} ký tự'}), 400

        allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li']
        message = bleach.clean(message, tags=allowed_tags, strip=True)

        target_type = target_type.upper()
        if target_type not in ['ALL', 'ROOM', 'USER', 'SYSTEM']:
            logger.warning("target_type không hợp lệ: %s", target_type)
            return jsonify({'message': 'target_type phải là ALL, ROOM, USER hoặc SYSTEM'}), 400

        target_id_value = None
        if target_type == 'ROOM':
            if not room_name or not area_id:
                logger.warning("Yêu cầu room_name và area_id cho ROOM")
                return jsonify({'message': 'Yêu cầu room_name và area_id cho ROOM'}), 400
            try:
                area_id = int(area_id)
            except (ValueError, TypeError):
                logger.warning("area_id không hợp lệ: %s", area_id)
                return jsonify({'message': 'area_id phải là số nguyên hợp lệ'}), 400
            room = Room.query.filter_by(name=room_name, area_id=area_id).first()
            if not room:
                logger.warning("Không tìm thấy phòng: room_name=%s, area_id=%s", room_name, area_id)
                return jsonify({'message': 'Không tìm thấy phòng với tên và khu vực này'}), 404
            target_id_value = room.room_id
        elif target_type in ['USER', 'SYSTEM']:
            if not email:
                logger.warning("Yêu cầu email cho USER hoặc SYSTEM")
                return jsonify({'message': 'Yêu cầu email cho USER hoặc SYSTEM'}), 400
            user = User.query.filter_by(email=email).first()
            if not user:
                logger.warning("Không tìm thấy người dùng: email=%s", email)
                return jsonify({'message': 'Không tìm thấy người dùng với email này'}), 404
            target_id_value = user.user_id
        elif target_type == 'ALL':
            target_id_value = None

        related_entity_id_value = None
        if related_entity_id and related_entity_id != 'null':
            try:
                related_entity_id_value = int(related_entity_id)
            except (ValueError, TypeError):
                logger.warning("related_entity_id không hợp lệ: %s", related_entity_id)
                return jsonify({'message': 'related_entity_id phải là số nguyên hợp lệ hoặc null'}), 400

        claims = get_jwt()
        admin_id = int(claims.get('sub'))
        admin_fullname = claims.get('fullname', 'Admin')

        notification = Notification(
            title=title,
            message=message,
            target_type=target_type,
            target_id=target_id_value,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id_value,
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        db.session.flush()

        notification_id = notification.id

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
        failed_uploads = []
        base_url = request.host_url.rstrip('/')
        image_count = 0
        video_count = 0
        document_count = 0

        for index, file in enumerate(files):
            if file.filename == '':
                logger.warning("File không có tên: index=%s", index)
                failed_uploads.append({'index': index, 'error': 'File không có tên'})
                continue

            if not allowed_file(file.filename):
                logger.warning("Định dạng file không hỗ trợ: filename=%s", file.filename)
                failed_uploads.append({'index': index, 'error': f'File {file.filename} có định dạng không hỗ trợ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'})
                continue

            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            file_type = get_file_type(file.filename)

            if file_type == 'image':
                if file_size > MAX_IMAGE_SIZE:
                    logger.warning("Ảnh quá lớn: filename=%s, size=%s, max=%s", file.filename, file_size, MAX_IMAGE_SIZE)
                    failed_uploads.append({'index': index, 'error': f'Ảnh {file.filename} quá lớn. Tối đa {MAX_IMAGE_SIZE // (1024 * 1024)}MB'})
                    continue
                # Kiểm tra định dạng hình ảnh
                try:
                    image = Image.open(file)
                    image.verify()  # Kiểm tra tính toàn vẹn của hình ảnh
                    file.seek(0)  # Đặt lại con trỏ file sau khi kiểm tra
                except Exception as e:
                    logger.error(f"File hình ảnh không hợp lệ: filename={file.filename}, error={str(e)}")
                    failed_uploads.append({'index': index, 'error': f'File hình ảnh {file.filename} không hợp lệ: {str(e)}'})
                    continue
                image_count += 1
                if image_count > MAX_IMAGES:
                    logger.warning("Số lượng ảnh vượt quá giới hạn: count=%s, max=%s", image_count, MAX_IMAGES)
                    failed_uploads.append({'index': index, 'error': f'Tối đa {MAX_IMAGES} ảnh được phép upload'})
                    continue
            elif file_type == 'video':
                if file_size > MAX_VIDEO_SIZE:
                    logger.warning("Video quá lớn: filename=%s, size=%s, max=%s", file.filename, file_size, MAX_VIDEO_SIZE)
                    failed_uploads.append({'index': index, 'error': f'Video {file.filename} quá lớn. Tối đa {MAX_VIDEO_SIZE // (1024 * 1024)}MB'})
                    continue
                video_count += 1
            else:  # document
                if file_size > MAX_DOCUMENT_SIZE:
                    logger.warning("Tài liệu quá lớn: filename=%s, size=%s, max=%s", file.filename, file_size, MAX_DOCUMENT_SIZE)
                    failed_uploads.append({'index': index, 'error': f'Tài liệu {file.filename} quá lớn. Tối đa {MAX_DOCUMENT_SIZE // (1024 * 1024)}MB'})
                    continue
                document_count += 1
                if document_count > MAX_DOCUMENTS:
                    logger.warning("Số lượng tài liệu vượt quá giới hạn: count=%s, max=%s", document_count, MAX_DOCUMENTS)
                    failed_uploads.append({'index': index, 'error': f'Tối đa {MAX_DOCUMENTS} tài liệu được phép upload'})
                    continue

            extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            filename = generate_filename(notification.created_at, notification_id, extension, UPLOAD_FOLDER)
            file_path = os.path.join(UPLOAD_FOLDER, filename)

            try:
                file.save(file_path)
                logger.debug("Lưu file media tại: %s", file_path)
            except OSError as e:
                logger.error("Lỗi khi lưu file media: filename=%s, error=%s", filename, str(e))
                failed_uploads.append({'index': index, 'error': f'Lỗi khi lưu file {filename}'})
                continue

            media_url = filename
            sort_order = data.get(f'sort_order_{index}', str(index))
            try:
                sort_order = int(sort_order)
            except (ValueError, TypeError):
                sort_order = index

            media = NotificationMedia(
                notification_id=notification.id,
                media_url=media_url,
                alt_text=data.get(f'alt_text_{index}', ''),
                is_primary=(index == 0),
                sort_order=sort_order,
                file_type=file_type,
                file_size=file_size,
                uploaded_at=datetime.utcnow()
            )
            db.session.add(media)
            uploaded_media.append({
                'filename': filename,
                'type': file_type,
                'size': file_size,
                'sort_order': sort_order,
                'media_url': f"{base_url}/api/notification_media/{filename}"
            })

        recipients = []
        if target_type == 'ROOM':
            contracts = Contract.query.filter_by(room_id=target_id_value, status='ACTIVE').all()
            recipients = [contract.user_id for contract in contracts]
        elif target_type in ['USER', 'SYSTEM']:
            recipients = [target_id_value]
        elif target_type == 'ALL':
            recipients = [user.user_id for user in User.query.all()]

        media_message = f" (kèm {image_count} ảnh, {video_count} video, {document_count} tài liệu)" if (image_count + video_count + document_count) > 0 else ""

        for user_id in recipients:
            recipient = NotificationRecipient(notification_id=notification.id, user_id=user_id)
            db.session.add(recipient)
            user = User.query.get(user_id)
            if user and user.email:
                logger.debug("Chuẩn bị gửi email cho user_id=%s, email=%s", user_id, user.email)

        try:
            db.session.commit()
            logger.info("Tạo thông báo và lưu %s file media thành công: notification_id=%s", len(uploaded_media), notification.id)
            if target_type in ['USER', 'SYSTEM']:
                send_fcm_notification(
                    user_id=target_id_value,
                    title=notification.title,
                    message=notification.message,
                    data={
                        'notification_id': str(notification.id),
                        'related_entity_type': related_entity_type or '',
                        'related_entity_id': str(related_entity_id_value) if related_entity_id_value else ''
                    }
                )
            else:  # ROOM hoặc ALL
                send_fcm_notification_to_multiple(
                    user_ids=recipients,
                    title=notification.title,
                    message=notification.message,
                    data={
                        'notification_id': str(notification.id),
                        'related_entity_type': related_entity_type or '',
                        'related_entity_id': str(related_entity_id_value) if related_entity_id_value else ''
                    }
                )
            response = notification.to_dict()
            response['uploaded_media'] = uploaded_media
            response['failed_uploads'] = failed_uploads
            return jsonify(response), 201
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi lưu thông báo: %s", str(e))
            for media in uploaded_media:
                file_path = os.path.join(UPLOAD_FOLDER, media['filename'])
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info("Xóa file media do rollback: %s", file_path)
            return jsonify({'message': 'Lỗi khi lưu thông báo, vui lòng thử lại', 'failed_uploads': failed_uploads}), 500

    except Exception as e:
        logger.error("Lỗi server khi xử lý yêu cầu: %s", str(e))
        return jsonify({'message': 'Lỗi server nội bộ, vui lòng thử lại sau'}), 500

# UpdateNotification (Admin)
@notification_bp.route('/admin/notifications/<int:notification_id>', methods=['PUT'])
@admin_required()
def update_notification(notification_id):
    try:
        notification = Notification.query.get(notification_id)
        if not notification:
            logger.warning("Không tìm thấy thông báo: notification_id=%s", notification_id)
            return jsonify({'message': 'Không tìm thấy thông báo'}), 404

        if notification.is_deleted:
            logger.warning("Thông báo đã bị xóa: notification_id=%s", notification_id)
            return jsonify({'message': 'Thông báo đã bị xóa'}), 400

        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Yêu cầu không phải multipart/form-data")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        data = request.form
        message = data.get('message')
        email = data.get('email')
        room_name = data.get('room_name')
        area_id = data.get('area_id')

        if not message:
            logger.warning("Thiếu trường message")
            return jsonify({'message': 'Yêu cầu trường message'}), 400

        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"Message vượt quá độ dài tối đa: {len(message)} ký tự")
            return jsonify({'message': f'Message không được vượt quá {MAX_MESSAGE_LENGTH} ký tự'}), 400

        allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li']
        message = bleach.clean(message, tags=allowed_tags, strip=True)

        notification.message = message

        target_id_value = notification.target_id
        if notification.target_type == 'ROOM':
            if room_name and area_id:
                try:
                    area_id = int(area_id)
                except (ValueError, TypeError):
                    logger.warning("area_id không hợp lệ: %s", area_id)
                    return jsonify({'message': 'area_id phải là số nguyên hợp lệ'}), 400
                room = Room.query.filter_by(name=room_name, area_id=area_id).first()
                if not room:
                    logger.warning("Không tìm thấy phòng: room_name=%s, area_id=%s", room_name, area_id)
                    return jsonify({'message': 'Không tìm thấy phòng với tên và khu vực này'}), 404
                target_id_value = room.room_id
        elif notification.target_type in ['USER', 'SYSTEM']:
            if email:
                user = User.query.filter_by(email=email).first()
                if not user:
                    logger.warning("Không tìm thấy người dùng: email=%s", email)
                    return jsonify({'message': 'Không tìm thấy người dùng với email này'}), 404
                target_id_value = user.user_id
        notification.target_id = target_id_value

        claims = get_jwt()
        admin_id = int(claims.get('sub'))
        admin_fullname = claims.get('fullname', 'Admin')

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
                media.notification_id = None  # Đặt notification_id thành NULL
                logger.debug("Soft delete media: media_id=%s", media.media_id)

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
        failed_uploads = []
        base_url = request.host_url.rstrip('/')
        current_image_count = NotificationMedia.query.filter_by(
            notification_id=notification_id,
            file_type='image',
            is_deleted=False
        ).count()
        current_document_count = NotificationMedia.query.filter_by(
            notification_id=notification_id,
            file_type='document',
            is_deleted=False
        ).count()
        image_count = current_image_count
        video_count = 0
        document_count = current_document_count

        for index, file in enumerate(files):
            if file.filename == '':
                logger.warning("File không có tên: index=%s", index)
                failed_uploads.append({'index': index, 'error': 'File không có tên'})
                continue

            if not allowed_file(file.filename):
                logger.warning("Định dạng file không hỗ trợ: filename=%s", file.filename)
                failed_uploads.append({'index': index, 'error': f'File {file.filename} có định dạng không hỗ trợ. Chỉ chấp nhận: {", ".join(ALLOWED_EXTENSIONS)}'})
                continue

            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            file_type = get_file_type(file.filename)

            if file_type == 'image':
                if file_size > MAX_IMAGE_SIZE:
                    logger.warning("Ảnh quá lớn: filename=%s, size=%s, max=%s", file.filename, file_size, MAX_IMAGE_SIZE)
                    failed_uploads.append({'index': index, 'error': f'Ảnh {file.filename} quá lớn. Tối đa {MAX_IMAGE_SIZE // (1024 * 1024)}MB'})
                    continue
                # Kiểm tra định dạng hình ảnh
                try:
                    image = Image.open(file)
                    image.verify()  # Kiểm tra tính toàn vẹn của hình ảnh
                    file.seek(0)  # Đặt lại con trỏ file sau khi kiểm tra
                except Exception as e:
                    logger.error(f"File hình ảnh không hợp lệ: filename={file.filename}, error={str(e)}")
                    failed_uploads.append({'index': index, 'error': f'File hình ảnh {file.filename} không hợp lệ: {str(e)}'})
                    continue
                image_count += 1
                if image_count > MAX_IMAGES:
                    logger.warning("Số lượng ảnh vượt quá giới hạn: count=%s, max=%s", image_count, MAX_IMAGES)
                    failed_uploads.append({'index': index, 'error': f'Tối đa {MAX_IMAGES} ảnh được phép upload'})
                    continue
            elif file_type == 'video':
                if file_size > MAX_VIDEO_SIZE:
                    logger.warning("Video quá lớn: filename=%s, size=%s, max=%s", file.filename, file_size, MAX_VIDEO_SIZE)
                    failed_uploads.append({'index': index, 'error': f'Video {file.filename} quá lớn. Tối đa {MAX_VIDEO_SIZE // (1024 * 1024)}MB'})
                    continue
                video_count += 1
            else:  # document
                if file_size > MAX_DOCUMENT_SIZE:
                    logger.warning("Tài liệu quá lớn: filename=%s, size=%s, max=%s", file.filename, file_size, MAX_DOCUMENT_SIZE)
                    failed_uploads.append({'index': index, 'error': f'Tài liệu {file.filename} quá lớn. Tối đa {MAX_DOCUMENT_SIZE // (1024 * 1024)}MB'})
                    continue
                document_count += 1
                if document_count > MAX_DOCUMENTS:
                    logger.warning("Số lượng tài liệu vượt quá giới hạn: count=%s, max=%s", document_count, MAX_DOCUMENTS)
                    failed_uploads.append({'index': index, 'error': f'Tối đa {MAX_DOCUMENTS} tài liệu được phép upload'})
                    continue

            extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            filename = generate_filename(notification.created_at, notification_id, extension, UPLOAD_FOLDER)
            file_path = os.path.join(UPLOAD_FOLDER, filename)

            try:
                file.save(file_path)
                logger.debug("Lưu file media tại: %s", file_path)
            except OSError as e:
                logger.error("Lỗi khi lưu file media: filename=%s, error=%s", filename, str(e))
                failed_uploads.append({'index': index, 'error': f'Lỗi khi lưu file {filename}'})
                continue

            media_url = filename
            sort_order = data.get(f'sort_order_{index}', str(index + current_media_count))
            try:
                sort_order = int(sort_order)
            except (ValueError, TypeError):
                sort_order = index + current_media_count

            media = NotificationMedia(
                notification_id=notification.id,
                media_url=media_url,
                alt_text=data.get(f'alt_text_{index}', ''),
                is_primary=(index == 0 and current_media_count == 0),
                sort_order=sort_order,
                file_type=file_type,
                file_size=file_size,
                uploaded_at=datetime.utcnow()
            )
            db.session.add(media)
            uploaded_media.append({
                'filename': filename,
                'type': file_type,
                'size': file_size,
                'sort_order': sort_order,
                'media_url': f"{base_url}/api/notification_media/{filename}"
            })

        try:
            db.session.commit()
            logger.info("Cập nhật thông báo và xử lý %s file media thành công: notification_id=%s", len(uploaded_media), notification.id)
            response = notification.to_dict()
            response['uploaded_media'] = uploaded_media
            response['failed_uploads'] = failed_uploads
            return jsonify(response), 200
        except Exception as e:
            db.session.rollback()
            logger.error("Lỗi khi cập nhật thông báo: %s", str(e))
            for media in uploaded_media:
                file_path = os.path.join(UPLOAD_FOLDER, media['filename'])
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info("Xóa file media do rollback: %s", file_path)
            return jsonify({'message': 'Lỗi khi cập nhật thông báo, vui lòng thử lại', 'failed_uploads': failed_uploads}), 500

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

        notification.is_deleted = True
        notification.deleted_at = datetime.utcnow()
        logger.debug("Đánh dấu soft delete thông báo: notification_id=%s", notification_id)

        media_items = NotificationMedia.query.filter_by(notification_id=notification_id, is_deleted=False).all()
        for media in media_items:
            media.is_deleted = True
            media.deleted_at = datetime.utcnow()
            media.notification_id = None
            logger.debug("Đánh dấu soft delete và đặt notification_id thành NULL cho media: media_id=%s", media.media_id)

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

    # Lọc thông báo không phải SYSTEM
    query = Notification.query.filter_by(is_deleted=False).filter(Notification.target_type != 'SYSTEM')

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
    # Thêm danh sách media vào phản hồi
    notifications_list = []
    for notification in notifications.items:
        media_query = NotificationMedia.query.filter_by(
            notification_id=notification.id,
            is_deleted=False
        )
        media_items = media_query.all()
        media_list = [m.to_dict() for m in media_items]
        notification_dict = notification.to_dict()
        notification_dict['media'] = media_list  # Thêm danh sách media
        notifications_list.append(notification_dict)
        logger.info(f"Notification ID {notification.id} has {len(media_list)} media items: {media_list}")

    logger.info(f"Search notifications fetched: {len(notifications_list)} items")
    return jsonify({
        'notifications': notifications_list,
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page
    }), 200