from flask import Blueprint, request, jsonify, send_from_directory
from extensions import db
from models.notification import Notification
from models.notification_media import NotificationMedia
from controllers.auth_controller import admin_required
import os
import uuid
from werkzeug.utils import secure_filename
from datetime import datetime

notification_media_bp = Blueprint('notification_media', __name__)

# Đường dẫn lưu file
UPLOAD_FOLDER = 'uploads/notification_media'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'mp4', 'avi'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_FILES = 10  # Giới hạn số file tối đa

# Kiểm tra file hợp lệ
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Tạo thư mục nếu chưa tồn tại
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Get all media for a notification (Admin)
@notification_media_bp.route('/admin/notifications/<int:notification_id>/media', methods=['GET'])
@admin_required()
def get_notification_media(notification_id):
    notification = Notification.query.get(notification_id)
    if not notification:
        return jsonify({'message': 'Không tìm thấy thông báo'}), 404

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    file_type = request.args.get('file_type')  # image, video

    query = NotificationMedia.query.filter_by(notification_id=notification_id, is_deleted=False)
    if file_type in ['image', 'video']:
        query = query.filter_by(file_type=file_type)

    media = query.paginate(page=page, per_page=limit)
    return jsonify({
        'media': [m.to_dict() for m in media.items],
        'total': media.total,
        'pages': media.pages,
        'current_page': media.page
    }), 200

# Add media to an existing notification (Admin)
@notification_media_bp.route('/admin/notifications/<int:notification_id>/media', methods=['POST'])
@admin_required()
def add_notification_media(notification_id):
    if not request.content_type.startswith('multipart/form-data'):
        return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

    notification = Notification.query.get(notification_id)
    if not notification:
        return jsonify({'message': 'Không tìm thấy thông báo'}), 404

    files = request.files.getlist('media')
    if len(files) > MAX_FILES:
        return jsonify({'message': f'Tối đa {MAX_FILES} file được phép upload'}), 400

    current_media_count = NotificationMedia.query.filter_by(notification_id=notification_id, is_deleted=False).count()
    if current_media_count + len(files) > MAX_FILES:
        return jsonify({'message': f'Tổng số file vượt quá {MAX_FILES}'}), 400

    data = request.form
    image_count = 0
    video_count = 0
    media_list = []

    for index, file in enumerate(files):
        if file and allowed_file(file.filename):
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            if file_size > MAX_FILE_SIZE:
                return jsonify({'message': f'File {file.filename} vượt quá kích thước cho phép (100MB)'}), 400
            file.seek(0)

            filename = secure_filename(file.filename)
            ext = filename.rsplit('.', 1)[1].lower()
            unique_filename = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            file.save(file_path)

            file_type = 'image' if ext in {'jpg', 'jpeg', 'png'} else 'video'
            if file_type == 'image':
                image_count += 1
            else:
                video_count += 1

            media = NotificationMedia(
                notification_id=notification_id,
                media_url=f"/notification_media/{unique_filename}",
                alt_text=data.get(f'alt_text_{index}', ''),
                is_primary=(current_media_count + index == 0 and NotificationMedia.query.filter_by(notification_id=notification_id, is_primary=True, is_deleted=False).count() == 0),
                sort_order=current_media_count + index,
                file_type=file_type,
                file_size=file_size
            )
            db.session.add(media)
            media_list.append(media.to_dict())

    db.session.commit()
    return jsonify({
        'message': f'Thêm {len(files)} file thành công ({image_count} ảnh, {video_count} video)',
        'media': media_list
    }), 201

# Update media (Admin)
@notification_media_bp.route('/admin/notifications/media/<int:media_id>', methods=['PUT'])
@admin_required()
def update_notification_media(media_id):
    media = NotificationMedia.query.get(media_id)
    if not media or media.is_deleted:
        return jsonify({'message': 'Không tìm thấy file media'}), 404

    data = request.get_json()
    media.alt_text = data.get('alt_text', media.alt_text)
    is_primary = data.get('is_primary', media.is_primary)
    sort_order = data.get('sort_order', media.sort_order)

    if is_primary and not media.is_primary:
        # Đặt is_primary của các file khác thành False
        NotificationMedia.query.filter_by(notification_id=media.notification_id, is_primary=True).update({'is_primary': False})
        media.is_primary = True

    if sort_order is not None:
        media.sort_order = sort_order

    db.session.commit()
    return jsonify(media.to_dict()), 200

# Delete media (Admin)
@notification_media_bp.route('/admin/notifications/media/<int:media_id>', methods=['DELETE'])
@admin_required()
def delete_notification_media(media_id):
    media = NotificationMedia.query.get(media_id)
    if not media or media.is_deleted:
        return jsonify({'message': 'Không tìm thấy file media'}), 404

    # Đánh dấu xóa mềm
    media.is_deleted = True
    media.deleted_at = datetime.utcnow()

    # Xóa file vật lý
    file_path = os.path.join(UPLOAD_FOLDER, media.media_url.split('/')[-1])
    if os.path.exists(file_path):
        os.remove(file_path)

    # Nếu media bị xóa là primary, chọn media khác làm primary
    if media.is_primary:
        next_media = NotificationMedia.query.filter_by(notification_id=media.notification_id, is_deleted=False).order_by(NotificationMedia.sort_order).first()
        if next_media:
            next_media.is_primary = True

    db.session.commit()
    return jsonify({'message': 'Xóa file media thành công'}), 200

# Serve media file
@notification_media_bp.route('/notification_media/<filename>', methods=['GET'])
def serve_notification_media(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)