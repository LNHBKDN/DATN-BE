# utils/fcm.py
from firebase_admin import messaging
import logging
from models.user import User
from extensions import db

logger = logging.getLogger(__name__)

def send_fcm_notification(user_id, title, message, data=None):
    """Gửi FCM notification đến một người dùng."""
    user = User.query.get(user_id)
    if not user or not user.fcm_token:
        logger.warning(f"No FCM token for user_id={user_id}")
        return False

    fcm_message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=message,
        ),
        token=user.fcm_token,
        data=data or {},
    )
    try:
        response = messaging.send(fcm_message)
        logger.info(f"FCM notification sent to user_id={user_id}: {response}")
        return True
    except Exception as e:
        logger.error(f"Error sending FCM notification to user_id={user_id}: {e}")
        return False

def send_fcm_notification_to_multiple(user_ids, title, message, data=None):
    """Gửi FCM notification đến nhiều người dùng."""
    users = User.query.filter(User.user_id.in_(user_ids), User.fcm_token != None).all()
    if not users:
        logger.warning(f"No users with FCM tokens for user_ids={user_ids}")
        return False

    messages = [
        messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=message,
            ),
            token=user.fcm_token,
            data=data or {},
        ) for user in users
    ]
    try:
        batch_response = messaging.send_all(messages)
        successes = sum(1 for response in batch_response.responses if response.success)
        logger.info(f"FCM notifications sent to {successes}/{len(messages)} users")
        return True
    except Exception as e:
        logger.error(f"Error sending FCM notifications to user_ids={user_ids}: {e}")
        return False