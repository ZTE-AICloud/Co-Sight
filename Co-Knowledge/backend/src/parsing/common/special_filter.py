import re


class SpecialFilter:
    def __init__(self):
        pass

    def char_filter(self, text: str):
        text = text.replace("\xa0", " ").replace("\ufeff", " ").replace('。：','。')
        return text

    def replace_char(self, key):
        key = key.replace("【", "").replace("】", "").replace("-", "").replace("\xa0", "").replace("\ufeff", " ").replace(
            "\n", "")
        key = '，'.join([item for item in key.split("|") if len(item.strip()) > 0])
        key = re.sub(r',+', ',', key)
        key = re.sub(r'\d+、', '', key)
        key = re.sub(r'\d+、', '', key)
        key = re.sub(r'[^\w\s\d\u4e00-\u9fa5。，；？！：、]', '', key)
        key = re.sub(r'[\u2460-\u24FF]', '', key)
        return key

    def replace_path_char(self, key):
        key = re.sub(r'[^\w\s]', '', key)
        return key.replace(' ','_')

    def replace_content_char(self, text: str):
        text = text.replace("如下图所示", "").replace("\xa0", "").replace("\\n", "\n").replace("\r", "")
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r'^(?:\d+(\.\d+)*\s+)+', '', text)
        # 不能动
        text = text.replace("：\n 如图", "如图").replace('\t', '').replace("\ufeff", " ")
        return text

    def replace_pic_and_serial(self, sentence):
        sentence = self.replace_char(sentence).strip()
        sentence = re.sub(r'如图\d+所示', '', sentence)
        sentence = re.sub(r'\s+', ' ', sentence)
        sentence = re.sub(r'^\d+\.', ' ', sentence).strip()
        sentence = re.sub(r'^\d+）', ' ', sentence).strip()
        return sentence.rstrip("，")

    def replace_char_for_pic(self, text: str):
        text = text.replace("如下图所示", "").replace("\xa0", "").replace("，。", "")
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r'^(?:\d+(\.\d+)*\s+)+', '', text)
        # 不能动
        text = text.replace("：\n 如图", "如图").replace(" 如图", "如图").replace('\t', '')
        return text
