import os
import shutil

from infrastructure.logging.logutil import log
from infrastructure.fs.pathutil import get_work_dir

work_dir = get_work_dir()


def delete_temp_files() -> None:
    try:
        log.info(f"pre delete temp {work_dir}/temp")
        if os.path.exists(f'{work_dir}/temp'):
            shutil.rmtree(f'{work_dir}/temp')
        log.info("remove temp finished")
    except Exception as e:
        log.error('remove temp error', e)
