"""文档处理模块的文件客户端。

持久文件（资产包）走后端抽象（本地卷 / MinIO）；清洗产物
``clean/`` 属于进程内中间件，仍写本地 scratch —— 切片算子需要真实文件路径。

对象键与历史本地布局一致：``dump/<文件名>``。
本地后端的根是 ``RKB_KBASE_STORAGE_PATH``（默认 ``/data/kb``），MinIO 后端则写桶。
"""

import os
import shutil
import uuid

from infrastructure.storage import keys
from infrastructure.storage.backend import scratch_root, storage_backend


class LocalClient:
    def __init__(self, base_folder):
        #: 历史字段：改造前是本地落盘根。持久文件现在由 storage_backend() 决定；
        #: 保留它是为了让 DiskClientManager 的构造方式不用改。
        self._base_folder = base_folder

    def upload_dump_file(self, source_file: str):
        key = keys.dump_key(source_file)
        storage_backend().put(key, source_file, overwrite=True)
        local_path = storage_backend().local_path(key)
        return str(local_path) if local_path is not None else key

    def upload_clean_file(self, source_file: str, emp):
        """清洗产物写本地 scratch（MinIO 模式下也不进桶）。"""
        u_id = str(uuid.uuid4())
        destination_folder = os.path.join(str(scratch_root()), 'clean', u_id[0:2])
        # 确保目标文件夹存在
        os.makedirs(destination_folder, exist_ok=True)
        destination_file = os.path.join(destination_folder, u_id)
        shutil.copy(source_file, destination_file)
        return destination_file


if __name__ == '__main__':
    client = LocalClient(os.environ.get("STORAGE_MAIN_PATH", "/data/kb"))
    client.upload_clean_file(os.path.join(os.environ.get("STORAGE_MAIN_PATH", "/data/kb"),
                                          "core/0eea/0eea03ab26cc4d8ea523850730c3ddb7"), "111")
