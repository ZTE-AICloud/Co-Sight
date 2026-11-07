# -*- coding: utf-8 -*-
import configparser
from ingestion.utility.singleton import singleton


@singleton
class Config(object):
    def __init__(self, config_file_path):
        self._config = configparser.ConfigParser()
        self._config.read(config_file_path, encoding='utf-8')

    def get_config(self, area, arg):
        return self._config[area][arg]
