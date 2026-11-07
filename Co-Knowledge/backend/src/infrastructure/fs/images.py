import os
import shutil

from infrastructure.logging.logutil import log


def move_img(target_directory: str,
             work_dir: str,
             file_name: str) -> None:
    source_directory = f'{work_dir}/temp/split/{file_name}/output/images'
    for root, dirs, files in os.walk(source_directory):
        for subdir in dirs:
            source_subdir_path = os.path.join(root, subdir)
            target_subdir_path = os.path.join(target_directory,
                                              os.path.relpath(source_subdir_path, source_directory))
            if not os.path.exists(target_subdir_path):
                os.makedirs(target_subdir_path)
            shutil.copytree(source_subdir_path, target_subdir_path, dirs_exist_ok=True)
            log.info(f"移动目录 {source_subdir_path} 至 {target_subdir_path}")

