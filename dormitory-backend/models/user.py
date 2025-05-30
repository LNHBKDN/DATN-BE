from extensions import db

class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    fullname = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True)
    date_of_birth = db.Column(db.Date)
    password_hash = db.Column(db.String(255), nullable=False)
    CCCD = db.Column(db.String(12), unique=True)
    class_name = db.Column(db.String(50))
    avatar_url = db.Column(db.String(512))
    created_at = db.Column(db.TIMESTAMP, default=db.func.current_timestamp())
    reset_token = db.Column(db.String(255))
    reset_token_expiry = db.Column(db.DateTime)
    reset_attempts = db.Column(db.Integer, default=0)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.TIMESTAMP)
    version = db.Column(db.Integer, default=1, nullable=False)
    fcm_token = db.Column(db.String(255), nullable=True)
    
    bills = db.relationship('MonthlyBill', back_populates='user', lazy=True)
    submitted_bill_details = db.relationship('BillDetail', back_populates='submitter', lazy=True)

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'fullname': self.fullname,
            'email': self.email,
            'phone': self.phone,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'CCCD': self.CCCD,
            'class_name': self.class_name,
            'avatar_url': self.avatar_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'version': self.version
        }