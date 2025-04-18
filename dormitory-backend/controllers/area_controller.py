from flask import Blueprint, request, jsonify
from extensions import db
from models.area import Area
from controllers.auth_controller import admin_required

area_bp = Blueprint('area', __name__)

# Lấy danh sách tất cả khu vực
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

# Lấy thông tin khu vực theo ID
@area_bp.route('/areas/<int:area_id>', methods=['GET'])
@admin_required()
def get_area_by_id(area_id):
    area = Area.query.get(area_id)
    if area:
        return jsonify(area.to_dict()), 200
    return jsonify({'message': 'Không tìm thấy khu vực'}), 404

# Tạo khu vực mới
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

# Cập nhật khu vực
@area_bp.route('/admin/areas/<int:area_id>', methods=['PUT'])
@admin_required()
def update_area(area_id):
    area = Area.query.get(area_id)
    if not area:
        return jsonify({'message': 'Không tìm thấy khu vực'}), 404
    
    data = request.get_json()
    new_name = data.get('name', area.name)
    if new_name != area.name:  # Chỉ kiểm tra nếu tên thay đổi
        existing_area = Area.query.filter_by(name=new_name).first()
        if existing_area and existing_area.area_id != area_id:
            return jsonify({'message': 'Tên khu vực đã tồn tại'}), 400
    area.name = new_name
    db.session.commit()
    return jsonify(area.to_dict()), 200

# Xóa khu vực
@area_bp.route('/admin/areas/<int:area_id>', methods=['DELETE'])
@admin_required()
def delete_area(area_id):
    area = Area.query.get(area_id)
    if not area:
        return jsonify({'message': 'Không tìm thấy khu vực'}), 404
    if area.rooms:
        return jsonify({'message': 'Không thể xóa khu vực vì có phòng liên kết'}), 400
    
    db.session.delete(area)
    try:
        db.session.commit()
        return jsonify({'message': 'Xoá thành công'}), 200  # Đổi sang mã 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"message": "Lỗi khi lưu dữ liệu vào database"}), 500