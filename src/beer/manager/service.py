import logging
import os
from typing import Any, List, Mapping, Sequence

import orjson
from docker.models.configs import Config
from docker.models.nodes import Node
from docker.models.services import Service
from docker.types import ConfigReference, EndpointSpec
from fastapi import Body, FastAPI
from playhouse.shortcuts import model_to_dict
from starlette.requests import Request
from starlette.responses import JSONResponse

import docker

import beer  # noqa
from beer.manager import beer_db
from beer.manager.api import ManagerAnswer, PermissionLevel, ReturnCodes
from beer.manager.beer_db import GPU, DBError, User, UserConfig, Worker
from beer.models import JobRequestModel, RequestUser, WorkerModel
from beer.utils import run_service

pylogger = logging.getLogger(__name__)

_RETURN_CODE_KEY: str = "code"
_DATA_CODE_KEY: str = "data"
_WORKER_TOKEN: str


class ORJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


app = FastAPI(default_response_class=ORJSONResponse, debug=True)

client = docker.from_env()


@app.post("/join")
def add_worker(worker_model: WorkerModel, request: Request):
    worker_model.external_ip = request.client.host
    try:
        worker = Worker.register(worker_model=worker_model)
        return ManagerAnswer(code=ReturnCodes.WORKER_INFO, data={"info": worker.__data__})
    except DBError as e:
        return ManagerAnswer(code=ReturnCodes.DB_ERROR, data={"message": e.message})


def permission_check(request_user: RequestUser, required_level: PermissionLevel) -> bool:
    User.update_details(user_id=request_user.user_id, username=request_user.username, full_name=request_user.full_name)

    if not User.permission_check(user_id=request_user.user_id, required_level=required_level.value):
        return False

    return True


@app.post("/set_permission")
def set_permission(
    request_user: RequestUser, user_id: str = Body(None), permission_level: PermissionLevel = Body(None)
):

    if not User.is_registered(user_id=request_user.user_id):
        pylogger.debug(f"<permission_check> User {request_user} not registered")

        admins = User.get_admins()
        admins = [f"- @{admin.username}" for admin in admins if admin.username is not None]
        admins = "\n".join(admins)
        return ManagerAnswer(code=ReturnCodes.NOT_REGISTERED_ERROR, data={"admins": admins})

    if not permission_check(request_user=request_user, required_level=permission_level.higher_permission()):
        return ManagerAnswer(code=ReturnCodes.PERMISSION_ERROR, data={})

    if not User.is_registered(user_id=user_id):
        return ManagerAnswer(code=ReturnCodes.NOT_REGISTERED_ERROR, data={"user_id": user_id})

    pylogger.info(f"Registering: {user_id} as {permission_level=}")
    try:
        User.register(user_id=user_id, permission_level=permission_level)
        return ManagerAnswer(
            # TODO: Change message/code
            code=ReturnCodes.REGISTRATION_SUCCESSFUL,
            data={"user_id": user_id, "permission_level": permission_level},
        )
    except Exception as e:
        return ManagerAnswer(code=ReturnCodes.DB_ERROR, data={"args": e.args})


@app.post("/register_user")
def register_user(request_user: RequestUser, user_id: str = Body(None)):
    if not User.is_registered(user_id=request_user.user_id):
        pylogger.debug(f"<permission_check> User {request_user} not registered")

        admins = User.get_admins()
        admins = [f"- @{admin.username}" for admin in admins if admin.username is not None]
        admins = "\n".join(admins)
        return ManagerAnswer(code=ReturnCodes.NOT_REGISTERED_ERROR, data={"admins": admins})

    if not permission_check(request_user=request_user, required_level=PermissionLevel.ADMIN):
        return ManagerAnswer(code=ReturnCodes.PERMISSION_ERROR, data={})

    if User.is_registered(user_id=user_id):
        return ManagerAnswer(code=ReturnCodes.ALREADY_REGISTERED_ERROR, data={"user_id": user_id})

    pylogger.info(f"Registering: {user_id}")
    try:
        User.register(user_id=user_id, permission_level=PermissionLevel.USER)
        return ManagerAnswer(code=ReturnCodes.REGISTRATION_SUCCESSFUL, data={"user_id": user_id})
    except Exception as e:
        return ManagerAnswer(code=ReturnCodes.DB_ERROR, data={"args": e.args})


@app.post("/set_ssh_key")
def set_ssh_key(request_user: RequestUser, ssh_key: str = Body(None)):
    if not User.is_registered(user_id=request_user.user_id):
        pylogger.debug(f"<permission_check> User {request_user} not registered")

        admins = User.get_admins()
        admins = [f"- @{admin.username}" for admin in admins if admin.username is not None]
        admins = "\n".join(admins)
        return ManagerAnswer(code=ReturnCodes.NOT_REGISTERED_ERROR, data={"admins": admins})

    if not permission_check(request_user=request_user, required_level=PermissionLevel.USER):
        return ManagerAnswer(code=ReturnCodes.PERMISSION_ERROR, data={})

    user: User = User.get_by_id(request_user.user_id)
    if (user_config := user.config) is not None:
        docker_config: Config = client.configs.get(config_id=user_config.id)
        docker_config.remove()

    config_name: str = f"ssh-key_{user.id}"
    config_id = client.configs.create(name=config_name, data=ssh_key)

    user_config = UserConfig.create(id=config_id, name=config_name, public_ssh_key=ssh_key)
    user.config = user_config

    user.save()


@app.post("/job")
def dispatch(request_user: RequestUser, job: JobRequestModel = Body(None)):
    worker: Worker = Worker.get_by_id(pk=job.worker_hostname)
    user: User = User.get_by_id(pk=job.user_id)

    ssh_key: str = user.public_ssh_key if (job_key := job.ssh_access_key) is None else job_key
    if ssh_key is None:
        return ManagerAnswer(code=ReturnCodes.KEY_MISSING_ERROR)

    service: Service = client.services.create(
        image=job.image,
        name=job.name,
        tty=True,
        container_labels={"beer.user_id": job.user_id},  # TODO
        endpoint_spec=EndpointSpec(ports={None: (22, None, "host")}),
        constraints=[f"node.hostname=={worker.hostname}"],
        configs=[
            ConfigReference(
                config_id=user.config.id, config_name=user.config.name, filename="/root/.ssh/authorized_keys"
            )
        ]
        # args=["-d"],
    )

    # job.ssh_access_key = user.public_ssh_key

    return ManagerAnswer(code=ReturnCodes.DISPATCH_OK, data={"service.attrs": service.attrs})


@app.post("/list_resources")
def list_resources(request_user: RequestUser, only_online: bool = Body(None), only_available: bool = Body(None)):
    if not permission_check(request_user=request_user, required_level=PermissionLevel.USER):
        return ManagerAnswer(code=ReturnCodes.PERMISSION_ERROR, data={})

    workers: List[Node] = client.nodes.list(filters={"role": "worker"})

    online_workers: List[str] = []
    for node in workers:
        # Force re-loading node information from Docker API
        node.reload()
        if node.attrs["Status"]["State"] == "ready" and node.attrs["Spec"]["Availability"] == "active":
            online_workers.append(node.attrs["Description"]["Hostname"])

    resources: Mapping[Worker, Sequence[GPU]] = GPU.by_workers(worker_ids=online_workers)

    return ManagerAnswer(
        code=ReturnCodes.RESOURCES,
        data={
            "workers": {worker.hostname: model_to_dict(worker) for worker in resources.keys()},
            "gpus": {
                worker.hostname: [model_to_dict(gpu, recurse=False) for gpu in gpus]
                for worker, gpus in resources.items()
            },
        },
    )


def run(worker_token: str):
    service_port: int = int(os.environ["MANAGER_SERVICE_PORT"])
    service_host: str = os.environ["MANAGER_SERVICE_HOST"]
    owner_id: str = os.environ["OWNER_ID"]

    beer_db.init(owner_id=owner_id)

    global _WORKER_TOKEN
    _WORKER_TOKEN = worker_token

    run_service(app=app, service_host=service_host, service_port=service_port)
