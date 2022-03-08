from enum import auto
from typing import Any, Mapping

import requests
from pydantic import BaseModel
from requests import Response
from telegram import User

from beer.models import RequestUser
from beer.utils import StrEnum


class PermissionLevel(StrEnum):
    OWNER = auto()
    ADMIN = auto()
    USER = auto()

    def higher_permission(self):
        permission = list(PermissionLevel)[max(0, list(PermissionLevel).index(self) - 1)]
        return permission


class ReturnCodes(StrEnum):
    DB_ERROR = auto()
    PERMISSION_ERROR = auto()
    ALREADY_REGISTERED_ERROR = auto()
    NOT_REGISTERED_ERROR = auto()
    KEY_MISSING_ERROR = auto()

    WORKER_INFO = auto()
    REGISTRATION_SUCCESSFUL = auto()
    PERMISSION_OK = auto()
    DISPATCH_OK = auto()

    @property
    def is_error(self):
        return "error" in self.name.lower()

    @classmethod
    def format(cls):
        raise NotImplementedError

    @property
    def message(self):
        return self.value[1]


MESSAGE_TEMPLATES: Mapping[ReturnCodes, str] = {
    ReturnCodes.DB_ERROR: "A generic error occurred while querying the database!",
    ReturnCodes.PERMISSION_ERROR: "You don't have permission to do that!",
    ReturnCodes.ALREADY_REGISTERED_ERROR: "User is already registered!",
    ReturnCodes.NOT_REGISTERED_ERROR: "User is not registered!",
    ReturnCodes.WORKER_INFO: "Worker info",
    ReturnCodes.REGISTRATION_SUCCESSFUL: "Registration successful!",
    ReturnCodes.PERMISSION_OK: "Ok!",
    ReturnCodes.KEY_MISSING_ERROR: "You first need to *add your public SSH key.",
}


class ManagerAnswer(BaseModel):
    code: ReturnCodes
    data: Mapping[str, Any]

    @property
    def message(self) -> str:
        # TODO
        return MESSAGE_TEMPLATES[self.code]  # .format(data)


def build_request_user(user: User) -> RequestUser:
    return RequestUser(user_id=str(user.id), username=user.username, full_name=user.full_name)


class ManagerAPI:
    def __init__(self, manager_url: str):
        self.manager_url: str = manager_url

    def _request(self, endpoint: str, **kwargs) -> Response:
        return requests.post(f"{self.manager_url}/{endpoint}", **kwargs)

    def register_user(self, request_user: User, user_id: str) -> ManagerAnswer:
        response: Response = self._request(
            endpoint="register_user",
            json=dict(request_user=build_request_user(request_user).dict(), user_id=user_id),
        )
        response: Mapping[str, Any] = response.json()

        return ManagerAnswer(**response)

    def set_permission(self, request_user: User, user_id: str, permission_level: PermissionLevel) -> ManagerAnswer:
        response: Response = self._request(
            endpoint="set_permission",
            json=dict(
                request_user=build_request_user(request_user).dict(),
                user_id=user_id,
                permission_level=permission_level,
            ),
        )
        response: Mapping[str, Any] = response.json()

        return ManagerAnswer(**response)

    def list_resources(self, request_user: User) -> ManagerAnswer:
        response: Response = self._request(
            endpoint="list_resources",
            json=dict(request_user=build_request_user(request_user).dict(), only_available=True, only_online=True),
        )
        response: Mapping[str, Any] = response.json()
        return ManagerAnswer(**response)
