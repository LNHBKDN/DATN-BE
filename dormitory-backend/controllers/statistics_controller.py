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
from models.report import Report
from models.report_type import ReportType
from controllers.auth_controller import admin_required

statistics_bp = Blueprint('statistics', __name__)

@statistics_bp.route('/api/statistics/consumption', methods=['GET'])
@admin_required()
def get_monthly_consumption():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản khi có area_id
        if area_id is not None:
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
                .select_from(Area)  # Bắt đầu từ Area
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

            # Lọc theo khu vực
            query = query.filter(Area.area_id == area_id)

            # Thêm điều kiện lọc thời gian nếu có
            if year:
                query = query.filter(extract('year', BillDetail.bill_month) == year)
            if month:
                query = query.filter(extract('month', BillDetail.bill_month) == month)

            # Nhóm kết quả
            query = query.group_by(
                Area.area_id,
                Area.name,
                Service.service_id,
                Service.name,
                Service.unit,
                extract('month', BillDetail.bill_month)
            )
        else:
            # Khi area_id là null, tổng hợp từ tất cả khu vực, không cần Area trong query
            query = (
                db.session.query(
                    Service.service_id,
                    Service.name.label('service_name'),
                    Service.unit.label('service_unit'),
                    func.sum(BillDetail.current_reading - BillDetail.previous_reading).label('total_consumption'),
                    extract('month', BillDetail.bill_month).label('month')
                )
                .select_from(BillDetail)  # Bắt đầu từ BillDetail
                .join(Room, Room.room_id == BillDetail.room_id)
                .join(Contract, Contract.room_id == Room.room_id)
                .join(User, User.user_id == Contract.user_id)
                .join(ServiceRate, ServiceRate.rate_id == BillDetail.rate_id)
                .join(Service, Service.service_id == ServiceRate.service_id)
                .filter(
                    Room.is_deleted == False,
                    Contract.is_deleted == False,
                    User.is_deleted == False
                )
            )

            # Thêm điều kiện lọc thời gian nếu có
            if year:
                query = query.filter(extract('year', BillDetail.bill_month) == year)
            if month:
                query = query.filter(extract('month', BillDetail.bill_month) == month)

            # Nhóm kết quả
            query = query.group_by(
                Service.service_id,
                Service.name,
                Service.unit,
                extract('month', BillDetail.bill_month)
            )

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        if area_id is not None:
            # Xử lý khi có area_id (giữ logic cũ)
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
        else:
            # Xử lý khi area_id là null (tổng hợp tất cả khu vực)
            total_area_id = 0
            response[total_area_id] = {
                'area_id': total_area_id,
                'area_name': 'Toàn khu kí túc xá',
                'service_units': {},
                'months': {}
            }
            for row in results:
                service_name = row.service_name
                service_unit = row.service_unit
                month = int(row.month)
                total_consumption = float(row.total_consumption)

                response[total_area_id]['service_units'][service_name] = service_unit

                if month not in response[total_area_id]['months']:
                    response[total_area_id]['months'][month] = {}

                response[total_area_id]['months'][month][service_name] = total_consumption

        # Chuyển đổi response thành list
        formatted_response = list(response.values())

        return jsonify({
            'status': 'success',
            'data': formatted_response
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Lỗi xử lý dữ liệu: {str(e)}'
        }), 500

@statistics_bp.route('/api/statistics/rooms/status', methods=['GET'])
@admin_required()
def get_room_status_stats():
    try:
        # Lấy tham số từ query string
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        quarter = request.args.get('quarter', type=int)
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.status,
                func.count(Room.room_id).label('room_count')
            )
            .join(Area, Area.area_id == Room.area_id)
            .filter(Room.is_deleted == False)
        )

        # Lọc theo khu vực nếu có
        if area_id:
            query = query.filter(Area.area_id == area_id)

        # Nhóm kết quả
        query = query.group_by(Area.area_id, Area.name, Room.status)

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            status = row.status
            room_count = row.room_count

            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'status_counts': {}
                }

            response[area_id]['status_counts'][status] = room_count

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

@statistics_bp.route('/api/statistics/rooms/capacity', methods=['GET'])
@admin_required()
def get_room_capacity_stats():
    try:
        # Lấy tham số từ query string
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        quarter = request.args.get('quarter', type=int)
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                Room.capacity,
                func.count(Room.room_id).label('room_count')
            )
            .join(Area, Area.area_id == Room.area_id)
            .join(Contract, Contract.room_id == Room.room_id, isouter=True)
            .filter(
                Room.is_deleted == False,
                Room.status == 'OCCUPIED',
                Contract.is_deleted == False,
                Contract.status == 'ACTIVE'
            )
        )

        # Lọc theo khu vực nếu có
        if area_id:
            query = query.filter(Area.area_id == area_id)

        # Lọc theo thời gian nếu có
        if year:
            query = query.filter(extract('year', Contract.start_date) <= year, extract('year', Contract.end_date) >= year)
        if month:
            query = query.filter(extract('month', Contract.start_date) <= month, extract('month', Contract.end_date) >= month)
        if quarter:
            query = query.filter(
                (extract('month', Contract.start_date) <= (quarter * 3), extract('month', Contract.end_date) >= ((quarter - 1) * 3 + 1))
            )

        # Nhóm kết quả
        query = query.group_by(Area.area_id, Area.name, Room.capacity)

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            capacity = row.capacity
            room_count = row.room_count

            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'capacity_counts': {}
                }

            response[area_id]['capacity_counts'][str(capacity)] = room_count

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

@statistics_bp.route('/api/statistics/contracts', methods=['GET'])
@admin_required()
def get_contract_stats():
    try:
        # Lấy tham số từ query string
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        quarter = request.args.get('quarter', type=int)
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(Contract.contract_id).label('contract_count'),
                extract('month', Contract.start_date).label('month')
            )
            .join(Room, Room.room_id == Contract.room_id)
            .join(Area, Area.area_id == Room.area_id)
            .filter(
                Contract.is_deleted == False,
                Contract.status == 'ACTIVE',
                Room.is_deleted == False
            )
        )

        # Lọc theo khu vực nếu có
        if area_id:
            query = query.filter(Area.area_id == area_id)

        # Lọc theo thời gian nếu có
        if year:
            query = query.filter(extract('year', Contract.start_date) <= year, extract('year', Contract.end_date) >= year)
        if month:
            query = query.filter(extract('month', Contract.start_date) <= month, extract('month', Contract.end_date) >= month)
        if quarter:
            query = query.filter(
                (extract('month', Contract.start_date) <= (quarter * 3), extract('month', Contract.end_date) >= ((quarter - 1) * 3 + 1))
            )

        # Nhóm kết quả
        query = query.group_by(Area.area_id, Area.name, extract('month', Contract.start_date))

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            month = int(row.month) if row.month else None
            contract_count = row.contract_count

            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'months': {}
                }

            if month:
                response[area_id]['months'][month] = contract_count

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

@statistics_bp.route('/api/statistics/users', methods=['GET'])
@admin_required()
def get_user_stats():
    try:
        area_id = request.args.get('area_id', type=int)
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(User.user_id).label('user_count')
            )
            .outerjoin(Contract, Contract.user_id == User.user_id)
            .outerjoin(Room, Room.room_id == Contract.room_id)
            .outerjoin(Area, Area.area_id == Room.area_id)
            .filter(User.is_deleted == False)
        )
        if area_id:
            query = query.filter(Area.area_id == area_id)
        query = query.group_by(Area.area_id, Area.name)
        results = query.all()
        response = [
            {
                'area_id': row.area_id,
                'area_name': row.area_name,
                'user_count': row.user_count
            } for row in results
        ]
        return jsonify({'status': 'success', 'data': response}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@statistics_bp.route('/api/statistics/users/monthly', methods=['GET'])
@admin_required()
def get_user_monthly_stats():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        quarter = request.args.get('quarter', type=int)
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(User.user_id).label('user_count'),
                extract('month', User.created_at).label('month')
            )
            .outerjoin(Contract, Contract.user_id == User.user_id)
            .outerjoin(Room, Room.room_id == Contract.room_id)
            .outerjoin(Area, Area.area_id == Room.area_id)
            .filter(User.is_deleted == False, User.created_at.isnot(None))
        )

        # Lọc theo khu vực nếu có
        if area_id is not None:  # area_id được cung cấp
            query = query.filter(Area.area_id == area_id)
        # Lọc theo thời gian nếu có
        if year:
            query = query.filter(extract('year', User.created_at) == year)
        if month:
            query = query.filter(extract('month', User.created_at) == month)
        if quarter:
            query = query.filter(
                extract('month', User.created_at).in_([(quarter - 1) * 3 + 1, (quarter - 1) * 3 + 2, (quarter - 1) * 3 + 3])
            )

        # Nhóm kết quả
        if area_id is not None:
            # Nếu có area_id, nhóm theo khu vực cụ thể
            query = query.group_by(Area.area_id, Area.name, extract('month', User.created_at))
        else:
            # Nếu area_id là null, nhóm chỉ theo tháng (tổng hợp tất cả khu vực)
            query = (
                db.session.query(
                    func.count(User.user_id).label('user_count'),
                    extract('month', User.created_at).label('month')
                )
                .outerjoin(Contract, Contract.user_id == User.user_id)
                .outerjoin(Room, Room.room_id == Contract.room_id)
                .outerjoin(Area, Area.area_id == Room.area_id)
                .filter(User.is_deleted == False, User.created_at.isnot(None))
            )
            if year:
                query = query.filter(extract('year', User.created_at) == year)
            if month:
                query = query.filter(extract('month', User.created_at) == month)
            if quarter:
                query = query.filter(
                    extract('month', User.created_at).in_([(quarter - 1) * 3 + 1, (quarter - 1) * 3 + 2, (quarter - 1) * 3 + 3])
                )
            query = query.group_by(extract('month', User.created_at))

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        if area_id is not None:
            # Xử lý khi có area_id (giữ logic cũ)
            for row in results:
                area_id = row.area_id
                area_name = row.area_name
                month = int(row.month) if row.month else None
                user_count = row.user_count
                if area_id not in response:
                    response[area_id] = {
                        'area_id': area_id,
                        'area_name': area_name,
                        'months': {}
                    }
                if month:
                    response[area_id]['months'][month] = user_count
        else:
            # Xử lý khi area_id là null (tổng hợp tất cả khu vực)
            total_area_id = 0  # ID đặc biệt cho "Toàn khu kí túc xá"
            response[total_area_id] = {
                'area_id': total_area_id,
                'area_name': 'Toàn khu kí túc xá',
                'months': {}
            }
            for row in results:
                month = int(row.month) if row.month else None
                user_count = row.user_count
                if month:
                    response[total_area_id]['months'][month] = user_count

        # Chuyển đổi response thành list
        formatted_response = list(response.values())
        return jsonify({'status': 'success', 'data': formatted_response}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Lỗi xử lý dữ liệu: {str(e)}'}), 500

@statistics_bp.route('/api/statistics/rooms/occupancy-rate', methods=['GET'])
@admin_required()
def get_occupancy_rate_stats():
    try:
        # Lấy tham số từ query string
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                func.count(Room.room_id).label('total_rooms'),
                func.sum(db.case((Room.status == 'OCCUPIED', 1), else_=0)).label('occupied_rooms')
            )
            .join(Area, Area.area_id == Room.area_id)
            .filter(Room.is_deleted == False)
        )

        # Lọc theo khu vực nếu có
        if area_id:
            query = query.filter(Area.area_id == area_id)

        # Nhóm kết quả
        query = query.group_by(Area.area_id, Area.name)

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = []
        for row in results:
            total_rooms = row.total_rooms
            occupied_rooms = row.occupied_rooms
            occupancy_rate = (occupied_rooms / total_rooms * 100) if total_rooms > 0 else 0
            response.append({
                'area_id': row.area_id,
                'area_name': row.area_name,
                'total_rooms': total_rooms,
                'occupied_rooms': occupied_rooms,
                'occupancy_rate': round(occupancy_rate, 2)
            })

        return jsonify({
            'status': 'success',
            'data': response
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@statistics_bp.route('/api/statistics/reports', methods=['GET'])
@admin_required()
def get_report_stats():
    try:
        # Lấy tham số từ query string
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        area_id = request.args.get('area_id', type=int)

        # Khởi tạo query cơ bản
        query = (
            db.session.query(
                Area.area_id,
                Area.name.label('area_name'),
                ReportType.report_type_id,
                ReportType.name.label('report_type_name'),
                func.count(Report.report_id).label('report_count'),
                extract('month', Report.created_at).label('month'),
                extract('year', Report.created_at).label('year')
            )
            .join(Room, Room.room_id == Report.room_id)
            .join(Area, Area.area_id == Room.area_id)
            .join(ReportType, ReportType.report_type_id == Report.report_type_id)
            .filter(
                Room.is_deleted == False,
                Report.created_at.isnot(None)
            )
        )

        # Lọc theo khu vực nếu có
        if area_id:
            query = query.filter(Area.area_id == area_id)

        # Lọc theo thời gian nếu có
        if year:
            query = query.filter(extract('year', Report.created_at) == year)
        if month:
            query = query.filter(extract('month', Report.created_at) == month)

        # Nhóm kết quả
        query = query.group_by(
            Area.area_id,
            Area.name,
            ReportType.report_type_id,
            ReportType.name,
            extract('month', Report.created_at),
            extract('year', Report.created_at)
        )

        # Thực thi query
        results = query.all()

        # Định dạng kết quả
        response = {}
        for row in results:
            area_id = row.area_id
            area_name = row.area_name
            report_type_id = row.report_type_id
            report_type_name = row.report_type_name
            report_count = row.report_count
            month = int(row.month) if row.month else None
            year = int(row.year) if row.year else None

            if area_id not in response:
                response[area_id] = {
                    'area_id': area_id,
                    'area_name': area_name,
                    'years': {},
                    'report_types': {}
                }

            # Lưu thông tin report type
            response[area_id]['report_types'][str(report_type_id)] = report_type_name

            # Lưu thống kê theo năm
            if year not in response[area_id]['years']:
                response[area_id]['years'][year] = {'total': 0, 'months': {}, 'types': {}}

            response[area_id]['years'][year]['total'] += report_count

            # Lưu thống kê theo tháng trong năm
            if month:
                if month not in response[area_id]['years'][year]['months']:
                    response[area_id]['years'][year]['months'][month] = {}
                response[area_id]['years'][year]['months'][month][report_type_name] = report_count

            # Lưu thống kê theo loại báo cáo
            if report_type_name not in response[area_id]['years'][year]['types']:
                response[area_id]['years'][year]['types'][report_type_name] = 0
            response[area_id]['years'][year]['types'][report_type_name] += report_count

        # Chuyển đổi response thành list
        formatted_response = list(response.values())

        # Thêm thống kê xu hướng (so sánh với hợp đồng)
        trend_stats = []
        for area_data in formatted_response:
            area_id = area_data['area_id']
            area_name = area_data['area_name']
            for year, year_data in area_data['years'].items():
                # Lấy số lượng hợp đồng trong năm
                contract_query = (
                    db.session.query(
                        func.count(Contract.contract_id).label('contract_count')
                    )
                    .join(Room, Room.room_id == Contract.room_id)
                    .join(Area, Area.area_id == Room.area_id)
                    .filter(
                        Area.area_id == area_id,
                        Contract.is_deleted == False,
                        Contract.status == 'ACTIVE',
                        extract('year', Contract.start_date) <= year,
                        extract('year', Contract.end_date) >= year
                    )
                )
                contract_result = contract_query.one()
                contract_count = contract_result.contract_count

                # Tính tỷ lệ báo cáo trên hợp đồng
                report_per_contract = (year_data['total'] / contract_count) if contract_count > 0 else 0

                trend_stats.append({
                    'area_id': area_id,
                    'area_name': area_name,
                    'year': year,
                    'total_reports': year_data['total'],
                    'total_contracts': contract_count,
                    'report_per_contract': round(report_per_contract, 2)
                })

        return jsonify({
            'status': 'success',
            'data': formatted_response,
            'trends': trend_stats
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500