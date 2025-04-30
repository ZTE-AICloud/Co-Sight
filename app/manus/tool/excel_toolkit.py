# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import os

from camel.toolkits import (
    ExcelToolkit
)

def extract_excel_content(document_path: str):
    excelToolkit = ExcelToolkit()
    result = excelToolkit.extract_excel_content(document_path)
    return result


if __name__ == '__main__':
    result = extract_excel_content("/home/eval_test.xlsx")
    print(result)
