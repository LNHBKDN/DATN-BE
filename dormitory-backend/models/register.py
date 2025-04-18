from extensions import db

class Register(db.Model):
    __tablename__ = 'register'
    registration_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name_student = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    status = db.Column(db.Enum('PENDING', 'APPROVED', 'REJECTED'), default='PENDING', nullable=False)
    information = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id', ondelete='SET NULL'), nullable=True)
    number_of_people = db.Column(db.Integer, default=1)

    meeting_datetime = db.Column(db.TIMESTAMP, nullable=True)  # Lưu thời gian gặp mặt, có thể để trống
    meeting_location = db.Column(db.String(255), default="Văn phòng ký túc xá")  # Địa điểm mặc định
    # relationship với bảng Room
    room = db.relationship('Room', backref='registers', lazy=True)

    def to_dict(self):
        return {
            'registration_id': self.registration_id,
            'name_student': self.name_student,
            'email': self.email,
            'phone_number': self.phone_number,
            'status': self.status,
            'information': self.information,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            
            'number_of_people': self.number_of_people,
            'meeting_datetime': self.meeting_datetime.isoformat() if self.meeting_datetime else None,
            'meeting_location': self.meeting_location,
            # relationships
            'room_details': self.room.to_dict() if self.room else None
        }