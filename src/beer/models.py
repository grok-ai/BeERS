from typing import Any, List, Mapping, Optional, Sequence

from pydantic import BaseModel

from beer.nvidia import NvidiaGPU


class WorkerModel(BaseModel):
    hostname: str
    external_ip: Optional[str]

    gpus: List[NvidiaGPU]
    # ram: Mapping[str, int]
    # disk: Mapping[str, int]

    info: Mapping[str, Any]


class JobRequestModel(BaseModel):
    user_id: str
    image: str
    name: str
    worker_hostname: str
    expected_duration: int
    gpu_device_ids: Sequence[int]
    ram: Optional[int]
    disk: Optional[int]


class RequestUser(BaseModel):
    user_id: str
    username: Optional[str]
    full_name: str
