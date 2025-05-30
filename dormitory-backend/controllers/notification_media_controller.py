# notification_media_controller.py
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import get_jwt, jwt_required
from extensions import db
from models.notification import Notification
from models.notification_media import NotificationMedia
from models.notification_recipient import NotificationRecipient
from models.admin import Admin
from controllers.auth_controller import admin_required
import os
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime
import logging
import re
from unidecode import unidecode
import mimetypes

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

notification_media_bp = Blueprint('notification_media', __name__)

# Đường dẫn lưu file
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'mp4', 'avi', 'pdf', 'doc', 'docx'}
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png'}
VIDEO_EXTENSIONS = {'mp4', 'avi'}
DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_FILES = 15
MAX_IMAGES = 10
MAX_DOCUMENTS = 5
MAX_IMAGE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB
MAX_TOTAL_SIZE = 1000 * 1024 * 1024  # 1000MB

# Kiểm tra file hợp lệ
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Hàm xác định loại file
def get_file_type(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    elif ext in DOCUMENT_EXTENSIONS:
        return 'document'
    return 'image'

# Hàm tạo tên file
def generate_filename(notification_type_name, created_at, extension, folder):
    base_name = re.sub(r'[^\w]', '', unidecode(notification_type_name)).lower()
    date_str = created_at.strftime('%Y%m%d')
    filename = f"{base_name}_{date_str}.{extension.lower()}"
    counter = 1
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"{base_name}_{date_str}_{counter}.{extension.lower()}"
        counter += 1
    return filename

def clean_deleted_media_notification_id():
    """
    Kiểm tra và đặt notification_id thành NULL cho các bản ghi NotificationMedia đã xóa mềm.
    """
    try:
        deleted_media = NotificationMedia.query.filter_by(is_deleted=True).filter(NotificationMedia.notification_id != None).all()
        if not deleted_media:
            logger.info("No deleted media with non-null notification_id found")
            return 0

        count = 0
        for media in deleted_media:
            media.notification_id = None
            count += 1
            logger.debug(f"Set notification_id to NULL for media_id={media.media_id}")

        db.session.commit()
        logger.info(f"Cleaned {count} deleted media records by setting notification_id to NULL")
        return count
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cleaning deleted media notification_id: {str(e)}")
        raise

@notification_media_bp.route('/notifications/<int:notification_id>/media', methods=['GET'])
@jwt_required()
def get_notification_media(notification_id):
    try:
        logger.info(f"Fetching media for notification_id: {notification_id}")
        notification = Notification.query.get(notification_id)
        if not notification:
            logger.warning(f"Notification {notification_id} not found")
            return jsonify({'message': 'Không tìm thấy thông báo'}), 404

        # Kiểm tra và làm sạch các bản ghi đã xóa mềm
        logger.debug("Cleaning deleted media notification_id")
        clean_deleted_media_notification_id()

        # Lấy thông tin từ JWT
        claims = get_jwt()
        user_id = int(claims.get('sub'))
        # Xác định quyền admin từ claims
        is_admin = claims.get('type') == 'ADMIN'
        if not is_admin:
            logger.warning(f"User {user_id} is not an admin (type: {claims.get('type')})")
            # Kiểm tra quyền truy cập cho người dùng không phải admin
            is_recipient = False
            if notification.target_type != 'ALL':
                is_recipient = NotificationRecipient.query.filter_by(
                    notification_id=notification_id,
                    user_id=user_id
                ).first() is not None

            if not (is_recipient or notification.target_type == 'ALL'):
                logger.warning(f"User {user_id} is not authorized to access media for notification {notification_id}")
                return jsonify({'message': 'Bạn không có quyền truy cập media của thông báo này'}), 403

        file_type = request.args.get('file_type')
        logger.debug(f"Filtering media with file_type: {file_type}")

        query = NotificationMedia.query.filter_by(notification_id=notification_id, is_deleted=False)
        if file_type in ['image', 'video', 'document']:
            query = query.filter_by(file_type=file_type)

        media_items = query.all()
        media_list = [m.to_dict() for m in media_items]
        logger.info(f"Successfully fetched {len(media_list)} media items for notification {notification_id}: {media_list}")
        return jsonify({
            'media': media_list,
            'total': len(media_list),
            'pages': 1,
            'current_page': 1
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving media for notification {notification_id}: {str(e)}", exc_info=True)
        return jsonify({'message': 'Lỗi server không xác định', 'error': str(e)}), 500

@notification_media_bp.route('/notification_media/<path:filename>', methods=['GET'])
def serve_notification_media(filename):
    try:
        upload_folder = current_app.config.get('NOTIFICATION_MEDIA_BASE', 'Uploads/notification_media')
        
        # Kiểm tra đường dẫn file
        full_path = os.path.join(upload_folder, filename)
        logger.info(f"Serving media: {filename}, full path: {full_path}")

        if not os.path.exists(full_path):
            logger.error(f"Media file not found at: {full_path}")
            return jsonify({'message': f'Tệp media không tồn tại tại: {full_path}'}), 404

        # Kiểm tra quyền đọc file
        if not os.access(full_path, os.R_OK):
            logger.error(f"File is not readable: {full_path}")
            return jsonify({'message': f'Không thể đọc file media: {filename}'}), 500

        # Xác định Content-Type dựa trên phần mở rộng file
        content_type, _ = mimetypes.guess_type(full_path)
        if not content_type:
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            content_type = {
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'mp4': 'video/mp4',
                'avi': 'video/x-msvideo',
                'pdf': 'application/pdf',
                'doc': 'application/msword',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            }.get(ext, 'application/octet-stream')
            logger.warning(f"Could not determine Content-Type for {filename}, defaulting to {content_type}")

        # Serve file
        response = send_from_directory(upload_folder, filename)
        response.headers['Content-Type'] = content_type
        if content_type.startswith('video'):
            response.headers['Content-Disposition'] = 'inline'
            response.headers['Accept-Ranges'] = 'bytes'
        elif content_type.startswith('application'):
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        logger.info(f"Successfully served media: {filename} with Content-Type: {content_type}")
        return response
    except Exception as e:
        logger.error(f"Error serving media {filename}: {str(e)}", exc_info=True)
        return jsonify({'message': f'Lỗi khi phục vụ media: {str(e)}'}), 500

# Get media for multiple notifications (Admin)
@notification_media_bp.route('/admin/notifications/media/batch', methods=['GET'])
@admin_required()
def get_batch_notification_media():
    try:
        notification_ids = request.args.getlist('notification_ids', type=int)
        if not notification_ids:
            logger.warning("No notification_ids provided")
            return jsonify({'message': 'Yêu cầu danh sách notification_ids'}), 400

        media_items = NotificationMedia.query.filter(
            NotificationMedia.notification_id.in_(notification_ids),
            NotificationMedia.is_deleted == False
        ).all()

        media_dict = {}
        for media in media_items:
            if media.notification_id not in media_dict:
                media_dict[media.notification_id] = []
            media_dict[media.notification_id].append(media.to_dict())

        return jsonify(media_dict), 200
    except Exception as e:
        logger.error(f"Error retrieving batch media: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Add media to an existing notification (Admin)
@notification_media_bp.route('/admin/notifications/<int:notification_id>/media', methods=['POST'])
@admin_required()
def add_notification_media(notification_id):
    try:
        # Kiểm tra content type
        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Invalid content type for media upload")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        # Kiểm tra thông báo tồn tại
        notification = Notification.query.get(notification_id)
        if not notification:
            logger.warning(f"Notification {notification_id} not found")
            return jsonify({'message': 'Không tìm thấy thông báo'}), 404

        # Kiểm tra số lượng file
        files = request.files.getlist('media')
        if len(files) > MAX_FILES:
            logger.warning(f"Too many files uploaded: {len(files)} > {MAX_FILES}")
            return jsonify({'message': f'Tối đa {MAX_FILES} file được phép upload'}), 400

        current_media_count = NotificationMedia.query.filter_by(notification_id=notification_id, is_deleted=False).count()
        if current_media_count + len(files) > MAX_FILES:
            logger.warning(f"Total files exceed limit: {current_media_count + len(files)} > {MAX_FILES}")
            return jsonify({'message': f'Tổng số file vượt quá {MAX_FILES}'}), 400

        data = request.form
        image_count = 0
        video_count = 0
        document_count = 0
        media_list = []
        saved_files = []

        upload_folder = current_app.config.get('NOTIFICATION_MEDIA_BASE', 'Uploads/notification_media')
        os.makedirs(upload_folder, exist_ok=True)

        # Lấy thông tin admin từ JWT
        claims = get_jwt()
        admin_id = int(claims.get('sub'))
        admin_name = re.sub(r'[^\w\-]', '_', claims.get('fullname', 'Admin'))

        # Tạo thư mục con dựa trên notification_id, target_type và admin_name
        folder_name = f"{notification_id}_{notification.target_type}_{admin_name}"
        media_folder = os.path.join(upload_folder, folder_name)
        os.makedirs(media_folder, exist_ok=True)

        # Kiểm tra tổng kích thước file
        total_size = 0
        for file in files:
            file.seek(0, os.SEEK_END)
            total_size += file.tell()
            file.seek(0)
        if total_size > MAX_TOTAL_SIZE:
            logger.warning(f"Total file size too large: {total_size} > {MAX_TOTAL_SIZE}")
            return jsonify({'message': f'Tổng kích thước file vượt quá {MAX_TOTAL_SIZE // (1024 * 1024)}MB'}), 400

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

        for index, file in enumerate(files):
            if file and allowed_file(file.filename):
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)

                file_type = get_file_type(file.filename)
                if file_type == 'image':
                    if file_size > MAX_IMAGE_SIZE:
                        logger.warning(f"Image too large: {file.filename}, size: {file_size}")
                        return jsonify({'message': f'Ảnh {file.filename} vượt quá kích thước cho phép ({MAX_IMAGE_SIZE // (1024 * 1024)}MB)'}), 400
                    image_count += 1
                    if current_image_count + image_count > MAX_IMAGES:
                        logger.warning(f"Too many images: {current_image_count + image_count} > {MAX_IMAGES}")
                        return jsonify({'message': f'Tối đa {MAX_IMAGES} ảnh được phép upload'}), 400
                elif file_type == 'video':
                    if file_size > MAX_VIDEO_SIZE:
                        logger.warning(f"Video too large: {file.filename}, size: {file_size}")
                        return jsonify({'message': f'Video {file.filename} vượt quá kích thước cho phép ({MAX_VIDEO_SIZE // (1024 * 1024)}MB)'}), 400
                    video_count += 1
                else:  # document
                    if file_size > MAX_DOCUMENT_SIZE:
                        logger.warning(f"Document too large: {file.filename}, size: {file_size}")
                        return jsonify({'message': f'Tài liệu {file.filename} vượt quá kích thước cho phép ({MAX_DOCUMENT_SIZE // (1024 * 1024)}MB)'}), 400
                    document_count += 1
                    if current_document_count + document_count > MAX_DOCUMENTS:
                        logger.warning(f"Too many documents: {current_document_count + document_count} > {MAX_DOCUMENTS}")
                        return jsonify({'message': f'Tối đa {MAX_DOCUMENTS} tài liệu được phép upload'}), 400

                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower()
                notification_type_name = "notification"
                unique_filename = generate_filename(notification_type_name, notification.created_at, ext, media_folder)
                file_path = os.path.join(media_folder, unique_filename)
                file.save(file_path)
                saved_files.append(file_path)

                # Lưu media_url bao gồm thư mục con
                relative_path = f"{folder_name}/{unique_filename}"
                media = NotificationMedia(
                    notification_id=notification_id,
                    media_url=relative_path,
                    alt_text=data.get(f'alt_text_{index}', ''),
                    is_primary=(current_media_count + index == 0 and NotificationMedia.query.filter_by(notification_id=notification_id, is_primary=True, is_deleted=False).count() == 0),
                    sort_order=current_media_count + index,
                    file_type=file_type,
                    file_size=file_size
                )
                db.session.add(media)
                media_list.append(media.to_dict())

        db.session.commit()
        logger.info(f"Added {len(files)} media files for notification {notification_id}: {image_count} images, {video_count} videos, {document_count} documents")
        return jsonify({
            'message': f'Thêm {len(files)} file thành công ({image_count} ảnh, {video_count} video, {document_count} tài liệu)',
            'media': media_list
        }), 201

    except Exception as e:
        db.session.rollback()
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
                except OSError:
                    logger.warning(f"Failed to clean up file: {file_path}")
        logger.error(f"Error adding media for notification {notification_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Update media (Admin)
@notification_media_bp.route('/admin/notifications/media/<int:media_id>', methods=['PUT'])
@admin_required()
def update_notification_media(media_id):
    try:
        media = NotificationMedia.query.get(media_id)
        if not media or media.is_deleted:
            logger.warning(f"Media {media_id} not found or deleted")
            return jsonify({'message': 'Không tìm thấy file media'}), 404

        data = request.get_json()
        media.alt_text = data.get('alt_text', media.alt_text)
        is_primary = data.get('is_primary', media.is_primary)
        sort_order = data.get('sort_order', media.sort_order)

        if is_primary and not media.is_primary:
            NotificationMedia.query.filter_by(notification_id=media.notification_id, is_primary=True).update({'is_primary': False})
            media.is_primary = True

        if sort_order is not None:
            media.sort_order = sort_order

        db.session.commit()
        logger.info(f"Updated media {media_id}")
        return jsonify(media.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating media {media_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Delete media (Admin)
@notification_media_bp.route('/admin/notifications/media/<int:media_id>', methods=['DELETE'])
@admin_required()
def delete_notification_media(media_id):
    try:
        media = NotificationMedia.query.get(media_id)
        if not media or media.is_deleted:
            logger.warning(f"Media {media_id} not found or deleted")
            return jsonify({'message': 'Không tìm thấy file media'}), 404

        media.is_deleted = True
        media.deleted_at = datetime.utcnow()
        media.notification_id = None  # Đặt notification_id thành NULL

        file_path = os.path.join(current_app.config.get('NOTIFICATION_MEDIA_BASE', 'Uploads/notification_media'), media.media_url)
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted file: {file_path}")

        if media.is_primary:
            next_media = NotificationMedia.query.filter_by(notification_id=media.notification_id, is_deleted=False).order_by(NotificationMedia.sort_order).first()
            if next_media:
                next_media.is_primary = True

        db.session.commit()
        logger.info(f"Soft deleted media {media_id} and set notification_id to NULL")
        return jsonify({'message': 'Xóa file media thành công'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting media {media_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500