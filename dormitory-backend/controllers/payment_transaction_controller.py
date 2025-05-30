from flask import Blueprint, request, jsonify, current_app, redirect
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models.payment_transaction import PaymentTransaction
from models.monthly_bill import MonthlyBill
from models.user import User
from models.contract import Contract
from models.notification import Notification
from models.notification_recipient import NotificationRecipient
from controllers.auth_controller import admin_required, user_required
import hashlib
import hmac
import urllib.parse
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import logging
from utils.fcm import send_fcm_notification

payment_transaction_bp = Blueprint('payment_transaction', __name__)

# Hàm tiện ích để mã hóa giá trị URL
def encode_url_value(value):
    return urllib.parse.quote_plus(str(value))

# Hàm tiện ích để tạo chữ ký bảo mật
def generate_secure_hash(data, secret_key):
    if not secret_key:
        raise ValueError("Secret key không được để trống")
    data_string = '&'.join([f"{k}={encode_url_value(v)}" for k, v in sorted(data.items())])
    logging.debug(f"Data string for hash: {data_string}")
    return hmac.new(secret_key.encode('utf-8'), data_string.encode('utf-8'), hashlib.sha512).hexdigest()

# Hàm tiện ích để lấy thông tin người dùng từ JWT
def get_user_info(identity):
    try:
        if isinstance(identity, dict):
            return identity['id'], identity.get('type', 'USER')
        return int(identity), 'USER'
    except (TypeError, ValueError) as e:
        raise ValueError(f"Token không hợp lệ: {str(e)}")

# Utility function to get active room_id from user_id via Contract
def get_active_room_id(user_id):
    contract = Contract.query.filter_by(user_id=user_id, status='ACTIVE').first()
    if not contract:
        return None
    return contract.room_id

def create_vnpay_url(transaction, bill_id, payment_method, return_url, request_ip):
    print(f"payment_method received: '{payment_method}' (length: {len(payment_method)})")
    print(f"payment_method chars: {[ord(c) for c in payment_method]}")
    payment_method = payment_method.strip()
    print(f"payment_method after strip: '{payment_method}' (length: {len(payment_method)})")
    if payment_method != 'VNPAY':
        raise ValueError(f"Phương thức thanh toán không hợp lệ: {payment_method}")
    VNPAY_TMN_CODE = current_app.config.get("VNPAY_TMN_CODE")
    VNPAY_HASH_SECRET = current_app.config.get("VNPAY_HASH_SECRET")
    VNPAY_URL = current_app.config.get("VNPAY_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html")

    if not all([VNPAY_TMN_CODE, VNPAY_HASH_SECRET, VNPAY_URL]):
        logging.error("Missing VNPay configuration")
        raise ValueError("Cấu hình VNPay không đầy đủ")

    if payment_method != 'VNPAY':
        logging.error(f"Invalid payment method: {payment_method}")
        raise ValueError(f"Phương thức thanh toán không hợp lệ: {payment_method}")

    create_date = datetime.now()
    expire_date = create_date + timedelta(minutes=15)

    vnp_params = {
        'vnp_Version': '2.1.0',
        'vnp_Command': 'pay',
        'vnp_TmnCode': VNPAY_TMN_CODE,
        'vnp_Amount': int(float(transaction.amount) * 100),
        'vnp_CurrCode': 'VND',
        'vnp_TxnRef': str(transaction.transaction_id),
        'vnp_OrderInfo': f'Payment for bill {bill_id}',
        'vnp_OrderType': 'billpayment',
        'vnp_Locale': 'vn',
        'vnp_ReturnUrl': return_url,
        'vnp_IpAddr': request_ip,
        'vnp_CreateDate': create_date.strftime('%Y%m%d%H%M%S'),
        'vnp_ExpireDate': expire_date.strftime('%Y%m%d%H%M%S'),
    }

    logging.debug(f"VNPay params before hash: {vnp_params}")
    vnp_params['vnp_SecureHash'] = generate_secure_hash(vnp_params, VNPAY_HASH_SECRET)
    logging.debug(f"VNPay SecureHash: {vnp_params['vnp_SecureHash']}")
    vnpay_url = f"{VNPAY_URL}?{urllib.parse.urlencode(vnp_params)}"
    logging.debug(f"Generated VNPay URL: {vnpay_url}")
    return vnpay_url

# Tạo giao dịch mới
@payment_transaction_bp.route('/payment-transactions', methods=['POST'])
@jwt_required()
def create_payment_transaction():
    logging.info(f"POST /payment-transactions - Request body: {request.get_json()}")
    try:
        user_id, user_type = get_user_info(get_jwt_identity())

        data = request.get_json()
        bill_id = data.get('bill_id')
        payment_method = data.get('payment_method')
        return_url = data.get('return_url')

        if not all([bill_id, payment_method]):
            logging.error("Missing bill_id or payment_method in request")
            return jsonify({'message': 'Yêu cầu bill_id và payment_method'}), 400

        if not return_url:
            return_url = 'http://localhost:5000/api/payment-transactions/callback'

        bill = MonthlyBill.query.get(bill_id)
        if not bill:
            logging.error(f"Bill not found for bill_id: {bill_id}")
            return jsonify({'message': 'Không tìm thấy hóa đơn'}), 404

        if user_type == 'USER':
            user = User.query.filter_by(user_id=user_id, is_deleted=False).first()
            if not user:
                logging.error(f"User not found for user_id: {user_id}")
                return jsonify({'message': 'Không tìm thấy người dùng'}), 404

            room_id = get_active_room_id(user_id)
            if not room_id or bill.room_id != room_id or bill.user_id != user_id:
                logging.error(f"User {user_id} does not have permission to pay bill {bill_id}")
                return jsonify({'message': 'Bạn không có quyền thanh toán hóa đơn này'}), 403

        if bill.payment_status == 'PAID':
            logging.info(f"Bill {bill_id} already paid")
            return jsonify({'message': 'Hóa đơn đã được thanh toán'}), 409

        amount = float(bill.total_amount)
        if amount <= 0:
            logging.error(f"Invalid bill amount for bill_id {bill_id}: {amount}")
            return jsonify({'message': 'Số tiền hóa đơn không hợp lệ'}), 400
        if amount > 50000000:
            logging.error(f"Bill amount exceeds VNPay sandbox limit for bill_id {bill_id}: {amount}")
            return jsonify({'message': 'Số tiền vượt quá giới hạn sandbox VNPay (50 triệu VND)'}), 400

        allowed_methods = bill.payment_method_allowed.split(',') if bill.payment_method_allowed else []
        logging.info(f"Allowed payment methods for bill_id {bill_id}: {allowed_methods}")
        if payment_method not in allowed_methods:
            logging.error(f"Payment method {payment_method} not allowed for bill_id {bill_id}")
            return jsonify({'message': f'Phương thức thanh toán {payment_method} không được phép'}), 400

        existing_transaction = PaymentTransaction.query.filter_by(
            bill_id=bill_id, status='PENDING'
        ).first()

        if existing_transaction:
            if bill.payment_status != 'PENDING':
                logging.info(f"Bill {bill_id} no longer in PENDING status")
                return jsonify({'message': 'Hóa đơn không còn ở trạng thái PENDING'}), 409
            if existing_transaction.created_at < datetime.utcnow() - timedelta(minutes=15):
                existing_transaction.status = 'CANCELLED'
                db.session.commit()
                logging.info(f"Cancelled expired PaymentTransaction {existing_transaction.transaction_id} for bill {bill_id}")
            else:
                existing_transaction.status = 'CANCELLED'
                db.session.commit()
                logging.info(f"Cancelled PaymentTransaction {existing_transaction.transaction_id} to create a new one for bill {bill_id}")

        transaction = PaymentTransaction(
            bill_id=bill_id,
            amount=amount,
            payment_method=payment_method.upper(),
            status='PENDING'
        )
        db.session.add(transaction)
        db.session.commit()

        vnpay_url = create_vnpay_url(transaction, bill_id, payment_method, return_url, request.remote_addr)
        logging.info(f"User {user_id} created PaymentTransaction {transaction.transaction_id} for bill {bill_id}")
        return jsonify({
            'payment_url': vnpay_url,
            'transaction_id': transaction.transaction_id,
            'bill_details': {'bill_id': bill.bill_id, 'total_amount': str(bill.total_amount)}
        }), 200

    except ValueError as e:
        logging.error(f"ValueError: {str(e)}")
        return jsonify({'message': str(e)}), 400
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError: {str(e)}")
        return jsonify({'message': 'Lỗi khi tạo giao dịch: Hóa đơn không hợp lệ'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error: {str(e)}")
        return jsonify({'message': 'Lỗi khi tạo giao dịch thanh toán', 'error': str(e)}), 500

# Xử lý callback từ VNPay
@payment_transaction_bp.route('/payment-transactions/callback', methods=['GET'])
def vnpay_callback():
    logging.info("GET /payment-transactions/callback")
    try:
        vnp_params = request.args.to_dict()
        secure_hash = vnp_params.pop('vnp_SecureHash', None)
        if not secure_hash:
            return jsonify({'message': 'Invalid signature'}), 400

        VNPAY_HASH_SECRET = current_app.config.get("VNPAY_HASH_SECRET")
        calculated_hash = generate_secure_hash(vnp_params, VNPAY_HASH_SECRET)

        if secure_hash != calculated_hash:
            return jsonify({'message': 'Signature mismatch'}), 400

        transaction_id = vnp_params.get('vnp_TxnRef')
        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        logging.info(f"Before update - Transaction {transaction_id} status: {transaction.status}, Bill {bill.bill_id} payment_status: {bill.payment_status}")

        if vnp_params.get('vnp_ResponseCode') == '00':
            transaction.status = 'SUCCESS'
            transaction.processed_at = datetime.utcnow()
            transaction.gateway_reference = vnp_params.get('vnp_TransactionNo')
            bill.payment_status = 'PAID'
            bill.paid_at = datetime.utcnow()
            bill.transaction_reference = transaction.gateway_reference
            # Gọi payment_success để xử lý thông báo
            payment_success(transaction_id=transaction_id, status='SUCCESS', 
                            bank_code=vnp_params.get('vnp_BankCode', ''),
                            transaction_no=vnp_params.get('vnp_TransactionNo', ''),
                            pay_date=vnp_params.get('vnp_PayDate', ''),
                            amount=int(vnp_params.get('vnp_Amount', 0)) / 100)
        else:
            transaction.status = 'FAILED'
            transaction.error_message = vnp_params.get('vnp_Message', 'Payment failed')
            bill.payment_status = 'FAILED'
            # Gọi payment_failure để xử lý thông báo
            payment_failure(transaction_id=transaction_id, status='FAILED',
                            bank_code=vnp_params.get('vnp_BankCode', ''),
                            transaction_no=vnp_params.get('vnp_TransactionNo', ''),
                            pay_date=vnp_params.get('vnp_PayDate', ''),
                            amount=int(vnp_params.get('vnp_Amount', 0)) / 100)

        db.session.commit()

        logging.info(f"After update - Transaction {transaction_id} status: {transaction.status}, Bill {bill.bill_id} payment_status: {bill.payment_status}")

        # Redirect về file HTML tĩnh
        redirect_base = "/static/payment_success.html" if transaction.status == 'SUCCESS' else "/static/payment_failure.html"
        redirect_params = {
            'transaction_id': transaction_id,
            'status': transaction.status,
            'bank_code': vnp_params.get('vnp_BankCode', ''),
            'transaction_no': vnp_params.get('vnp_TransactionNo', ''),
            'pay_date': vnp_params.get('vnp_PayDate', ''),
            'amount': int(vnp_params.get('vnp_Amount', 0)) / 100
        }
        redirect_url = f"{redirect_base}?{urllib.parse.urlencode(redirect_params)}"
        logging.info(f"Redirecting to: {redirect_url}")
        return redirect(redirect_url)

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in vnpay_callback: {str(e)}")
        return jsonify({'message': 'Error processing callback', 'error': str(e)}), 500

# Xử lý trang thành công
@payment_transaction_bp.route('/payment/success', methods=['GET'])
def payment_success(transaction_id=None, status=None, bank_code=None, transaction_no=None, pay_date=None, amount=None):
    # Nếu được gọi từ callback, sử dụng tham số truyền vào
    if transaction_id is None:
        transaction_id = request.args.get('transaction_id')
        status = request.args.get('status')
        bank_code = request.args.get('bank_code')
        transaction_no = request.args.get('transaction_no')
        pay_date = request.args.get('pay_date')
        amount = float(request.args.get('amount', 0))

    try:
        if status != 'SUCCESS':
            logging.error(f"Invalid status for payment_success: {status}")
            return jsonify({'message': 'Invalid transaction status for success endpoint'}), 400

        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            logging.error(f"Transaction not found: {transaction_id}")
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            logging.error(f"Bill not found for transaction: {transaction_id}")
            return jsonify({'message': 'Bill not found'}), 404

        # Kiểm tra xem thông báo đã được gửi chưa
        existing_notification = Notification.query.filter_by(
            related_entity_type='PAYMENT_TRANSACTION',
            related_entity_id=transaction.transaction_id
        ).first()
        if existing_notification:
            logging.info(f"Notification already exists for transaction {transaction_id}")
        else:
            # Tạo thông báo cho phòng
            title = "Thanh toán hóa đơn thành công"
            message = f"Hóa đơn #{bill.bill_id} cho phòng đã được thanh toán thành công. Số tiền: {bill.total_amount} VND."
            notification = Notification(
                title=title,
                message=message,
                target_type='SYSTEM',
                target_id=bill.room_id,  # target_id is room_id
                related_entity_type='PAYMENT_TRANSACTION',
                related_entity_id=transaction.transaction_id,
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.flush()

            # Tìm tất cả người dùng trong phòng qua hợp đồng
            contracts = Contract.query.filter_by(
                room_id=bill.room_id,
                status='ACTIVE'
            ).all()
            for contract in contracts:
                recipient = NotificationRecipient(
                    notification_id=notification.id,
                    user_id=contract.user_id,
                    is_read=False
                )
                db.session.add(recipient)

                # Gửi thông báo qua FCM
                user = User.query.get(contract.user_id)
                if user and user.fcm_token:
                    send_fcm_notification(
                        user_id=contract.user_id,
                        title=title,
                        message=message,
                        data={
                            'notification_id': str(notification.id),
                            'related_entity_type': 'PAYMENT_TRANSACTION',
                            'related_entity_id': str(transaction.transaction_id)
                        }
                    )
                    logging.info(f"FCM notification sent to user {contract.user_id} for notification_id={notification.id}")

            db.session.commit()
            logging.info(f"Notification created for room {bill.room_id}, notification_id={notification.id}")

        response_data = {
            'message': 'Payment processed successfully',
            'transaction_id': transaction_id,
            'status': status,
            'bank_code': bank_code,
            'transaction_no': transaction_no,
            'pay_date': pay_date,
            'amount': amount
        }

        logging.info(f"Payment success response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in payment_success: {str(e)}")
        return jsonify({'message': 'Error processing payment success', 'error': str(e)}), 500

# Xử lý trang thất bại
@payment_transaction_bp.route('/payment/failure', methods=['GET'])
def payment_failure(transaction_id=None, status=None, bank_code=None, transaction_no=None, pay_date=None, amount=None):
    # Nếu được gọi từ callback, sử dụng tham số truyền vào
    if transaction_id is None:
        transaction_id = request.args.get('transaction_id')
        status = request.args.get('status')
        bank_code = request.args.get('bank_code')
        transaction_no = request.args.get('transaction_no')
        pay_date = request.args.get('pay_date')
        amount = float(request.args.get('amount', 0))

    try:
        if status != 'FAILED':
            logging.error(f"Invalid status for payment_failure: {status}")
            return jsonify({'message': 'Invalid transaction status for failure endpoint'}), 400

        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            logging.error(f"Transaction not found: {transaction_id}")
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            logging.error(f"Bill not found for transaction: {transaction_id}")
            return jsonify({'message': 'Bill not found'}), 404

        # Kiểm tra xem thông báo đã được gửi chưa
        existing_notification = Notification.query.filter_by(
            related_entity_type='PAYMENT_TRANSACTION',
            related_entity_id=transaction.transaction_id
        ).first()
        if existing_notification:
            logging.info(f"Notification already exists for transaction {transaction_id}")
        else:
            # Tạo thông báo cho phòng
            title = "Thanh toán hóa đơn thất bại"
            message = f"Thanh toán hóa đơn #{bill.bill_id} cho phòng thất bại. Lý do: {transaction.error_message or 'Lỗi không xác định'}."
            notification = Notification(
                title=title,
                message=message,
                target_type='SYSTEM',
                target_id=bill.room_id,  # target_id is room_id
                related_entity_type='PAYMENT_TRANSACTION',
                related_entity_id=transaction.transaction_id,
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.flush()

            # Tìm tất cả người dùng trong phòng qua hợp đồng
            contracts = Contract.query.filter_by(
                room_id=bill.room_id,
                status='ACTIVE'
            ).all()
            for contract in contracts:
                recipient = NotificationRecipient(
                    notification_id=notification.id,
                    user_id=contract.user_id,
                    is_read=False
                )
                db.session.add(recipient)

                # Gửi thông báo qua FCM
                user = User.query.get(contract.user_id)
                if user and user.fcm_token:
                    send_fcm_notification(
                        user_id=contract.user_id,
                        title=title,
                        message=message,
                        data={
                            'notification_id': str(notification.id),
                            'related_entity_type': 'PAYMENT_TRANSACTION',
                            'related_entity_id': str(transaction.transaction_id)
                        }
                    )
                    logging.info(f"FCM notification sent to user {contract.user_id} for notification_id={notification.id}")

            db.session.commit()
            logging.info(f"Notification created for room {bill.room_id}, notification_id={notification.id}")

        response_data = {
            'message': 'Payment processing failed',
            'transaction_id': transaction_id,
            'status': status,
            'bank_code': bank_code,
            'transaction_no': transaction_no,
            'pay_date': pay_date,
            'amount': amount
        }

        logging.info(f"Payment failure response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in payment_failure: {str(e)}")
        return jsonify({'message': 'Error processing payment failure', 'error': str(e)}), 500

# Lấy danh sách giao dịch (Admin)
@payment_transaction_bp.route('/payment-transactions', methods=['GET'])
@admin_required()
def get_all_payment_transactions():
    logging.info("GET /payment-transactions")
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        bill_id = request.args.get('bill_id', type=int)
        status = request.args.get('status', type=str)

        if page <= 0 or limit <= 0:
            return jsonify({'message': 'Page and limit must be greater than 0'}), 400

        if status and status.upper() not in ['PENDING', 'SUCCESS', 'FAILED', 'CANCELLED']:
            return jsonify({'message': 'Invalid status'}), 400

        query = PaymentTransaction.query
        if bill_id:
            query = query.filter_by(bill_id=bill_id)
        if status:
            query = query.filter_by(status=status.upper())

        transactions = query.paginate(page=page, per_page=limit, error_out=False)
        return jsonify({
            'payment_transactions': [transaction.to_dict() for transaction in transactions.items],
            'total': transactions.total,
            'pages': transactions.pages,
            'current_page': transactions.page
        }), 200

    except Exception as e:
        logging.error(f"Error in get_all_payment_transactions: {str(e)}")
        return jsonify({'message': 'Error retrieving transactions', 'error': str(e)}), 500

# Lấy chi tiết giao dịch
@payment_transaction_bp.route('/payment-transactions/<int:transaction_id>', methods=['GET'])
@jwt_required()
def get_payment_transaction_by_id(transaction_id):
    logging.info(f"GET /payment-transactions/{transaction_id}")
    try:
        user_id, user_type = get_user_info(get_jwt_identity())

        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        if user_type == 'USER':
            room_id = get_active_room_id(user_id)
            if not room_id or bill.room_id != room_id or bill.user_id != user_id:
                return jsonify({'message': 'Bạn không có quyền xem giao dịch này'}), 403

        return jsonify(transaction.to_dict()), 200

    except ValueError as e:
        return jsonify({'message': str(e)}), 401
    except Exception as e:
        logging.error(f"Error in get_payment_transaction_by_id: {str(e)}")
        return jsonify({'message': 'Lỗi khi lấy chi tiết giao dịch', 'error': str(e)}), 500

# Cập nhật giao dịch (Admin)
@payment_transaction_bp.route('/payment-transactions/<int:transaction_id>', methods=['PUT'])
@admin_required()
def update_payment_transaction(transaction_id):
    logging.info(f"PUT /payment-transactions/{transaction_id}")
    try:
        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        if transaction.status != 'PENDING':
            return jsonify({'message': 'Cannot update: Transaction is not in PENDING status'}), 409

        data = request.get_json()
        new_payment_method = data.get('payment_method', transaction.payment_method).upper()
        new_status = data.get('status', transaction.status).upper() if data.get('status') else transaction.status

        if new_payment_method not in ['VIETQR', 'CASH', 'BANK_TRANSFER']:
            return jsonify({'message': f'Invalid payment method: {new_payment_method}'}), 400

        if new_status not in ['PENDING', 'SUCCESS', 'FAILED', 'CANCELLED']:
            return jsonify({'message': 'Invalid status'}), 400

        transaction.payment_method = new_payment_method
        transaction.status = new_status

        if new_status == 'SUCCESS':
            bill.payment_status = 'PAID'
            bill.paid_at = datetime.utcnow()
            bill.transaction_reference = transaction.gateway_reference or f"TRANS-{transaction.transaction_id}"
        elif new_status == 'FAILED':
            bill.payment_status = 'FAILED'
            bill.transaction_reference = None

        db.session.commit()
        logging.info(f"Updated PaymentTransaction {transaction_id} to status {new_status}")
        return jsonify(transaction.to_dict()), 200

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in update_payment_transaction: {str(e)}")
        return jsonify({'message': 'Lỗi khi cập nhật: Có bản ghi liên quan không thể cập nhật do ràng buộc khóa ngoại'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in update_payment_transaction: {str(e)}")
        return jsonify({'message': 'Lỗi khi cập nhật giao dịch', 'error': str(e)}), 500

# Xóa giao dịch (Admin)
@payment_transaction_bp.route('/payment-transactions/<int:transaction_id>', methods=['DELETE'])
@admin_required()
def delete_payment_transaction(transaction_id):
    logging.info(f"DELETE /payment-transactions/{transaction_id}")
    try:
        transaction = PaymentTransaction.query.get(transaction_id)
        if not transaction:
            return jsonify({'message': 'Transaction not found'}), 404

        if transaction.status == 'SUCCESS':
            return jsonify({'message': 'Cannot delete: Transaction is successful'}), 409

        bill = MonthlyBill.query.get(transaction.bill_id)
        if not bill:
            return jsonify({'message': 'Bill not found'}), 404

        db.session.delete(transaction)
        db.session.commit()
        logging.info(f"Deleted PaymentTransaction {transaction_id}")
        return '', 204

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f"IntegrityError in delete_payment_transaction: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa: Có bản ghi liên quan không thể xóa do ràng buộc khóa ngoại'}), 409
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error in delete_payment_transaction: {str(e)}")
        return jsonify({'message': 'Lỗi khi xóa giao dịch', 'error': str(e)}), 500