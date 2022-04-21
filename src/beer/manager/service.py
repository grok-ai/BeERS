import logging
import time
from datetime import datetime, timedelta
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import orjson
from docker.errors import APIError, NotFound
from docker.models.configs import Config
from docker.models.nodes import Node
from docker.models.services import Service
from docker.types import ConfigReference, DriverConfig, EndpointSpec, Mount
from fastapi import Body, FastAPI
from playhouse.shortcuts import model_to_dict
from starlette.requests import Request
from starlette.responses import JSONResponse

import docker

import beer  # noqa
from beer.manager import beer_db
from beer.manager.api import ManagerAnswer, PermissionLevel, ReturnCodes
from beer.manager.beer_db import GPU, DBError, Job, User, Worker
from beer.models import JobRequestModel, RequestUser, WorkerModel
from beer.utils import run_service

pylogger = logging.getLogger(__name__)

_RETURN_CODE_KEY: str = "code"
_DATA_CODE_KEY: str = "data"

_SWARM_RESOURCE: str = "DOCKER_RESOURCE_GPU"

_LABEL_USER_ID: str = "beer.user_id"
_LABEL_EXPIRE: str = "beer.expire"
_LABEL_NFS_SERVER: str = "beer.nfs_server"

_CONFIG_PREFIX: str = "beer_ssh-key_"


class ORJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


app = FastAPI(default_response_class=ORJSONResponse, debug=True)

client = docker.from_env()


def _update_nfs_nodes(workers: Sequence[Node]):
    if len(workers) == 0:
        return

    users: Sequence[User] = User.having_permission(permission_level=PermissionLevel.USER.value)
    if len(users) == 0:
        return

    hostname2nfs_root2address: Sequence[Tuple[str, str, str]] = [
        (
            worker.attrs["Description"]["Hostname"],
            worker.attrs["Spec"]["Labels"][_LABEL_NFS_SERVER],
            worker.attrs["Status"]["Addr"],
        )
        for worker in workers
    ]

    client.containers.run(
        image="alpine:latest",
        tty=True,
        command=[
            "mkdir",
            "-p",
            *(f"/data/{hostname}/{user}" for hostname, _, _ in hostname2nfs_root2address for user in users),
        ],
        mounts=[
            Mount(
                target=f"/data/{hostname}",
                source=f"nfs_volume_{hostname}",
                type="volume",
                driver_config=DriverConfig(
                    name="local",
                    options={
                        "type": "nfs4",
                        "device": f":{nfs_root}",
                        "o": f"addr={address},nfsvers=4,nolock,soft,rw",
                    },
                ),
            )
            for hostname, nfs_root, address in hostname2nfs_root2address
        ],
        remove=True,
    )


@app.post("/ready")
def is_ready():
    return ManagerAnswer(code=ReturnCodes.READY)


@app.post("/join", response_model=ManagerAnswer)
def add_worker(worker_model: WorkerModel, request: Request):
    worker_model.external_ip = request.client.host
    try:
        # DB registration
        worker = Worker.register(worker_model=worker_model)

        try:
            node: Node = client.nodes.get(worker.hostname)
        except APIError:
            return ManagerAnswer(code=ReturnCodes.DOCKER_ERROR)

        if worker.local_nfs_root is not None:
            # The correct flow is to call this endpoint AFTER joining the swarm via Docker, so we can assume the worker
            # is already present in the nodes list
            specs = node.attrs["Spec"]
            specs["Labels"][_LABEL_NFS_SERVER] = worker.local_nfs_root
            node.update(node_spec=specs)

            _update_nfs_nodes(workers=[node])
        return ManagerAnswer(code=ReturnCodes.WORKER_INFO, data={"info": worker.__data__})
    except DBError as e:
        return ManagerAnswer(code=ReturnCodes.DB_ERROR, data={"message": e.message})


def permission_check(request_user: RequestUser, required_level: PermissionLevel) -> Optional[ManagerAnswer]:
    User.update_details(user_id=request_user.user_id, username=request_user.username, full_name=request_user.full_name)

    if required_level == PermissionLevel.USER and not User.is_registered(user_id=request_user.user_id):
        pylogger.debug(f"<permission_check> User {request_user} not registered")

        admins = User.having_permission(permission_level=PermissionLevel.ADMIN.value)
        admins = [f"- @{admin.username}" for admin in admins if admin.username is not None]
        admins = "\n".join(admins)
        return ManagerAnswer(code=ReturnCodes.NOT_REGISTERED_ERROR, data={"admins": admins})

    if not User.permission_check(user_id=request_user.user_id, required_level=required_level.value):
        return ManagerAnswer(
            code=ReturnCodes.PERMISSION_ERROR,
        )


@app.post("/set_permission", response_model=ManagerAnswer)
def set_permission(
    request_user: RequestUser, user_id: str = Body(None), permission_level: PermissionLevel = Body(None)
):
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


@app.post("/register_user", response_model=ManagerAnswer)
def register_user(request_user: RequestUser, user_id: str = Body(None)):
    if (
        permission_error := permission_check(request_user=request_user, required_level=PermissionLevel.ADMIN)
    ) is not None:
        return permission_error

    if User.is_registered(user_id=user_id):
        return ManagerAnswer(code=ReturnCodes.ALREADY_REGISTERED_ERROR, data={"user_id": user_id})

    pylogger.info(f"Registering: {user_id}")
    try:
        User.register(user_id=user_id, permission_level=PermissionLevel.USER)
        nfs_workers: Sequence[Node] = client.nodes.list(filters={"label": _LABEL_NFS_SERVER})
        _update_nfs_nodes(workers=nfs_workers)
        return ManagerAnswer(code=ReturnCodes.REGISTRATION_SUCCESSFUL, data={"user_id": user_id})
    except Exception as e:
        return ManagerAnswer(code=ReturnCodes.DB_ERROR, data={"args": e.args})


@app.post("/set_ssh_key", response_model=ManagerAnswer)
def set_ssh_key(request_user: RequestUser, ssh_key: str = Body(None)):
    if (
        permission_error := permission_check(request_user=request_user, required_level=PermissionLevel.USER)
    ) is not None:
        return permission_error

    user: User = User.get_by_id(request_user.user_id)
    config_name: str = f"{_CONFIG_PREFIX}{user.id}"

    try:
        # Even if configs.get is documented as working by id, it works by name too
        docker_config: Config = client.configs.get(config_name)
        pylogger.info(f"Removing Docker config {docker_config.name}")
        docker_config.remove()
    except NotFound:
        pass
    except APIError as e:
        # TODO
        if "in use by the following service" in e.explanation:
            return ManagerAnswer(code=ReturnCodes.KEY_IN_USE_ERROR, data={})

    docker_config = client.configs.create(name=config_name, data=ssh_key)
    docker_config.reload()

    if docker_config.name != config_name:
        return ManagerAnswer(
            code=ReturnCodes.RUNTIME_ERROR, data={"config_name": config_name, "docker_config_name": docker_config.name}
        )

    user.public_ssh_key = ssh_key

    user.save(only=[User.public_ssh_key])

    return ManagerAnswer(code=ReturnCodes.SET_KEY_SUCCESSFUL)


@app.post("/check_ssh_key", response_model=ManagerAnswer)
def check_ssh_key(request_user: RequestUser):
    if (
        permission_error := permission_check(request_user=request_user, required_level=PermissionLevel.USER)
    ) is not None:
        return permission_error

    user: User = User.get_by_id(request_user.user_id)

    return ManagerAnswer(code=ReturnCodes.KEY_CHECK, data={"is_set": user.public_ssh_key is not None})


@app.post("/job", response_model=ManagerAnswer)
def dispatch(request_user: RequestUser, job: JobRequestModel = Body(None)):
    if (
        permission_error := permission_check(request_user=request_user, required_level=PermissionLevel.USER)
    ) is not None:
        return permission_error

    worker: Worker = Worker.get_by_id(pk=job.worker_hostname)
    user: User = User.get_by_id(pk=job.user_id)
    if user.public_ssh_key is None:
        return ManagerAnswer(code=ReturnCodes.KEY_MISSING_ERROR)

    now: float = time.time()
    now: datetime = datetime.fromtimestamp(now)
    expire: datetime = now + timedelta(hours=job.expected_duration)

    try:
        docker_config: Config = client.configs.get(f"{_CONFIG_PREFIX}{user.id}")
    except NotFound:
        return ManagerAnswer(code=ReturnCodes.KEY_MISSING_ERROR)

    job_name: str = f"{job.user_id}_{now.strftime('%m%d%Y%H%M%S')}"
    service: Service = client.services.create(
        image=job.image,
        name=job_name,
        tty=True,
        labels={_LABEL_USER_ID: job.user_id, _LABEL_EXPIRE: expire.strftime("%m%d%Y%H%M%S")},
        endpoint_spec=EndpointSpec(ports={None: (22, None, "host")}),
        constraints=[f"node.hostname=={worker.hostname}"],
        # resources=Resources(**job.resources.dict()),
        env=[f"{_SWARM_RESOURCE}={gpu['uuid']}" for gpu in job.gpus],
        configs=[
            ConfigReference(
                config_id=docker_config.id,
                config_name=docker_config.name,
                filename="/root/.ssh/authorized_keys",
            )
        ],
        mounts=[
            Mount(
                target=mount["target"],
                source=user.id,
                type="volume",
                driver_config=DriverConfig(
                    name="local",
                    options={
                        "type": "nfs4",
                        "device": f":{mount['source_root']}/{user.id}",
                        "o": f"addr={mount['source_ip']},nfsvers=4,nolock,soft,rw",
                    },
                ),
            )
            for mount in job.mounts
        ]
        # args=["-d"],
    )
    service.reload()

    Job.create(
        name=job_name,
        user=job.user_id,
        image=job.image,
        service=service.id,
        worker_hostname=job.worker_hostname,
        worker_info=worker.info,
        start_time=now,
        expected_end_time=expire,
        gpu=job.gpus[0],  # TODO: add multi-gpu support on the DB side
    )

    return ManagerAnswer(code=ReturnCodes.DISPATCH_OK, data={"service.attrs": service.attrs})


@app.post("/job_list", response_model=ManagerAnswer)
def job_list(request_user: RequestUser):
    if (
        permission_error := permission_check(request_user=request_user, required_level=PermissionLevel.USER)
    ) is not None:
        return permission_error

    user: User = User.get_by_id(pk=request_user.user_id)

    services: Sequence[Service] = [
        service
        for service in client.services.list(filters={"label": _LABEL_USER_ID})
        if service.attrs["Spec"]["Labels"][_LABEL_USER_ID] == user.id
    ]

    return ManagerAnswer(code=ReturnCodes.JOB_LIST, data={"services": [service.attrs for service in services]})


@app.post("/list_resources", response_model=ManagerAnswer)
def list_resources(request_user: RequestUser, only_online: bool = Body(None), only_available: bool = Body(None)):
    if (
        permission_error := permission_check(request_user=request_user, required_level=PermissionLevel.USER)
    ) is not None:
        return permission_error

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


def run(service_port: int, service_host: str, owner_id: str):
    beer_db.init(owner_id=owner_id)

    run_service(app=app, service_host=service_host, service_port=service_port)
