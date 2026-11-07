# coding=utf-8

import os

Config = {
    # "profile": "prod",
    "profile": "dev",
    "work_dir": os.path.dirname(__file__)
}

class Profile(object):
    @classmethod
    def dev(cls):
        if os.environ.get('DEV_MODE', '').lower() == 'true':
            return True
        pro_file = Config.get("profile")
        if pro_file and str(pro_file).lower() == "dev":
            return True
        return False

    @classmethod
    def prod(cls):
        if os.environ.get('DEV_MODE', '').lower() == 'true':
            return False
        pro_file = Config.get("profile")
        if pro_file and str(pro_file).lower() == "prod":
            return True
        return False
