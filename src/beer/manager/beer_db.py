import itertools
import logging
import operator
import os
from typing import Mapping, Sequence

import orjson
from peewee import (
    CharField,
    CompositeKey,
    DateTimeField,
    FixedCharField,
    ForeignKeyField,
    IntegerField,
    IPField,
    Model,
    ModelSelect,
    ModelUpdate,
    SqliteDatabase,
)
from playhouse.sqlite_ext import JSONField

import beer  # noqa
from beer.manager.api import PermissionLevel
from beer.models import WorkerModel
from beer.nvidia import NvidiaGPU

_db: SqliteDatabase = SqliteDatabase(os.environ["BEER_DB_PATH"])
pylogger = logging.getLogger(__name__)


class DBError(RuntimeError):
    def __init__(self, message: str):
        super().__init__()
        self.message: str = message


class User(Model):
    id = CharField(primary_key=True)
    username = CharField(unique=True, null=True, default=None)
    full_name = CharField(null=True, default=None)
    permission_level = IntegerField(default=2)
    public_ssh_key = CharField(unique=True, null=True, default=None)

    class Meta:
        database = _db

    @classmethod
    def permission_check(cls, user_id: str, required_level: int) -> bool:
        matching_users: ModelSelect = User.select().where(User.id == user_id)

        return (user := matching_users.get_or_none()) is not None and user.permission_level <= required_level

    @classmethod
    def is_registered(cls, user_id: str) -> bool:
        matching_users: ModelSelect = User.select().where(User.id == user_id)
        return matching_users.get_or_none() is not None

    @classmethod
    def register(cls, user_id: str, permission_level: PermissionLevel) -> str:
        # TODO: check consistency/update in DB
        return User.replace(id=user_id, permission_level=permission_level.value).execute()

    @classmethod
    def update_permissions(cls, user_id: str, permission_level: PermissionLevel):
        update: ModelUpdate = User.update(permission_level=permission_level.value).where(User.id == user_id)
        return update.execute()

    @classmethod
    def update_details(cls, user_id: str, username: str, full_name: str):
        update: ModelUpdate = User.update(username=username, full_name=full_name).where(User.id == user_id)
        return update.execute()

    @classmethod
    def having_permission(cls, permission_level: int) -> Sequence["User"]:
        # TODO: check
        return list(cls.select().where(User.permission_level <= permission_level))


class Worker(Model):
    hostname = CharField(primary_key=True, max_length=42)
    node_id = CharField(unique=True)  # swarm id
    ip = IPField()
    local_nfs_root = CharField()
    info = JSONField(json_dumps=orjson.dumps, json_loads=orjson.loads)

    class Meta:
        database = _db

    @classmethod
    def register(cls, worker_model: WorkerModel) -> "Worker":
        worker: Worker = Worker.select().where(Worker.hostname == worker_model.hostname).get_or_none()

        if worker is not None:
            pylogger.info(f"Updating existing worker {worker} to {worker_model}")
            worker.ip = worker_model.external_ip
            worker.info = worker_model.info
            worker.local_nfs_root = worker_model.local_nfs_root
            worker.save(only=[Worker.ip, Worker.info, Worker.local_nfs_root])
        else:
            pylogger.info(f"Registering new worker {worker_model}")
            worker = Worker.create(
                hostname=worker_model.hostname,
                ip=worker_model.external_ip,
                info=worker_model.info,
                local_nfs_root=worker_model.local_nfs_root,
            )

        for gpu in worker_model.gpus:
            GPU.register(gpu_model=gpu, worker_id=worker.hostname)

        return worker

    @classmethod
    def get_workers(cls, worker_ids: Sequence[str]) -> Sequence["Worker"]:
        worker_ids = list(worker_ids)
        return list(Worker.select().where(Worker.hostname << worker_ids))


class Job(Model):
    name = CharField()
    user = ForeignKeyField(User)
    image = CharField()
    container = FixedCharField(max_length=64, primary_key=True)
    worker_hostname = CharField()
    worker_info = JSONField(default=None, null=True)
    start_time = DateTimeField()
    expected_end_time = DateTimeField()
    end_time = DateTimeField(null=True, default=None)

    ram = IntegerField(null=True, default=None)
    disk = IntegerField(null=True, default=None)

    class Meta:
        database = _db


class GPU(Model):
    worker = ForeignKeyField(model=Worker)
    uuid = CharField()
    name = CharField()
    index = IntegerField()
    total_memory = IntegerField()
    info = JSONField(json_dumps=orjson.dumps, json_loads=orjson.loads)
    owner = ForeignKeyField(model=User, null=True, default=None)
    current_job = ForeignKeyField(model=Job, null=True, default=None)

    class Meta:
        database = _db
        indexes = [(("worker", "index"), True)]
        primary_key = CompositeKey("worker", "uuid")  # TODO: uuid could be enough, if consistent across machines

    @classmethod
    def register(cls, gpu_model: NvidiaGPU, worker_id) -> "GPU":
        gpu: GPU = GPU.select().where((GPU.worker == worker_id) & (GPU.uuid == gpu_model.uuid)).get_or_none()

        if gpu is None:
            gpu = GPU.create(
                worker=worker_id,
                uuid=gpu_model.uuid,
                name=gpu_model.name,
                index=gpu_model.index,
                total_memory=gpu_model.total_memory,
                info=gpu_model.info,
            )

        return gpu

    @classmethod
    def by_workers(cls, worker_ids: Sequence[str]) -> Mapping[Worker, Sequence["GPU"]]:
        worker_ids = list(worker_ids)
        gpus = list(cls.select().where(GPU.worker << worker_ids))
        return {worker: list(items) for worker, items in itertools.groupby(gpus, key=operator.attrgetter("worker"))}


def init(owner_id: str):
    _db.connect(reuse_if_open=True)
    _db.create_tables(models=[User, Worker, Job, GPU])
    User.register(user_id=owner_id, permission_level=PermissionLevel.OWNER)
