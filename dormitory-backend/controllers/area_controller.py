# controllers/area_controller.py
from flask import Blueprint, request, jsonify
from extensions import db
from models.area import Area
from models.room import Room
from models.roomimage import RoomImage
from controllers.auth_controller import admin_required
from sqlalchemy.exc import SQLAlchemyError
import os
import logging
from unidecode import unidecode
import re
from flask import current_app
import uuid
from models.user import User
from models.contract import Contract
from flask import send_file
import openpyxl
from io import BytesIO

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

area_bp = Blueprint('area', __name__)

# Hàm chuẩn hóa tên (loại bỏ dấu tiếng Việt và ký tự đặc biệt)
def normalize_name(name):
    normalized = unidecode(name)
    normalized = re.sub(r'[^a-zA-Z0-9]', '_', normalized)
    return normalized

# Lấy danh sách tất cả khu vực (public)
@area_bp.route('/public/areas', methods=['GET'])
def get_public_areas():
    try:
        areas = Area.query.all()
        return jsonify([{
            'area_id': area.area_id,
            'name': area.name
        } for area in areas]), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching public areas: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

# Lấy danh sách tất cả khu vực (admin)
@area_bp.route('/areas', methods=['GET'])
@admin_required()
def get_all_areas():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    
    areas = Area.query.paginate(page=page, per_page=limit)
    return jsonify({
        'areas': [area.to_dict() for area in areas.items],
        'total': areas.total,
        'pages': areas.pages,
        'current_page': areas.page
    }), 200

# Lấy thông tin khu vực theo ID (admin)
@area_bp.route('/areas/<int:area_id>', methods=['GET'])
@admin_required()
def get_area_by_id(area_id):
    area = Area.query.get(area_id)
    if area:
        return jsonify(area.to_dict()), 200
    return jsonify({'message': 'Không tìm thấy khu vực'}), 404

# Tạo khu vực mới (admin)
@area_bp.route('/admin/areas', methods=['POST'])
@admin_required()
def create_area():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'message': 'Yêu cầu tên khu vực'}), 400
    
    if Area.query.filter_by(name=name).first():
        return jsonify({'message': 'Tên khu vực đã tồn tại'}), 400
    
    area = Area(name=name)
    db.session.add(area)
    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"message": "Lỗi khi lưu dữ liệu vào database"}), 500
    return jsonify(area.to_dict()), 201

# Cập nhật khu vực (admin)
@area_bp.route('/admin/areas/<int:area_id>', methods=['PUT'])
@admin_required()
def update_area(area_id):
    try:
        area = Area.query.get(area_id)
        if not area:
            logger.warning(f"Khu vực không tồn tại: area_id={area_id}")
            return jsonify({'message': 'Không tìm thấy khu vực'}), 404

        data = request.get_json()
        new_name = data.get('name', area.name)
        if new_name != area.name:  # Chỉ xử lý nếu tên thay đổi
            existing_area = Area.query.filter_by(name=new_name).first()
            if existing_area and existing_area.area_id != area_id:
                return jsonify({'message': 'Tên khu vực đã tồn tại'}), 400

            old_name = area.name
            area.name = new_name
            db.session.commit()

            # Cập nhật room.name và image_url của các phòng liên quan
            rooms = Room.query.filter_by(area_id=area_id).all()
            for room in rooms:
                # Cập nhật room.name (thay thế tên khu vực cũ bằng tên mới)
                room_name_parts = room.name.split(' - ')
                if len(room_name_parts) > 1 and room_name_parts[1] == old_name:
                    room.name = f"{room_name_parts[0]} - {new_name}"

                # Cập nhật image_url của các hình ảnh liên quan
                images = RoomImage.query.filter_by(room_id=room.room_id, is_deleted=False).all()
                for image in images:
                    # Chuẩn hóa tên phòng và tên khu vực
                    old_roomname = normalize_name(f"{room_name_parts[0]} - {old_name}")
                    new_roomname = normalize_name(room.name)

                    # Tạo tên thư mục cũ và mới
                    old_folder_name = old_roomname
                    new_folder_name = new_roomname
                    old_folder_path = os.path.join(current_app.config['ROOM_IMAGES_BASE'], old_folder_name)
                    new_folder_path = os.path.join(current_app.config['ROOM_IMAGES_BASE'], new_folder_name)

                    # Đổi tên thư mục nếu tồn tại
                    if os.path.exists(old_folder_path):
                        try:
                            os.rename(old_folder_path, new_folder_path)
                            logger.debug("Đổi tên thư mục từ %s sang %s", old_folder_path, new_folder_path)
                        except OSError as e:
                            logger.error("Lỗi khi đổi tên thư mục: %s", str(e))
                            db.session.rollback()
                            return jsonify({'message': 'Lỗi khi đổi tên thư mục hình ảnh'}), 500

                    # Cập nhật image_url
                    filename = os.path.basename(image.image_url)
                    image.image_url = f"roomimage/{new_folder_name}/{filename}"

            db.session.commit()
            logger.info("Cập nhật khu vực thành công: area_id=%s, new_name=%s", area_id, new_name)
            return jsonify(area.to_dict()), 200

        # Nếu không có thay đổi tên, chỉ trả về kết quả
        return jsonify(area.to_dict()), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Lỗi cơ sở dữ liệu khi cập nhật khu vực {area_id}: {str(e)}")
        return jsonify({"message": "Lỗi khi lưu dữ liệu vào database"}), 500
    except Exception as e:
        db.session.rollback()
        logger.error(f"Lỗi không xác định khi cập nhật khu vực {area_id}: {str(e)}")
        return jsonify({'message': 'Lỗi server, vui lòng thử lại sau'}), 500

# Xóa khu vực (admin)
@area_bp.route('/admin/areas/<int:area_id>', methods=['DELETE'])
@admin_required()
def delete_area(area_id):
    area = Area.query.get(area_id)
    if not area:
        return jsonify({'message': 'Không tìm thấy khu vực'}), 404

    # Kiểm tra còn phòng nào thuộc khu vực này không (kể cả đã bị xóa mềm hay chưa)
    room_count = Room.query.filter_by(area_id=area_id, is_deleted=False).count()
    if room_count > 0:
        return jsonify({'message': 'Không thể xóa khu vực vì vẫn còn phòng thuộc khu vực này'}), 400

    db.session.delete(area)
    try:
        db.session.commit()
        return jsonify({'message': 'Xoá thành công'}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"message": "Lỗi khi lưu dữ liệu vào database"}), 500

# Lấy danh sách khu vực kèm theo số lượng sinh viên (admin)
@area_bp.route('/areas-with-student-count', methods=['GET'])
@admin_required()
def get_areas_with_student_count():
    areas = Area.query.all()
    result = []
    for area in areas:
        # Lấy tất cả phòng thuộc area này
        rooms = area.rooms
        # Đếm số sinh viên có hợp đồng ACTIVE trong các phòng này
        student_ids = set()
        for room in rooms:
            for contract in room.contracts:
                if contract.status == 'ACTIVE' and not contract.is_deleted:
                    student_ids.add(contract.user_id)
        result.append({
            'area_id': area.area_id,
            'area_name': area.name,
            'student_count': len(student_ids)
        })
    return jsonify(result), 200

@area_bp.route('/admin/areas/<int:area_id>/users', methods=['GET'])
@admin_required()
def get_users_in_area(area_id):
    try:
        area = Area.query.get(area_id)
        if not area:
            return jsonify({'message': 'Không tìm thấy khu vực'}), 404
        # Lấy tất cả phòng thuộc khu vực này
        rooms = Room.query.filter_by(area_id=area_id, is_deleted=False).all()
        room_ids = [room.room_id for room in rooms]
        # Lấy tất cả hợp đồng ACTIVE trong các phòng này
        contracts = Contract.query.filter(
            Contract.room_id.in_(room_ids),
            Contract.status == 'ACTIVE',
            Contract.is_deleted == False
        ).all()
        user_ids = {contract.user_id for contract in contracts}
        users = User.query.filter(User.user_id.in_(user_ids)).all()
        return jsonify([user.to_dict() for user in users]), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching users in area {area_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@area_bp.route('/admin/areas/<int:area_id>/users/export', methods=['GET'])
@admin_required()
def export_users_in_area(area_id):
    try:
        area = Area.query.get(area_id)
        if not area:
            return jsonify({'message': 'Không tìm thấy khu vực'}), 404
        rooms = Room.query.filter_by(area_id=area_id, is_deleted=False).all()
        room_ids = [room.room_id for room in rooms]
        contracts = Contract.query.filter(
            Contract.room_id.in_(room_ids),
            Contract.status == 'ACTIVE',
            Contract.is_deleted == False
        ).all()
        user_ids = {contract.user_id for contract in contracts}
        users = User.query.filter(User.user_id.in_(user_ids)).all()
        # Tạo workbook Excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Danh sách sinh viên"
        # Header
        ws.append(['ID', 'Họ tên', 'Email', 'MSSV', 'SĐT', 'Quê quán'])
        # Data
        for user in users:
            ws.append([
                user.user_id,
                user.fullname,
                user.email,
                user.student_code,
                user.phone,
                user.hometown
            ])
        # Lưu vào bộ nhớ và trả về file
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f"users_in_area_{area_id}.xlsx"
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error exporting users in area {area_id}: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@area_bp.route('/admin/areas/users/export', methods=['GET'])
@admin_required()
def export_all_users_in_all_areas():
    try:
        rooms = Room.query.filter_by(is_deleted=False).all()
        room_ids = [room.room_id for room in rooms]
        contracts = Contract.query.filter(
            Contract.room_id.in_(room_ids),
            Contract.status == 'ACTIVE',
            Contract.is_deleted == False
        ).all()
        user_ids = {contract.user_id for contract in contracts}
        users = User.query.filter(User.user_id.in_(user_ids)).all()
        # Tạo workbook Excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Danh sách sinh viên"
        ws.append(['ID', 'Họ tên', 'Email', 'MSSV', 'SĐT', 'Quê quán'])
        for user in users:
            ws.append([
                user.user_id,
                user.fullname,
                user.email,
                user.student_code,
                user.phone,
                user.hometown
            ])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f"users_in_all_areas.xlsx"
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error exporting all users in all areas: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500

@area_bp.route('/admin/areas/users', methods=['GET'])
@admin_required()
def get_all_users_in_all_areas():
    try:
        # Lấy tất cả phòng chưa xóa
        rooms = Room.query.filter_by(is_deleted=False).all()
        room_ids = [room.room_id for room in rooms]
        # Lấy tất cả hợp đồng ACTIVE trong các phòng này
        contracts = Contract.query.filter(
            Contract.room_id.in_(room_ids),
            Contract.status == 'ACTIVE',
            Contract.is_deleted == False
        ).all()
        user_ids = {contract.user_id for contract in contracts}
        users = User.query.filter(User.user_id.in_(user_ids)).all()
        return jsonify([user.to_dict() for user in users]), 200
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching all users in all areas: {str(e)}")
        return jsonify({'message': 'Lỗi database'}), 500