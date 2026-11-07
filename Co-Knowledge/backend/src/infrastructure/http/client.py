from infrastructure.http.request_headers import EMRequestHeaders
from shared.errors.exception import EMException
from infrastructure.http import headers as httputil
from infrastructure.logging.logutil import log


def build_headers(request_headers: EMRequestHeaders):
    return {
        'Content-Type': 'application/json',
        'TransactionID': request_headers.transaction_id,
        'language-option': request_headers.language_option,
        'X-Forwarded-For': request_headers.client_ip
    }


def check_status_code(status_code, service_name):
    if not httputil.is_success(status_code):
        log.warning("bad status code = %s" % status_code)
        raise EMException('bad-status-code', service_name, status_code)
