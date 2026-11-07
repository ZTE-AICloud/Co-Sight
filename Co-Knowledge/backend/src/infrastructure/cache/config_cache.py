from infrastructure.config.constants import const
from infrastructure.config.constants import DEFAULT_MEMORY
from infrastructure.logging.logutil import log

cached_memory = None


def get_cpu_memory():
    global cached_memory
    if cached_memory is None:
        log.info(f"limit memory: {const.memory}")
        cached_memory = float(const.memory) if const.memory else DEFAULT_MEMORY
    return cached_memory
