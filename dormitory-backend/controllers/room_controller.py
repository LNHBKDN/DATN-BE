from flask import Blueprint, request, jsonify, current_app
from extensions import db
from models.room import Room
from models.contract import Contract
from models.user import User
from models.report import Report
from models.area import Area
from models.roomimage import RoomImage
from controllers.auth_controller import admin_required
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import func
import logging
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import uuid
from unidecode import unidecode
import re

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

room_bp = Blueprint('room', __name__)

# Hàm chuẩn hóa tên (loại bỏ dấu tiếng Việt và ký tự đặc biệt)
def normalize_name(name):
    normalized = unidecode(name)
    normalized = re.sub(r'[^a-zA-Z0-9]', '_', normalized)
    return normalized

def update_current_person_number(room_id=None):
    """Cập nhật current_person_number hiệu quả cho một phòng hoặc tất cả phòng."""
    try:
        contract_counts = db.session.query(
            Contract.room_id,
            func.count().label('active_count')
        ).filter(
            Contract.status == 'ACTIVE'
        ).group_by(
            Contract.room_id
        ).subquery()

        if room_id:
            rooms_query = Room.query.filter_by(room_id=room_id)
        else:
            rooms_query = Room.query

        for room in rooms_query:
            active_count = db.session.query(contract_counts.c.active_count).filter(contract_counts.c.room_id == room.room_id).scalar() or 0
            room.current_person_number = active_count
            old_status = room.status
            if room.status not in ['MAINTENANCE', 'DISABLED']:
                room.status = 'OCCUPIED' if active_count >= room.capacity else 'AVAILABLE'
                if old_status != room.status:
                    logger.info(f"Room {room.room_id}: Changed status from {old_status} to {room.status}")
            else:
                logger.info(f"Room {room.room_id}: Skipped status update (current status: {room.status})")

        db.session.commit()
        logger.info(f"Updated current_person_number for {'room ' + str(room_id) if room_id else 'all rooms'}")
        return True
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Database error updating current_person_number: {str(e)}")
        return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error updating current_person_number: {str(e)}")
        return False

# Lấy danh sách tất cả phòng (public, user, admin)
@room_bp.route('/rooms', methods=['GET'])
def get_rooms():
    try:
        if not update_current_person_number():
            return jsonify({'message': 'Lỗi khi cập nhật số lượng người trong phòng'}), 500

        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        min_capacity = request.args.get('min_capacity', type=int)
        max_capacity = request.args.get('max_capacity', type=int)
        min_price = request.args.get('min_price', type=float)
        max_price = request.args.get('max_price', type=float)
        available = request.args.get('available', type=bool)
        search = request.args.get('search', '')
        area_id = request.args.get('area_id', type=int)

        query = Room.query.filter_by(is_deleted=False)
        if min_capacity:
            query = query.filter(Room.capacity >= min_capacity)
        if max_capacity:
            query = query.filter(Room.capacity <= max_capacity)
        if min_price:
            query = query.filter(Room.price >= min_price)
        if max_price:
            query = query.filter(Room.price <= max_price)
        if available:
            query = query.filter(Room.current_person_number < Room.capacity)
        if search:
            query = query.filter(Room.name.ilike(f'%{search}%') | Room.description.ilike(f'%{search}%'))
        if area_id:
            query = query.filter(Room.area_id == area_id)

        rooms = query.paginate(page=page, per_page=limit)
        return jsonify({
            'rooms': [room.to_dict() for room in rooms.items],
            'total': rooms.total,
            'pages': rooms.pages,
            'current_page': rooms.page
        }), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching rooms: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

# Lấy chi tiết phòng theo ID
@room_bp.route('/rooms/<int:room_id>', methods=['GET'])
def get_room_by_id(room_id):
    try:
        if not update_current_person_number(room_id):
            return jsonify({'message': 'Không tìm thấy phòng hoặc lỗi khi cập nhật số lượng người'}), 404

        room = Room.query.filter_by(room_id=room_id, is_deleted=False).first()
        if room:
            return jsonify(room.to_dict()), 200
        return jsonify({'message': 'Không tìm thấy phòng'}), 404
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@room_bp.route('/admin/rooms', methods=['POST'])
@admin_required()
def create_room():
    logger.info(f"Received request to /admin/rooms with method: {request.method}, Content-Type: {request.content_type}")
    try:
        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Yêu cầu không phải multipart/form-data")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        data = request.form
        name = data.get('name')
        capacity = data.get('capacity', type=int)
        price = data.get('price', type=float)
        area_id = data.get('area_id', type=int)
        description = data.get('description')

        logger.info(f"Request data: name={name}, capacity={capacity}, price={price}, area_id={area_id}, description={description}")

        if not all([name, capacity, price, area_id]):
            logger.warning("Thiếu thông tin bắt buộc: name, capacity, price, area_id")
            return jsonify({'message': 'Yêu cầu name, capacity, price và area_id'}), 400

        # Kiểm tra khu vực
        area = Area.query.get(area_id)
        if not area:
            logger.warning(f"Area {area_id} not found")
            return jsonify({'message': 'Không tìm thấy khu vực'}), 404

        # Kiểm tra trùng lặp tên phòng
        if Room.query.filter_by(name=name).first():
            logger.warning(f"Room name already exists: {name}")
            return jsonify({'message': 'Tên phòng đã tồn tại'}), 400

        # Tạo phòng
        room = Room(
            name=name,
            capacity=capacity,
            price=price,
            description=description,
            area_id=area_id
        )
        db.session.add(room)
        db.session.flush()  # Lấy room_id trước khi commit

        # Xử lý media
        files = request.files.getlist('images')
        if not files or all(file.filename == '' for file in files):
            logger.warning("Không có file media hợp lệ: room_id=%s", room.room_id)

        max_media = 20
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi'}  # Thêm mp4, avi
        max_file_size = 100 * 1024 * 1024  # 100MB
        saved_files = []
        uploaded_media = []

        if files:
            if len(files) > max_media:
                logger.warning(f"Too many media files uploaded: {len(files)} > {max_media}")
                return jsonify({'message': f'Chỉ được tải lên tối đa {max_media} file'}), 400

            # Tạo thư mục lưu trữ media
            upload_folder = os.path.join(current_app.config['ROOM_IMAGES_BASE'])
            os.makedirs(upload_folder, exist_ok=True)

            # Kiểm tra file media
            for file in files:
                if not file or not file.filename:
                    logger.warning("Empty file in upload list")
                    return jsonify({'message': 'Danh sách chứa file rỗng'}), 400

                if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
                    logger.warning(f"Invalid file extension: {file.filename}")
                    return jsonify({'message': f'File {file.filename}: Chỉ hỗ trợ định dạng png, jpg, jpeg, gif, mp4, avi'}), 400

                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                if file_size > max_file_size:
                    logger.warning(f"File too large: {file.filename}, size: {file_size}")
                    return jsonify({'message': f'File {file.filename}: Vượt quá kích thước tối đa 100MB'}), 400
                file.seek(0)

            # Lưu media
            primary_set = False
            for index, file in enumerate(files):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                file_path = os.path.join(upload_folder, filename)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)

                file.save(file_path)
                saved_files.append(file_path)

                is_primary = data.get(f'is_primary_{index}', False, type=bool)
                if is_primary and not primary_set:
                    RoomImage.query.filter_by(room_id=room.room_id, is_primary=True).update({'is_primary': False})
                    primary_set = True
                elif is_primary:
                    is_primary = False

                file_type = 'video' if ext in {'mp4', 'avi'} else 'image'
                media = RoomImage(
                    room_id=room.room_id,
                    image_url=filename,
                    alt_text=data.get(f'alt_text_{index}', ''),
                    is_primary=is_primary,
                    sort_order=data.get(f'sort_order_{index}', index, type=int),
                    uploaded_at=datetime.utcnow(),
                    file_type=file_type,
                    file_size=file_size
                )
                db.session.add(media)
                uploaded_media.append(media)

        try:
            db.session.commit()
            logger.info(f"Created room {room.room_id} with {len(uploaded_media)} media files")
            return jsonify(room.to_dict()), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
            logger.error(f"Database error creating room: {str(e)}")
            return jsonify({'message': 'Lỗi cơ sở dữ liệu khi tạo phòng'}), 500
        except OSError as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            logger.error(f"File system error creating room: {str(e)}")
            return jsonify({'message': 'Lỗi hệ thống khi lưu file media'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error creating room: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định'}), 500

# Cập nhật phòng và quản lý media (Admin)
@room_bp.route('/admin/rooms/<int:room_id>', methods=['PUT'])
@admin_required()
def update_room(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found")
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        if not request.content_type.startswith('multipart/form-data'):
            logger.warning("Yêu cầu không phải multipart/form-data")
            return jsonify({'message': 'Yêu cầu multipart/form-data'}), 400

        data = request.form
        name = data.get('name', room.name)
        capacity = data.get('capacity', room.capacity, type=int)
        price = data.get('price', room.price, type=float)
        description = data.get('description', room.description)
        status = data.get('status', room.status)
        area_id = data.get('area_id', room.area_id, type=int)

        # Validate status
        if status not in Room.ALLOWED_STATUSES:
            logger.warning(f"Invalid status provided: {status}")
            return jsonify({'message': f'Trạng thái không hợp lệ. Phải là một trong {Room.ALLOWED_STATUSES}'}), 400

        # Kiểm tra khu vực
        area = Area.query.get(area_id)
        if not area:
            logger.warning(f"Area {area_id} not found")
            return jsonify({'message': 'Không tìm thấy khu vực'}), 404

        # Kiểm tra trùng lặp tên phòng
        if name != room.name:
            existing_room = Room.query.filter_by(name=name).first()
            if existing_room and existing_room.room_id != room_id:
                logger.warning(f"Room name already exists: {name}")
                return jsonify({'message': 'Tên phòng đã tồn tại'}), 400

        # Cập nhật thông tin phòng
        room.name = name
        room.capacity = capacity
        room.price = price
        room.description = description
        room.status = status
        room.area_id = area_id

        # Xử lý xóa media
        image_ids_to_delete = data.get('image_ids_to_delete', '').split(',')
        image_ids_to_delete = [int(id) for id in image_ids_to_delete if id.strip().isdigit()]
        if image_ids_to_delete:
            media_to_delete = RoomImage.query.filter(
                RoomImage.image_id.in_(image_ids_to_delete),
                RoomImage.room_id == room_id,
                RoomImage.is_deleted == False
            ).all()
            roomname = f"{room.name} - {area.name}"
            roomname = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in roomname)
            trash_folder = os.path.join(current_app.config['UPLOAD_BASE'], 'trash', 'roomimage', roomname)
            os.makedirs(trash_folder, exist_ok=True)

            for media in media_to_delete:
                media.is_deleted = True
                media.deleted_at = datetime.utcnow()
                absolute_path = os.path.join(current_app.config['ROOM_IMAGES_BASE'], media.image_url)
                if os.path.exists(absolute_path):
                    trash_filename = f"{uuid.uuid4().hex}_{os.path.basename(media.image_url)}"
                    trash_path = os.path.join(trash_folder, trash_filename)
                    try:
                        os.rename(absolute_path, trash_path)
                        logger.info(f"Moved media {media.image_url} to trash: {trash_path}")
                    except OSError as e:
                        logger.warning(f"Failed to move media to trash: {media.image_url}, error: {str(e)}")
                else:
                    logger.warning(f"Media file not found: {absolute_path}")
                logger.debug("Soft delete media: image_id=%s", media.image_id)

        # Xử lý thêm media mới
        files = request.files.getlist('images')
        current_media_count = RoomImage.query.filter_by(
            room_id=room_id,
            is_deleted=False
        ).count()
        max_media = 20
        if len(files) + current_media_count > max_media:
            logger.warning(f"Too many media files: {len(files) + current_media_count} > {max_media}")
            return jsonify({'message': f'Tổng số file (hiện tại + mới) không được vượt quá {max_media}'}), 400

        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi'}  # Thêm mp4, avi
        max_file_size = 100 * 1024 * 1024  # 100MB
        saved_files = []
        uploaded_media = []

        if files:
            roomname = f"{room.name} - {area.name}"
            roomname = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in roomname)
            upload_folder = os.path.join(current_app.config['ROOM_IMAGES_BASE'])
            os.makedirs(upload_folder, exist_ok=True)

            for file in files:
                if not file or not file.filename:
                    logger.warning("Empty file in upload list")
                    return jsonify({'message': 'Danh sách chứa file rỗng'}), 400

                if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
                    logger.warning(f"Invalid file extension: {file.filename}")
                    return jsonify({'message': f'File {file.filename}: Chỉ hỗ trợ định dạng png, jpg, jpeg, gif, mp4, avi'}), 400

                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                if file_size > max_file_size:
                    logger.warning(f"File too large: {file.filename}, size: {file_size}")
                    return jsonify({'message': f'File {file.filename}: Vượt quá kích thước tối đa 100MB'}), 400
                file.seek(0)

            primary_set = current_media_count > 0 and RoomImage.query.filter_by(room_id=room_id, is_primary=True, is_deleted=False).first()
            for index, file in enumerate(files):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                file_path = os.path.join(upload_folder, filename)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)

                file.save(file_path)
                saved_files.append(file_path)

                is_primary = data.get(f'is_primary_{index}', False, type=bool)
                if is_primary and not primary_set:
                    RoomImage.query.filter_by(room_id=room_id, is_primary=True).update({'is_primary': False})
                    primary_set = True
                elif is_primary:
                    is_primary = False

                file_type = 'video' if ext in {'mp4', 'avi'} else 'image'
                media = RoomImage(
                    room_id=room_id,
                    image_url=filename,
                    alt_text=data.get(f'alt_text_{index}', ''),
                    is_primary=is_primary,
                    sort_order=data.get(f'sort_order_{index}', index + current_media_count, type=int),
                    uploaded_at=datetime.utcnow(),
                    file_type=file_type,
                    file_size=file_size
                )
                db.session.add(media)
                uploaded_media.append(media)

        try:
            db.session.commit()
            logger.info(f"Updated room {room_id} with {len(uploaded_media)} new media files")
            return jsonify(room.to_dict()), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Cleaned up file: {file_path}")
            logger.error(f"Database error updating room {room_id}: {str(e)}")
            return jsonify({'message': 'Lỗi cơ sở dữ liệu khi cập nhật phòng'}), 500
        except OSError as e:
            db.session.rollback()
            for file_path in saved_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            logger.error(f"File system error updating room {room_id}: {str(e)}")
            return jsonify({'message': 'Lỗi hệ thống khi lưu file media'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error updating room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server không xác định', 'error': str(e)}), 500

# Lấy báo cáo của phòng (Admin)
@room_bp.route('/admin/rooms/<int:room_id>/reports', methods=['GET'])
@admin_required()
def get_room_reports(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'message': 'Không tìm thấy phòng'}), 404
        
        reports = Report.query.filter_by(room_id=room_id).all()
        return jsonify([report.to_dict() for report in reports]), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching reports for room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

# Lấy người dùng trong phòng (Admin)
@room_bp.route('/admin/rooms/<int:room_id>/users', methods=['GET'])
@admin_required()
def get_users_in_room(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'message': 'Không tìm thấy phòng'}), 404
        
        contracts = Contract.query.filter_by(room_id=room_id, status='ACTIVE').all()
        user_ids = [contract.user_id for contract in contracts]
        users = User.query.filter(User.user_id.in_(user_ids)).all()
        return jsonify([user.to_dict() for user in users]), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching users in room {room_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

# Xóa phòng (Admin)
@room_bp.route('/admin/rooms/<int:room_id>', methods=['DELETE'])
@admin_required()
def delete_room(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            logger.warning("Room not found: room_id=%s", room_id)
            return jsonify({'message': 'Không tìm thấy phòng'}), 404

        active_contracts = Contract.query.filter_by(room_id=room_id, status='ACTIVE').count()
        if active_contracts > 0:
            logger.warning("Cannot delete room with active contracts: room_id=%s", room_id)
            return jsonify({'message': 'Không thể xóa phòng vì vẫn còn hợp đồng đang hoạt động'}), 400

        pending_reports = Report.query.filter_by(room_id=room_id, status='PENDING').count()
        if pending_reports > 0:
            logger.warning("Cannot delete room with pending reports: room_id=%s", room_id)
            return jsonify({'message': 'Không thể xóa phòng vì vẫn còn báo cáo chưa giải quyết'}), 400

        # Xóa mềm các ảnh liên quan
        room_images = RoomImage.query.filter_by(room_id=room_id).all()
        for image in room_images:
            image.is_deleted = True
            image.deleted_at = datetime.utcnow()
            image.room_id = None
            logger.debug("Marked RoomImage as deleted: image_id=%s, room_id=None", image.image_id)

        # Xóa mềm phòng
        room.is_deleted = True
        room.deleted_at = datetime.utcnow()
        logger.debug(f"Marked Room as deleted: room_id={room_id}")

        try:
            db.session.commit()
            logger.info(f"Room soft deleted: room_id={room_id}")
            return jsonify({'message': 'Xóa phòng thành công'}), 200
        except IntegrityError as e:
            db.session.rollback()
            logger.error(f"Integrity error deleting room: room_id={room_id}, error={str(e)}")
            return jsonify({'message': 'Lỗi cơ sở dữ liệu: Không thể xóa phòng do ràng buộc dữ liệu'}), 409
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error deleting room: room_id={room_id}, error={str(e)}")
            return jsonify({'message': 'Lỗi cơ sở dữ liệu khi xóa phòng'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error deleting room: room_id={room_id}, error={str(e)}")
        return jsonify({'message': 'Lỗi server không xác định', 'error': str(e)}), 500