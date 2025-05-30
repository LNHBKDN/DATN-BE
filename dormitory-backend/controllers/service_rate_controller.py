from flask import Blueprint, request, jsonify
from extensions import db
from models.service import Service
from models.service_rate import ServiceRate
from controllers.auth_controller import admin_required
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import logging

logging.basicConfig(level=logging.INFO)

service_rate_bp = Blueprint('service_rate', __name__)

# Lấy danh sách tất cả mức giá (Admin)
@service_rate_bp.route('/service-rates', methods=['GET'])
@admin_required()
def get_all_service_rates():
    logging.info(f"GET /api/service-rates with params: {request.args}")
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        service_id = request.args.get('service_id', type=int)

        query = ServiceRate.query
        if service_id:
            if not Service.query.get(service_id):
                return jsonify({'message': f'Không tìm thấy dịch vụ với ID {service_id}'}), 404
            query = query.filter_by(service_id=service_id)

        rates = query.paginate(page=page, per_page=limit)
        return jsonify({
            'service_rates': [rate.to_dict() for rate in rates.items],
            'total': rates.total,
            'pages': rates.pages,
            'current_page': rates.page
        }), 200
    except Exception as e:
        logging.error(f"Error in get_all_service_rates: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy danh sách mức giá', 'error': str(e)}), 500

# Lấy mức giá hiện tại cho một dịch vụ (Admin)
@service_rate_bp.route('/service-rates/current/<int:service_id>', methods=['GET'])
@admin_required()
def get_current_service_rate(service_id):
    logging.info(f"GET /api/service-rates/current/{service_id}")
    try:
        if not Service.query.get(service_id):
            return jsonify({'message': f'Không tìm thấy dịch vụ với ID {service_id}'}), 404

        today = datetime.today().date()
        rate = ServiceRate.query.filter(
            ServiceRate.service_id == service_id,
            ServiceRate.effective_date <= today
        ).order_by(ServiceRate.effective_date.desc()).first()

        if not rate:
            return jsonify({'message': 'Không tìm thấy mức giá hiện tại cho dịch vụ này'}), 404
        return jsonify(rate.to_dict()), 200
    except Exception as e:
        logging.error(f"Error in get_current_service_rate: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy mức giá hiện tại', 'error': str(e)}), 500

# Lấy chi tiết mức giá theo ID (Admin)
@service_rate_bp.route('/service-rates/<int:rate_id>', methods=['GET'])
@admin_required()
def get_service_rate_by_id(rate_id):
    logging.info(f"GET /api/service-rates/{rate_id}")
    try:
        rate = ServiceRate.query.get(rate_id)
        if not rate:
            return jsonify({'message': f'Không tìm thấy mức giá với ID {rate_id}'}), 404
        return jsonify(rate.to_dict()), 200
    except Exception as e:
        logging.error(f"Error in get_service_rate_by_id: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy mức giá', 'error': str(e)}), 500

# Tạo mức giá mới (Admin)
@service_rate_bp.route('/service-rates', methods=['POST'])
@admin_required()
def create_service_rate():
    logging.info(f"POST /api/service-rates with data: {request.get_json()}")
    try:
        # Phân tích JSON đầu vào
        try:
            data = request.get_json()
        except Exception:
            logging.error("Invalid JSON data")
            return jsonify({'message': 'Dữ liệu JSON không hợp lệ'}), 400

        # Lấy và kiểm tra các trường bắt buộc
        service_id = data.get('service_id')
        unit_price = data.get('unit_price')
        effective_date = data.get('effective_date')

        if not all([service_id, unit_price is not None, effective_date]):
            return jsonify({'message': 'Yêu cầu service_id, unit_price và effective_date'}), 400

        # Kiểm tra service_id
        if not isinstance(service_id, int):
            return jsonify({'message': 'service_id phải là số nguyên'}), 400
        if not Service.query.get(service_id):
            return jsonify({'message': f'Không tìm thấy dịch vụ với ID {service_id}'}), 404

        # Kiểm tra unit_price
        try:
            unit_price = float(unit_price)
            if unit_price < 0 or unit_price > 99999999.99:
                return jsonify({'message': 'unit_price phải là số không âm và không vượt quá 99999999.99'}), 400
        except (TypeError, ValueError):
            return jsonify({'message': 'unit_price phải là số hợp lệ'}), 400

        # Kiểm tra effective_date
        try:
            effective_date = datetime.strptime(effective_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'message': 'Định dạng effective_date không hợp lệ (YYYY-MM-DD)'}), 400

        # Ràng buộc kinh doanh: Không cho phép ngày quá xa trong quá khứ
        min_date = date(2020, 1, 1)  # Có thể điều chỉnh theo yêu cầu
        if effective_date < min_date:
            return jsonify({'message': f'effective_date không được trước {min_date}'}), 400

        # Kiểm tra: effective_date phải là ngày 1 của tháng
        if effective_date.day != 1:
            return jsonify({'message': 'Ngày áp dụng phải là ngày 1 của tháng'}), 400

        # Kiểm tra: effective_date không được nằm trong tháng hiện tại
        today = datetime.today().date()
        first_day_of_next_month = (today.replace(day=1) + relativedelta(months=1)).replace(day=1)
        if effective_date < first_day_of_next_month:
            return jsonify({'message': f'Ngày áp dụng phải từ {first_day_of_next_month.strftime("%Y-%m-%d")} trở đi (không được nằm trong tháng hiện tại)'}), 400

        # Kiểm tra xung đột giá
        existing_rate = ServiceRate.query.filter_by(
            service_id=service_id,
            effective_date=effective_date
        ).first()
        if existing_rate:
            return jsonify({'message': f'Đã tồn tại mức giá cho dịch vụ {service_id} vào ngày {effective_date}'}), 409

        # Tạo bản ghi mới
        try:
            rate = ServiceRate(
                service_id=service_id,
                unit_price=unit_price,
                effective_date=effective_date
            )
            db.session.add(rate)
            db.session.commit()
            return jsonify(rate.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in create_service_rate: {str(e)}")
            return jsonify({'message': 'Lỗi khi tạo mức giá', 'error': str(e)}), 500

    except Exception as e:
        logging.error(f"Error in create_service_rate: {str(e)}")
        return jsonify({'message': 'Lỗi khi tạo mức giá', 'error': str(e)}), 500

# Xóa mức giá (Admin)
@service_rate_bp.route('/service-rates/<int:rate_id>', methods=['DELETE'])
@admin_required()
def delete_service_rate(rate_id):
    logging.info(f"DELETE /api/service-rates/{rate_id}")
    try:
        rate = ServiceRate.query.get(rate_id)
        if not rate:
            return jsonify({'message': f'Không tìm thấy mức giá với ID {rate_id}'}), 404

        try:
            db.session.delete(rate)
            db.session.commit()
            return '', 204
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in delete_service_rate: {str(e)}")
            return jsonify({'message': 'Lỗi khi xóa mức giá', 'error': str(e)}), 500
    except Exception as e:
        logging.error(f"Error in delete_service_rate: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa mức giá', 'error': str(e)}), 500