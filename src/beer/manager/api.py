import json
from enum import Enum, auto
from typing import Any, Callable, Mapping

import requests
from pydantic import BaseModel
from requests import Response
from telegram import User

from beer.models import JobRequestModel, RequestUser
from beer.utils import StrEnum


class PermissionLevel(Enum):
    OWNER = 0
    ADMIN = 1
    USER = 2

    def higher_permission(self) -> "PermissionLevel":
        permission = list(PermissionLevel)[max(0, list(PermissionLevel).index(self) - 1)]
        return permission


class ReturnCodes(StrEnum):
    DB_ERROR = auto()
    PERMISSION_ERROR = auto()
    ALREADY_REGISTERED_ERROR = auto()
    NOT_REGISTERED_ERROR = auto()
    KEY_MISSING_ERROR = auto()
    RUNTIME_ERROR = auto()
    KEY_IN_USE_ERROR = auto()
    DOCKER_ERROR = auto()

    WORKER_INFO = auto()
    REGISTRATION_SUCCESSFUL = auto()
    PERMISSION_OK = auto()
    DISPATCH_OK = auto()
    RESOURCES = auto()
    SET_KEY_SUCCESSFUL = auto()
    READY = auto()
    KEY_CHECK = auto()
    JOB_LIST = auto()
    JOB_REMOVE_OK = auto()

    @property
    def is_error(self):
        return "error" in self.name.lower()


MESSAGE_FORMAT: Mapping[ReturnCodes, Callable] = {}

MESSAGE_TEMPLATES: Mapping[ReturnCodes, str] = {
    ReturnCodes.DB_ERROR: "A generic error occurred while querying the database!",
    ReturnCodes.PERMISSION_ERROR: "You don't have permission to do that!",
    ReturnCodes.ALREADY_REGISTERED_ERROR: "User is already registered!",
    ReturnCodes.NOT_REGISTERED_ERROR: "User is not registered!",
    ReturnCodes.WORKER_INFO: "Worker info",
    ReturnCodes.REGISTRATION_SUCCESSFUL: "Registration successful!",
    ReturnCodes.PERMISSION_OK: "Ok!",
    ReturnCodes.KEY_MISSING_ERROR: "You first need to add your public SSH key.",
    ReturnCodes.KEY_IN_USE_ERROR: "Can't update your SSH key while in use in job(s).",
}


class ManagerAnswer(BaseModel):
    code: ReturnCodes
    data: Mapping[str, Any] = {}

    @property
    def message(self) -> str:
        if self.code in MESSAGE_FORMAT:
            return MESSAGE_FORMAT[self.code](self.data)
        if self.code in MESSAGE_TEMPLATES:
            return MESSAGE_TEMPLATES[self.code]

        return f"{self.code}:\n\n{json.dumps(self.data, indent=4)}"


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

    def job(self, request_user: User, job: JobRequestModel) -> ManagerAnswer:
        response: Response = self._request(
            endpoint="job",
            json=dict(
                request_user=build_request_user(request_user).dict(),
                job=job.dict(),
            ),
        )
        response: Mapping[str, Any] = response.json()
        return ManagerAnswer(**response)

    def set_ssh_key(self, request_user: User, ssh_key: str) -> ManagerAnswer:
        response: Response = self._request(
            endpoint="set_ssh_key",
            json=dict(request_user=build_request_user(request_user).dict(), ssh_key=ssh_key),
        )

        response: Mapping[str, Any] = response.json()
        return ManagerAnswer(**response)

    def check_connection(self) -> bool:
        response: Response = self._request(
            endpoint="ready",
        )

        response: Mapping[str, Any] = response.json()

        return ManagerAnswer(**response).code == ReturnCodes.READY

    def check_ssh_key(self, request_user: User) -> bool:
        response: Response = self._request(
            endpoint="check_ssh_key",
            json=build_request_user(request_user).dict(),
        )
        response: Mapping[str, Any] = response.json()

        try:
            return ManagerAnswer(**response).data["is_set"]
        except Exception:
            return False

    def job_list(self, request_user: User) -> ManagerAnswer:
        response: Response = self._request(
            endpoint="job_list",
            json=build_request_user(request_user).dict(),
        )
        response: Mapping[str, Any] = response.json()

        return ManagerAnswer(**response)
