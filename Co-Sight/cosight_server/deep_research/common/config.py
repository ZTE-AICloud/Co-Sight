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

custom_config_data = {
    "proxy": "http://192.168.167.3:8000",
    "portal_port": "5000",
    "search_port": "7788",
    "environment": "dev-mode",
    "plugin_registration_enabled": False,
    "base_api_url": "/api/nae-deep-research/v1",
    "base_chatbot_api_url": "/api/openans-support-chatbot/v1",
    "upload_dir_env": "TRAFFIC_OPS_UPLOAD_DIR",
    "upload_allow_types": [
        "text/plain",
        "image/jpeg",
        "image/png",
        "image/gif",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/json"
    ],
    "db_config": {
        "dbname": "aim_portal",
        "user": "postgres",
        "database_id": "RX6fb2UkbL+QOJHFWQtzDA==",
        "host": "127.0.0.1",
        "port": "5432"
    },
    "entity_extraction": {
        "ip": "10.5.212.120",
        "port": "18088"
    },
    "traffic_ops_token_key": "6cpUFC4HjVq0K7G3mFil1jpfYWlECFp4+ZjXrRKtWtE="
}
