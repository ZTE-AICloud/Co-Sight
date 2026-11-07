import uuid

from shared.errors.exception import EMException
from infrastructure.logging.logutil import log


class EMRequestHeaders(object):
    username: str
    tenant_id: str
    language_option: str = 'en-US'
    client_ip: str
    connect_mode: str
    time_zone_info: str
    transaction_id: str = str(uuid.uuid4())
    mode: str = '0'
    cookie: str

    def set_username(self, username):
        self.username = username

    def set_tenant_id(self, tenant_id):
        self.tenant_id = tenant_id

    def set_language_option(self, language_option):
        self.language_option = language_option

    def set_client_ip(self, client_ip):
        self.client_ip = client_ip

    def set_connect_mode(self, connect_mode):
        self.connect_mode = connect_mode

    def set_timezone_info(self, timezone_info):
        self.time_zone_info = timezone_info

    def set_mode(self, mode):
        self.mode = mode

    def set_cookie(self, cookie):
        self.cookie = cookie

    def get_username(self):
        return self.username

    def get_language_option(self):
        return self.language_option

    def get_client_ip(self):
        return self.client_ip

    def get_connect_mode(self):
        return self.connect_mode

    def get_timezone_info(self):
        return self.time_zone_info

    def set_transaction_id(self, transaction_id):
        if transaction_id:
            self.transaction_id = transaction_id

    def get_transaction_id(self):
        return self.transaction_id

    def get_mode(self):
        return self.mode

    def check_param(self):
        if self.mode not in ['0', '1']:
            log.warning('mode is illegal')
            raise EMException('mode-illegal')
