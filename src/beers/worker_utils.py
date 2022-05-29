import logging
import platform
import re
import socket
import uuid
from typing import Optional

import psutil

from beers import nvidia
from beers.models import WorkerModel

pylogger = logging.getLogger(__name__)


def build_worker_specs(local_nfs_root: Optional[str]) -> WorkerModel:

    # https://stackoverflow.com/a/58420504
    try:
        info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "hostname": socket.gethostname(),
            "local_ip": socket.gethostbyname(socket.gethostname()),
            "mac_address": ":".join(re.findall("..", "%012x" % uuid.getnode())),
            "processor": platform.processor(),
            "machine": platform.machine(),
        }

        unit_measure = 1024.0**3

        if local_nfs_root is not None:
            disk = psutil.disk_usage(local_nfs_root)

            disk = dict(
                total=disk.total / unit_measure,
                used=disk.used / unit_measure,
                free=disk.free / unit_measure,
                usage_percent=disk.percent,
            )

        ram = psutil.virtual_memory()
        ram = dict(
            total=ram.total / unit_measure,
            used=ram.used / unit_measure,
            free=ram.free / unit_measure,
            usage_percent=ram.percent,
        )

        return WorkerModel(
            hostname=platform.uname().node,
            info=info,
            local_nfs_root=local_nfs_root,
            # ram=ram,
            # disk=disk,
            gpus=nvidia.get_gpus(),
        )
    except Exception as e:
        pylogger.exception(e)
