"""服务配置（全部经环境变量注入）。

落盘根由 ``STORAGE_MAIN_PATH``（compose 里挂卷）决定；配置/日志目录跟随代码目录，
可用 ``CONFIG_DIR`` / ``LOG_DIR`` 覆盖。语料与 zedx 的 PVC 路径由
``PLUGIN_PVC_PATH`` / ``PLUGIN_SOURCE_PATH`` / ``ZEDX_PVC_PATH`` 注入。

``PLUGIN_`` 是既有命名（原「知识库插件仓库」），compose 与文档已引用该变量名。
"""
import os

#: 服务根 = ``src/`` 的父目录。本文件位于 ``src/infrastructure/config/``，
#: 必须向上四层回到服务根，否则 ``data`` / ``work_dir`` 的默认落盘位置会整体漂移。
_SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: 落盘根目录（切片/标准文件/临时文件）。compose 中挂载独立卷 rkb-storage
#: （独立卷，避免与其他模块写同一批文件）。
STORAGE_MAIN_PATH = os.environ.get('STORAGE_MAIN_PATH', os.path.join(_SERVICE_DIR, 'data'))

#: 落盘根（装上传源文件与 zedx；见模块 docstring）
PLUGIN_PVC_PATH = os.environ.get('PLUGIN_PVC_PATH', os.path.join(STORAGE_MAIN_PATH, 'plugins'))

#: 上传语料的源文件目录（`const.knowledge_file_path` 读它）
PLUGIN_SOURCE_PATH = os.environ.get('PLUGIN_SOURCE_PATH', os.path.join(PLUGIN_PVC_PATH, 'sourcefile'))

#: ZEDX 资产解压目录
ZEDX_PVC_PATH = os.environ.get('ZEDX_PVC_PATH', os.path.join(PLUGIN_PVC_PATH, 'zedx'))

Config = {
    "dev_mode": os.environ.get('DEV_MODE', 'false').lower(),
    "work_dir": os.environ.get('WORK_DIR', _SERVICE_DIR),
    "storage_main_path": STORAGE_MAIN_PATH,
    "plugin_pvc_path": PLUGIN_PVC_PATH,
    "plugin_source_path": PLUGIN_SOURCE_PATH,
    "zedx_pvc_path": ZEDX_PVC_PATH,
}
