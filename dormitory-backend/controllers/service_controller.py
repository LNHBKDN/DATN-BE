from flask import Blueprint, request, jsonify
from extensions import db
from models.service import Service
from models.service_rate import ServiceRate
from controllers.auth_controller import admin_required

service_bp = Blueprint('service', __name__)

# Lấy danh sách tất cả dịch vụ (Admin)
@service_bp.route('/services', methods=['GET'])

def get_all_services():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    services = Service.query.paginate(page=page, per_page=limit)
    return jsonify({
        'services': [service.to_dict() for service in services.items],
        'total': services.total,
        'pages': services.pages,
        'current_page': services.page
    }), 200

# Lấy chi tiết dịch vụ theo ID (Admin)
@service_bp.route('/services/<int:service_id>', methods=['GET'])
@admin_required()
def get_service_by_id(service_id):
    service = Service.query.get(service_id)
    if not service:
        return jsonify({'message': 'Không tìm thấy dịch vụ'}), 404
    return jsonify(service.to_dict()), 200

# Tạo dịch vụ mới (Admin)
@service_bp.route('/services', methods=['POST'])
@admin_required()
def create_service():
    try:
        data = request.get_json()
    except Exception:
        return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

    name = data.get('name')
    unit = data.get('unit')

    if not name or not name.strip():
        return jsonify({'message': 'Tên dịch vụ không được để trống'}), 400
    if not unit or not unit.strip():
        return jsonify({'message': 'Đơn vị không được để trống'}), 400
    if len(name) > 100:
        return jsonify({'message': 'Tên dịch vụ không được vượt quá 100 ký tự'}), 400
    if len(unit) > 10:
        return jsonify({'message': 'Đơn vị không được vượt quá 10 ký tự'}), 400

    if Service.query.filter_by(name=name).first():
        return jsonify({'message': 'Tên dịch vụ đã tồn tại'}), 400

    try:
        service = Service(
            name=name,
            unit=unit
        )
        db.session.add(service)
        db.session.commit()
        return jsonify(service.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Lỗi khi tạo dịch vụ', 'error': str(e)}), 500

# Cập nhật dịch vụ (Admin)
@service_bp.route('/services/<int:service_id>', methods=['PUT'])
@admin_required()
def update_service(service_id):
    service = Service.query.get(service_id)
    if not service:
        return jsonify({'message': 'Không tìm thấy dịch vụ'}), 404

    try:
        data = request.get_json()
    except Exception:
        return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

    new_name = data.get('name', service.name)
    new_unit = data.get('unit', service.unit)

    if new_name and not new_name.strip():
        return jsonify({'message': 'Tên dịch vụ không được để trống'}), 400
    if new_unit and not new_unit.strip():
        return jsonify({'message': 'Đơn vị không được để trống'}), 400
    if len(new_name) > 100:
        return jsonify({'message': 'Tên dịch vụ không được vượt quá 100 ký tự'}), 400
    if len(new_unit) > 10:
        return jsonify({'message': 'Đơn vị không được vượt quá 10 ký tự'}), 400

    if new_name != service.name:
        existing_service = Service.query.filter_by(name=new_name).first()
        if existing_service and existing_service.service_id != service_id:
            return jsonify({'message': 'Tên dịch vụ đã tồn tại'}), 400

    try:
        service.name = new_name
        service.unit = new_unit
        db.session.commit()
        return jsonify(service.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Lỗi khi cập nhật dịch vụ', 'error': str(e)}), 500

# Xóa dịch vụ (Admin)
@service_bp.route('/services/<int:service_id>', methods=['DELETE'])
@admin_required()
def delete_service(service_id):
    service = Service.query.get(service_id)
    if not service:
        return jsonify({'message': 'Không tìm thấy dịch vụ'}), 404

    related_rates = ServiceRate.query.filter_by(service_id=service_id).first()
    if related_rates:
        return jsonify({'message': 'Không thể xóa dịch vụ vì có mức giá liên quan. Vui lòng xóa các mức giá trước.'}), 400

    try:
        db.session.delete(service)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Lỗi khi xóa dịch vụ', 'error': str(e)}), 500