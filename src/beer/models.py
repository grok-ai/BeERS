from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel

from beer.nvidia import NvidiaGPU


class WorkerModel(BaseModel):
    hostname: str
    external_ip: Optional[str]

    gpus: List[NvidiaGPU]
    # ram: Mapping[str, int]
    # disk: Mapping[str, int]

    local_nfs_root: Optional[str]
    info: Mapping[str, Any]


class ResourcesModel(BaseModel):
    cpu_limit: Optional[int]
    mem_limit: Optional[int]
    cpu_reservation: Optional[int]
    mem_reservation: Optional[int]
    generic_resources: Dict | List[Dict]


class JobRequestModel(BaseModel):
    user_id: str
    image: str
    worker_hostname: str
    expected_duration: int
    # resources: ResourcesModel
    volume_mount: str = "/data"
    gpus: Sequence[Dict]


class RequestUser(BaseModel):
    user_id: str
    username: Optional[str]
    full_name: str
