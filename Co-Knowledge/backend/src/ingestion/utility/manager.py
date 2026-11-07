import logging

from ingestion.utility.local_disk import LocalClient
from ingestion.utility.pg_database import PGClient
from ingestion.utility.utils import get_config


class DiskClientManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DiskClientManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        config = get_config()
        base_folder = config['LocalDisk']['baseFolder']
        self.disk_client = LocalClient(base_folder)
        return

    def get_disk_client(self):
        return self.disk_client


def get_pg_pw(config):
    """数据库口令来自环境（``RKB_DB_PASSWORD``），由 config 装载器注入。"""
    return config['PGDatabase']['password']


class PGClientManager:

    def get_pg_client(self):
        config = get_config()
        host = config['PGDatabase']['host']
        database = config['PGDatabase']['database']
        user = config['PGDatabase']['user']
        logging.info("start to get password")
        password = get_pg_pw(config)
        port = config['PGDatabase']['port']
        return PGClient(host, database, user, password, port)
