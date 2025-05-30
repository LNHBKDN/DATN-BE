import os
from datetime import timedelta
import re

class Config:
    def __init__(self):
        # Database settings
        self.SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
        if not self.SQLALCHEMY_DATABASE_URI:
            raise ValueError("DATABASE_URL is not set in environment variables")
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

        # JWT settings
        self.JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
        if not self.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY is not set in environment variables")
        self.JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
        self.JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
        self.JWT_BLACKLIST_ENABLED = True
        self.JWT_BLACKLIST_TOKEN_CHECKS = ['access', 'refresh']

        # Flask settings
        self.SECRET_KEY = os.getenv('SECRET_KEY')
        if not self.SECRET_KEY:
            raise ValueError("SECRET_KEY is not set in environment variables")
        self.SESSION_COOKIE_SECURE = True
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = 'Lax'

        # File upload settings
        self.MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

        # VNPAY settings
        self.VNPAY_TMN_CODE = os.getenv('VNPAY_TMN_CODE')
        self.VNPAY_HASH_SECRET = os.getenv('VNPAY_HASH_SECRET')
        self.VNPAY_URL = os.getenv('VNPAY_URL')

        # Mail settings
        self.MAIL_SERVER = os.getenv('MAIL_SERVER')
        self.MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
        self.MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
        self.MAIL_USERNAME = os.getenv('MAIL_USERNAME')
        self.MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
        self.MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
        if not self.MAIL_DEFAULT_SENDER or not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', self.MAIL_DEFAULT_SENDER):
            raise ValueError("MAIL_DEFAULT_SENDER is not a valid email address")

        # NGROK settings
        self.NGROK_URL = os.getenv('NGROK_URL')