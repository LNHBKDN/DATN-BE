from extensions import db
from datetime import date 

class Contract(db.Model):
    __tablename__ = 'contracts'
    __table_args__ = (
        db.Index('idx_contract_user_id', 'user_id'),
        db.Index('idx_contract_room_id', 'room_id'),
        db.Index('idx_contract_status', 'status'),
        db.Index('idx_contract_room_status', 'room_id', 'status'),
    )
    contract_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id', ondelete='RESTRICT'), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False)
    status = db.Column(db.Enum('PENDING', 'ACTIVE', 'EXPIRED', 'TERMINATED'), default='PENDING', nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=False)
    contract_type = db.Column(db.Enum('SHORT_TERM', 'LONG_TERM'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    # relationships
    room = db.relationship('Room', backref='contracts', lazy=True)
    user = db.relationship('User', backref='contracts', lazy=True)

    def to_dict(self):
        return {
            'contract_id': self.contract_id,
            'room_id': self.room_id,
            'user_id': self.user_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'contract_type': self.contract_type,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            # relationships
            'room_details': self.room.to_dict() if self.room else None,
            'user_details': self.user.to_dict() if self.user else None
        }
    @property
    def calculated_status(self):
        """Tính toán trạng thái hợp đồng dựa trên ngày hiện tại."""
        today = date.today()
        if self.status == 'TERMINATED':
            return 'TERMINATED'
        if today < self.start_date:
            return 'PENDING'
        if self.start_date <= today <= self.end_date:
            return 'ACTIVE'
        if today > self.end_date:
            return 'EXPIRED'
        return self.status

    def update_status(self):
        """Cập nhật trạng thái hợp đồng dựa trên calculated_status."""
        self.status = self.calculated_status
        db.session.commit()