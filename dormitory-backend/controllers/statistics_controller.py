# backend/controllers/statistics_controller.py
from flask import Blueprint, jsonify, request
from extensions import db
from sqlalchemy import func, extract
from datetime import datetime
from models.service import Service
from models.service_rate import ServiceRate
from models.bill_detail import BillDetail
from models.contract import Contract
from models.room import Room
from models.area import Area
from models.user import User
from controllers.auth_controller import admin_required

statistics_bp = Blueprint('statistics', __name__)

@statistics_bp.route('/api/statistics/consumption', methods=['GET'])
@admin_required()
def get_monthly_consumption():
    try:
        # Lấy tham số từ query string
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)  # Thêm area_id

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Service.service_id,
                Service.name.label('service_name'),
                Service.unit.label('service_unit'),
                func.sum(BillDetail.current_reading - BillDetail.previous_reading).label('total_consumption'),
                extract('month', BillDetail.bill_month).label('month')
            )
            .join(Room, Room.area_id == Area.area_id)
            .join(Contract, Contract.room_id == Room.room_id)
            .join(User, User.user_id == Contract.user_id)
            .join(BillDetail, BillDetail.room_id == Room.room_id)
            .join(ServiceRate, ServiceRate.rate_id == BillDetail.rate_id)
            .join(Service, Service.service_id == ServiceRate.service_id)
            .filter(
                Room.is_deleted == False,
                Contract.is_deleted == False,
                User.is_deleted == False
            )
        )

        # Thêm điều kiện lọc nếu có
        if year:
            query = query.filter(extract('year', BillDetail.bill_month) == year)
        if month:
            query = query.filter(extract('month', BillDetail.bill_month) == month)
        if area_id:
            query = query.filter(Area.area_id == area_id)  # Lọc theo area_id

        # Nhóm kết quả theo khu vực, dịch vụ, đơn vị và tháng
        query = query.group_by(
            Area.area_id,
            Area.name,
            Service.service_id,
            Service.name,
            Service.unit,
            extract('month', BillDetail.bill_month)
        )

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            service_name = row.service_name
            service_unit = row.service_unit
            month = int(row.month)
            total_consumption = float(row.total_consumption)

            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'service_units': {},
                    'months': {}
                }

            response[area_id]['service_units'][service_name] = service_unit

            if month not in response[area_id]['months']:
                response[area_id]['months'][month] = {}

            response[area_id]['months'][month][service_name] = total_consumption

        # Chuyển đổi response thành list
        formatted_response = list(response.values())

        return jsonify({
            'status': 'success',
            'data': formatted_response
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500