import os
from datetime import timedelta

class Config:
    def __init__(self):
        self.SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

        self.JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
        self.JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
        self.JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
        self.JWT_BLACKLIST_ENABLED = True
        self.JWT_BLACKLIST_TOKEN_CHECKS = ['access']


        self.MAX_CONTENT_LENGTH = 1100 * 1024 * 1024

        self.VNPAY_TMN_CODE = os.getenv('VNPAY_TMN_CODE')
        self.VNPAY_HASH_SECRET = os.getenv('VNPAY_HASH_SECRET')
        self.VNPAY_URL = os.getenv('VNPAY_URL')

        self.MAIL_SERVER = os.getenv('MAIL_SERVER')
        self.MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
        self.MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
        self.MAIL_USERNAME = os.getenv('MAIL_USERNAME')
        self.MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
        self.MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')

        self.NGROK_URL = os.getenv('NGROK_URL')
