from extensions import db
from datetime import datetime

class RefreshToken(db.Model):
    __tablename__ = 'refresh_tokens'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    jti = db.Column(db.String(36), nullable=False, unique=True, index=True)
    user_id = db.Column(db.BigInteger, nullable=True)  # For users
    admin_id = db.Column(db.Integer, nullable=True)    # For admins
    type = db.Column(db.String(10), nullable=False)    # 'USER' or 'ADMIN'
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'jti': self.jti,
            'user_id': self.user_id,
            'admin_id': self.admin_id,
            'type': self.type,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }