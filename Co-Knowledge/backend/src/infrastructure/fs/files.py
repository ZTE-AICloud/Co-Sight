import os


from infrastructure.fs import pathutil


def get_file_type(file_name):
    return file_name.rsplit('.', 1)[1].lower()


def get_files_under_dir(path):
    file_path_list = []
    _append_file_path_2_list(path, file_path_list)
    return file_path_list


def _append_file_path_2_list(path, path_list):
    for file_name in os.listdir(path):
        file_path = os.path.join(path, file_name)
        if os.path.isfile(file_path):
            path_list.append(file_path)
        elif os.path.isdir(file_path):
            _append_file_path_2_list(file_path, path_list)


def create_save_directory(dir_name: str) -> str:
    """创建保存目录并返回完整路径"""
    saved_path = pathutil.get_default_data_package_path() + os.sep + dir_name
    if not os.path.exists(saved_path):
        os.makedirs(saved_path)
    return saved_path
