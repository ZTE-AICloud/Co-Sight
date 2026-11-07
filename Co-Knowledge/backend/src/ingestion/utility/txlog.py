import logging


def get_tx_id_from_req(req: dict) -> str | None:
    try:
        kwargs = (req or {}).get('kwargs')
        return (kwargs or {}).get('txId')
    except Exception:
        return None


def build_prefix(tx_id: str | None) -> str:
    return f"[{tx_id}] >>> " if tx_id else ""


class TxPrefixedLogger:
    def __init__(self, tx_id: str | None):
        self._prefix = build_prefix(tx_id)

    def info(self, message: str):
        logging.info(self._prefix + message)

    def error(self, message: str):
        logging.error(self._prefix + message)

    def warning(self, message: str):
        logging.warning(self._prefix + message)

    def debug(self, message: str):
        logging.debug(self._prefix + message)

    def exception(self, message: str | Exception):
        if isinstance(message, Exception):
            logging.exception(self._prefix + str(message))
        else:
            logging.exception(self._prefix + message)


