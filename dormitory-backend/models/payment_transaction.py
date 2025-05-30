from extensions import db
from datetime import datetime

class PaymentTransaction(db.Model):
    __tablename__ = 'payment_transactions'
    transaction_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    bill_id = db.Column(db.BigInteger, db.ForeignKey('monthly_bills.bill_id', ondelete='CASCADE'), nullable=False)
    amount = db.Column(db.DECIMAL(12, 2), nullable=False)
    payment_method = db.Column(db.String(100), nullable=False)
    status = db.Column(db.Enum('PENDING', 'SUCCESS', 'FAILED', 'CANCELLED'), default='PENDING', nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=True)
    processed_at = db.Column(db.TIMESTAMP, nullable=True)
    gateway_reference = db.Column(db.String(255), nullable=True)
    qr_payload = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    bill = db.relationship('MonthlyBill', backref='transactions', lazy=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Validation
        if float(self.amount) <= 0:
            raise ValueError("Amount phải lớn hơn 0")
        if self.payment_method not in ['VNPAY']:
            raise ValueError(f"Phương thức thanh toán không hợp lệ: {self.payment_method}")

    def to_dict(self):
        return {
            'transaction_id': self.transaction_id,
            'bill_id': self.bill_id,
            'amount': str(self.amount),
            'payment_method': self.payment_method,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'gateway_reference': self.gateway_reference,
            'qr_payload': self.qr_payload,
            'error_message': self.error_message,
            'bill_details': {
                'bill_id': self.bill.bill_id,
                'user_id': self.bill.user_id,
                'total_amount': str(self.bill.total_amount),
                'payment_status': self.bill.payment_status
            } if self.bill else None
        }