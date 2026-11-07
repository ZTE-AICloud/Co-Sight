import chardet


def detect_encoding(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()
        result = chardet.detect(data)
        return result['encoding']
