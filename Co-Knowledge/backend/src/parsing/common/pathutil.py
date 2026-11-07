import os
import shutil

from parsing.common.logutil import log


def get_workdir():
    return os.path.dirname(os.path.dirname(__file__))


def create_parent_dir_all_path(file_path):
    parent_directory = os.path.dirname(file_path)
    if not os.path.exists(parent_directory):
        os.makedirs(parent_directory, exist_ok=True)


def create_dir_under_root(file_path):
    if not os.path.exists(get_workdir() + file_path):
        os.makedirs(get_workdir() + file_path, exist_ok=True)
    return get_workdir() + file_path


def get_name_pre(corpus_txt_name):
    return os.path.splitext(corpus_txt_name)[0]


def get_base_name(path):
    return os.path.basename(path)


def delete_temp():
    try:
        if os.path.exists(f'{get_workdir()}/temp'):
            shutil.rmtree(f'{get_workdir()}/temp')
    except Exception as e:
        log.error('delete temp error ', e)
