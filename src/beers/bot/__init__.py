from telegram import User

from beers.models import RequestUser


def build_request_user(user: User) -> RequestUser:
    return RequestUser(user_id=str(user.id), username=user.username, full_name=user.full_name)
