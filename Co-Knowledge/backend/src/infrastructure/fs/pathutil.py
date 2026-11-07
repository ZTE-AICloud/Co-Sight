import os

from infrastructure.config.settings import Config
root_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def get_workdir():
    return os.path.dirname(root_path)


def get_data_path(sub_path):
    sub_path = os.path.join(root_path, 'data', sub_path)
    os.makedirs(sub_path, exist_ok=True)
    return sub_path


def get_asset_center_path(mode: str = '0'):
    # "asset-center" 是本地数据目录名（知识库安装产物落盘处），compose 的卷布局引用它。
    dir_name = 'asset-center-publish' if mode == '1' else 'asset-center'
    sub_path = os.path.join(root_path, 'data', dir_name)
    os.makedirs(sub_path, exist_ok=True)
    return sub_path


pvc_base_path = os.sep + os.sep.join(['home', 'intelligent-assistants'])


def get_default_data_package_path():
    temp_path = os.path.join(get_work_dir(), "processor-data")
    if not os.path.exists(temp_path):
        os.makedirs(temp_path)
    return temp_path


def get_work_dir():
    return Config.get('work_dir')


def get_conf_dir():
    return os.path.join(get_work_dir(), 'config')


def create_dir_under_root(file_path):
    if not os.path.exists(get_work_dir() + file_path):
        os.makedirs(get_work_dir() + file_path, exist_ok=True)
    return get_work_dir() + file_path


def get_plugins_pvc_path():
    # 部署路径由 PLUGIN_PVC_PATH 注入
    return Config.get('plugin_pvc_path')


def get_file_track_path():
    sub_path = os.path.join(get_work_dir(), 'file_track')
    os.makedirs(sub_path, exist_ok=True)
    return sub_path
