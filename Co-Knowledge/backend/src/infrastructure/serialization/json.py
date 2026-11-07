import json

from infrastructure.logging.logutil import log


def bean_to_json(obj):
    return json.loads(json.dumps(obj, default=lambda x: x.__dict__))


def str_to_json(string):
    return json.loads(string)


def json_to_str(json_obj):
    return json.dumps(json_obj)


def json_unescape_dumps(content):
    escape = "unicode_escape"
    return json.dumps(content, ensure_ascii=False).encode(escape).decode(escape)


def read_json_file(filepath):
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        log.exception(e)
        log.warning('Failed to read file=%s' % filepath)
