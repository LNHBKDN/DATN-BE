from flask import Blueprint, request, jsonify
from extensions import db
from models.roomimage import RoomImage
from models.room import Room
from models.area import Area
from controllers.auth_controller import admin_required
from sqlalchemy.exc import SQLAlchemyError
import os
import logging
from werkzeug.utils import secure_filename
from flask import current_app
from datetime import datetime
import uuid

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

roomimage_bp = Blueprint('roomimage', __name__)

# Tải lên nhiều hình ảnh phòng cùng lúc (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images', methods=['POST'])
@admin_required()
def upload_room_images(room_id):
    try:
        # Kiểm tra phòng tồn tại
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        # Kiểm tra khu vực
        area = Area.query.get(room.area_id)
        if not area:
            logger.warning(f"Area {room.area_id} not found for room {room_id}")
            return jsonify({'message': 'Không tìm thấy khu vực của phòng'}), 404

        # Tạo thư mục lưu trữ ảnh
        roomname = f"{room.name} - {area.name}"
        roomname = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in roomname)
        upload_folder = os.path.join(current_app.config['ROOM_IMAGES_BASE'], roomname)
        os.makedirs(upload_folder, exist_ok=True)

        # Kiểm tra file ảnh
        if 'images' not in request.files:
            logger.warning("No images in request")
            return jsonify({'message': 'Không có file ảnh (key: images)'}), 400

        files = request.files.getlist('images')
        if not files or all(file.filename == '' for file in files):
            logger.warning("Empty or invalid image files")
            return jsonify({'message': 'Không có file ảnh hợp lệ'}), 400

        # Giới hạn số lượng ảnh
        max_images = 20
        if len(files) > max_images:
            logger.warning(f"Too many images uploaded: {len(files)} > {max_images}")
            return jsonify({'message': f'Chỉ được tải lên tối đa {max_images} ảnh cùng lúc'}), 400

        images = []
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
        max_file_size = 10 * 1024 * 1024  # 10MB
        saved_files = []  # Lưu danh sách file đã lưu để xóa nếu có lỗi

        # Kiểm tra tất cả file trước khi lưu
        for file in files:
            if not file or not file.filename:
                logger.warning("Empty file in upload list")
                return jsonify({'message': 'Danh sách chứa file rỗng'}), 400

            # Kiểm tra định dạng file
            if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
                logger.warning(f"Invalid file extension: {file.filename}")
                return jsonify({'message': f'File {file.filename}: Chỉ hỗ trợ định dạng png, jpg, jpeg, gif'}), 400

            # Kiểm tra kích thước file
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            if file_size > max_file_size:
                logger.warning(f"File too large: {file.filename}, size: {file_size}")
                return jsonify({'message': f'File {file.filename}: Vượt quá kích thước tối đa 5MB'}), 400
            file.seek(0)  # Reset con trỏ file

        # Lưu file và tạo bản ghi RoomImage
        primary_set = False
        for file in files:
            # Tạo tên file duy nhất
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(upload_folder, filename)
            relative_path = os.path.join('roomimage', roomname, filename)

            # Lưu file
            file.save(file_path)
            saved_files.append(file_path)

            # Kiểm tra is_primary từ form data
            is_primary = request.form.get(f'is_primary_{filename}', False, type=bool)
            if is_primary and not primary_set:
                # Đặt các ảnh khác thành không phải primary
                RoomImage.query.filter_by(room_id=room_id, is_primary=True).update({'is_primary': False})
                primary_set = True
            elif is_primary:
                logger.warning(f"Multiple primary images attempted for room {room_id}")
                is_primary = False  # Chỉ cho phép một ảnh primary

            image = RoomImage(
                room_id=room_id,
                image_url=relative_path,
                alt_text=request.form.get(f'alt_text_{filename}', ''),
                is_primary=is_primary,
                sort_order=request.form.get(f'sort_order_{filename}', 0, type=int)
            )
            db.session.add(image)
            images.append(image)

        # Commit hàng loạt
        db.session.commit()
        logger.info(f"Uploaded {len(images)} images for room {room_id}")
        return jsonify([image.to_dict() for image in images]), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        # Xóa các file đã lưu nếu có lỗi
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
                except OSError:
                    logger.warning(f"Failed to clean up file: {file_path}")
        logger.error(f"Database error uploading images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi cơ sở dữ liệu khi lưu hình ảnh'}), 500
    except OSError as e:
        db.session.rollback()
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        logger.error(f"File system error uploading images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi hệ thống khi lưu file ảnh'}), 500
    except ValueError as e:
        logger.error(f"Value error uploading images for room {room_id}: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        for file_path in saved_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        logger.error(f"Unexpected error uploading images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Lấy danh sách ảnh phòng (Public)
@roomimage_bp.route('/rooms/<int:room_id>/images', methods=['GET'])
def get_room_images(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        images = RoomImage.query.filter_by(room_id=room_id, is_deleted=False).order_by(RoomImage.sort_order.asc()).all()
        if not images:
            logger.info(f"No images found for room {room_id}")
            return jsonify({'message': 'Không tìm thấy ảnh cho phòng này'}), 404

        logger.info(f"Retrieved {len(images)} images for room {room_id}")
        return jsonify([image.to_dict() for image in images]), 200

    except SQLAlchemyError as e:
        logger.error(f"Database error fetching images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi cơ sở dữ liệu'}), 500
    except Exception as e:
        logger.error(f"Unexpected error fetching images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Cập nhật thông tin ảnh (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/<int:image_id>', methods=['PUT'])
@admin_required()
def update_room_image_info(room_id, image_id):
    try:
        image = RoomImage.query.get(image_id)
        if not image or image.room_id != room_id or image.is_deleted:
            logger.warning(f"Image {image_id} not found or deleted for room {room_id}")
            return jsonify({'message': 'Không tìm thấy ảnh hoặc ảnh đã bị xóa'}), 404

        data = request.get_json()
        if not data:
            logger.warning("No data provided for updating image")
            return jsonify({'message': 'Thiếu dữ liệu cập nhật'}), 400

        # Cập nhật thông tin
        image.alt_text = data.get('alt_text', image.alt_text)
        is_primary = data.get('is_primary', image.is_primary)
        if is_primary and not image.is_primary:
            # Đặt các ảnh khác thành không phải primary
            RoomImage.query.filter_by(room_id=room_id, is_primary=True).update({'is_primary': False})
        image.is_primary = is_primary
        image.sort_order = data.get('sort_order', image.sort_order)

        db.session.commit()
        logger.info(f"Updated image {image_id} for room {room_id}")
        return jsonify(image.to_dict()), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error updating image {image_id}: {str(e)}")
        return jsonify({'message': 'Lỗi cơ sở dữ liệu khi cập nhật ảnh'}), 500
    except ValueError as e:
        logger.error(f"Value error updating image {image_id}: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error updating image {image_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Xóa ảnh phòng (Admin) - Soft delete và chuyển vào thư mục rác
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/<int:image_id>', methods=['DELETE'])
@admin_required()
def delete_room_image(room_id, image_id):
    try:
        image = RoomImage.query.get(image_id)
        if not image or image.room_id != room_id or image.is_deleted:
            logger.warning(f"Image {image_id} not found or deleted for room {room_id}")
            return jsonify({'message': 'Không tìm thấy ảnh hoặc ảnh đã bị xóa'}), 404

        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        area = Area.query.get(room.area_id)
        if not area:
            logger.warning(f"Area {room.area_id} not found")
            return jsonify({'message': 'Không tìm thấy khu vực của phòng'}), 404

        # Đánh dấu xóa mềm
        image.is_deleted = True
        image.deleted_at = datetime.utcnow()

        # Di chuyển file vào thư mục rác
        roomname = f"{room.name} - {area.name}"
        roomname = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in roomname)
        trash_folder = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', 'roomimage', roomname)
        os.makedirs(trash_folder, exist_ok=True)

        absolute_path = os.path.join(current_app.config['UPLOAD_BASE'], image.image_url)
        if os.path.exists(absolute_path):
            trash_filename = f"{uuid.uuid4().hex}_{os.path.basename(image.image_url)}"
            trash_path = os.path.join(trash_folder, trash_filename)
            os.rename(absolute_path, trash_path)
            logger.info(f"Moved image {image.image_url} to trash: {trash_path}")
        else:
            logger.warning(f"Image file not found: {absolute_path}")

        db.session.commit()
        logger.info(f"Soft deleted image {image_id} for room {room_id}")
        return '', 204

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error deleting image {image_id}: {str(e)}")
        return jsonify({'message': 'Lỗi cơ sở dữ liệu khi xóa ảnh'}), 500
    except OSError as e:
        logger.error(f"File system error deleting image {image_id}: {str(e)}")
        return jsonify({'message': 'Lỗi hệ thống khi di chuyển file ảnh'}), 500
    except Exception as e:
        logger.error(f"Unexpected error deleting image {image_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Sắp xếp lại thứ tự ảnh (Admin)
@roomimage_bp.route('/admin/rooms/<int:room_id>/images/reorder', methods=['POST'])
@admin_required()
def reorder_room_images(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        data = request.get_json()
        if not data or 'imageIds' not in data:
            logger.warning("No imageIds provided for reordering")
            return jsonify({'message': 'Thiếu danh sách imageIds'}), 400

        image_ids = data.get('imageIds', [])
        if not isinstance(image_ids, list):
            logger.warning("Invalid imageIds format")
            return jsonify({'message': 'imageIds phải là một danh sách'}), 400

        if not image_ids:
            logger.warning("Empty imageIds list")
            return jsonify({'message': 'Danh sách imageIds rỗng'}), 400

        # Kiểm tra các image_id
        images = RoomImage.query.filter(
            RoomImage.image_id.in_(image_ids),
            RoomImage.room_id == room_id,
            RoomImage.is_deleted == False
        ).all()
        if len(images) != len(image_ids):
            logger.warning(f"Invalid or deleted image IDs provided: {image_ids}")
            return jsonify({'message': 'Một hoặc nhiều image_id không hợp lệ, đã xóa, hoặc không thuộc phòng này'}), 400

        # Cập nhật sort_order
        image_map = {img.image_id: img for img in images}
        for sort_order, image_id in enumerate(image_ids):
            image = image_map.get(image_id)
            if image:
                image.sort_order = sort_order

        db.session.commit()
        logger.info(f"Reordered images for room {room_id}")
        return jsonify({'message': 'Sắp xếp lại ảnh thành công'}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error reordering images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi cơ sở dữ liệu khi sắp xếp ảnh'}), 500
    except ValueError as e:
        logger.error(f"Value error reordering images for room {room_id}: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error reordering images for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500