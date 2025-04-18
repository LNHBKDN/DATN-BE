from extensions import db

class Report(db.Model):
    __tablename__ = 'reports'
    report_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    report_type_id = db.Column(db.Integer, db.ForeignKey('report_type.report_type_id', ondelete='RESTRICT'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id', ondelete='RESTRICT'), nullable=False)
    status = db.Column(db.Enum('PENDING', 'RECEIVED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED'), default='PENDING', nullable=False)
    description = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), nullable=True)
    updated_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp(), nullable=True)
    resolved_at = db.Column(db.TIMESTAMP, nullable=True)
    closed_at = db.Column(db.TIMESTAMP, nullable=True)


    # relationships
    report_type = db.relationship('ReportType', backref='reports', lazy=True)
    room = db.relationship('Room', backref='reports', lazy=True)
    user = db.relationship('User', backref='reports', lazy=True)

    def to_dict(self):
        return {
            'report_id': self.report_id,
            'report_type_id': self.report_type_id,
            'title': self.title,
            'room_id': self.room_id,
            'status': self.status,
            'description': self.description,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            # relationships
            'room_details': self.room.to_dict() if self.room else None,
            'report_type_details': self.report_type.to_dict() if self.report_type else None,
            'user_details': self.user.to_dict() if self.user else None
        }