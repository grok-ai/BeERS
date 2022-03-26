# Partially borrowed from https://github.com/Avlyssna/gpu-info/blob/master/gpuinfo/nvidia.py
# Standard library imports
import subprocess  # nosec
from typing import Any, List, Mapping

from pydantic import BaseModel


class NvidiaGPU(BaseModel):
    name: str
    uuid: str
    total_memory: int
    index: int
    info: Mapping[str, Any]

    # def get_memory_details(self):
    #     row = query_nvsmi("memory.used,memory.free", self.index)[0]
    #
    #     return {"used_memory": int(row[0]), "free_memory": int(row[1])}


def query_nvsmi(properties: str, index=None):
    query = ["nvidia-smi", f"--query-gpu={properties}", "--format=csv,noheader,nounits"]

    if index is not None:
        query.append(f"--id={index}")

    process = subprocess.Popen(query, stdout=subprocess.PIPE, shell=False)  # nosec
    output = process.stdout.read().decode(encoding="utf-8")
    rows = [line.rstrip().split(", ") for line in output.splitlines()]

    return rows


def get_gpus() -> List:
    rows = query_nvsmi("index,uuid,name,memory.total")
    gpus = []

    for row in rows:
        index, uuid, name, total_memory = row
        index = int(index)
        total_memory = int(total_memory)

        def get_clock_speeds():
            row = query_nvsmi("clocks.gr,clocks.mem", index)[0]
            return {"core_clock_speed": int(row[0]), "memory_clock_speed": int(row[1])}

        def get_max_clock_speeds():
            row = query_nvsmi("clocks.max.gr,clocks.max.mem", index)[0]
            return {"max_core_clock_speed": int(row[0]), "max_memory_clock_speed": int(row[1])}

        info = get_clock_speeds()
        info.update(get_max_clock_speeds())

        gpus.append(NvidiaGPU(index=index, uuid=uuid, name=name, info=info, total_memory=total_memory))

    return gpus
