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

Z_AGENTS_SOP_PROCESS = "z-agents.sop_process"
Z_AGENTS_SOP_TEMPLATE = "z-agents.sop_template"
Z_AGENTS_CLIENT_CALL_ID = "z-agents.client_call_id"
Z_AGENTS_INSTANT_RETURN_FLAG = "z-agents.instant_return_flag"
Z_AGENTS_TASK_ID = "z-agents.task_id"
Z_AGENTS_RESOURCE_ASSISTANT_IP = "z-agents.resource_assistant_ip"
ACTION = "action"
AGENT = "agent"
REGISTER = "register"
UNREGISTER = "unregister"

MICROSERVICE_VERSION = 'v1'
AGENT_MANAGER_MICROSERVICE = 'zagents-manager-service'

QUERY_AGENT_TEMPLATES = '/api/zagents-manager-service/v1/agent/template/getTemplates'
GET_AGENT_TEMPLATE_BY_NAME = '/api/zagents-manager-service/v1/agent/template/getTemplatesByName'
CREATE_AGENT_TEMPLATE = '/api/zagents-manager-service/v1/agent/template/createTemplates'
UPDATE_AGENT_TEMPLATE = '/api/zagents-manager-service/v1/agent/template/updateTemplates'
DELETE_AGENT_TEMPLATE = '/api/zagents-manager-service/v1/agent/template/deleteTemplates'

QUERY_ORGANIZATIONS = '/api/zagents-manager-service/v1/organization/getOrganizations'
GET_ORGANIZATION_BY_NAME = '/api/zagents-manager-service/v1/organization/getOrganizationsByNames'
CREATE_ORGANIZATION = '/api/zagents-manager-service/v1/organization/createOrganizations'
UPDATE_ORGANIZATION = '/api/zagents-manager-service/v1/organization/updateOrganizations'
DELETE_ORGANIZATION = '/api/zagents-manager-service/v1/organization/deleteOrganizations'

CREATE_SKILLS_ORCHESTRATION = '/api/zagents-manager-service/v1/agent/orchestration/create'
# DELETE_SKILLS_ORCHESTRATION = '/api/zagents-manager-service/v1/agent/orchestration/delete'
# UPDATE_SKILLS_ORCHESTRATION = '/api/zagents-manager-service/v1/agent/orchestration/update'
# GET_SKILLS_ORCHESTRATION = '/api/zagents-manager-service/v1/agent/orchestration/getById'

QUERY_SKILLS = '/api/zagents-manager-service/v1/agent/skill/getSkills'
GET_SKILL_BY_NAME = '/api/zagents-manager-service/v1/agent/skill/getSkillsByNames'
CREATE_SKILL = '/api/zagents-manager-service/v1/agent/skill/createSkills'
UPDATE_SKILL = '/api/zagents-manager-service/v1/agent/skill/updateSkills'
DELETE_SKILL = '/api/zagents-manager-service/v1/agent/skill/deleteSkills'

CREATE_AGENT_INSTANCE = '/api/zagents-manager-service/v1/agent/instance/createInstance'
UPDATE_AGENT_INSTANCE = '/api/zagents-manager-service/v1/agent/instance/updateInstance'
DELETE_AGENT_INSTANCE = '/api/zagents-manager-service/v1/agent/instance/deleteInstance'
GET_AGENT_INSTANCE_BY_ID = '/api/zagents-manager-service/v1/agent/instance/getInstancesById'
GET_AGENT_INSTANCE_BY_NAME = '/api/zagents-manager-service/v1/agent/instance/getInstancesByName'

TRACE_REPORT_DATA = "/api/zagents-manager-service/v1/agent/track/reportData"

CREATE_AGENT_INSTANCE_FROM_MANAGE_SERVICE = '/api/{}/v1/instance/createAgentInstance'
UPDATE_AGENT_INSTANCE_FROM_MANAGE_SERVICE = '/api/{}/v1/instance/updateAgentInstance'

APIMAPPPINGSERVICE = 'zae-apimappingservice'
API_MAPPING_SERVICE_URL = '/api/zae-apimappingservice/v1/text2api'

DEFAULT_CREATOR_FACTORY_NAME = 'default_creator_factory_name'
SOPCONTROLLER_ADD_SOPTEMPLATE = 'sopcontroller_add_sop_template'
SOPCONTROLLER_NAME = 'sop_controller_name'
CONTACTS = 'contacts'

PLAN_THEN_ACT = "plan_then_act"
PLAN_USE_RULE = "plan_use_rule"
REACT = "react"

EARLY_STOP = "early stop"

TYPE_REQUEST = "request"
TYPE_ACK = "ack"
TYPE_NOTICE = "notice"
TYPE_STREAM = "stream"

RAG_COMPONENT_SERVICE = 'zae-ragcomponentservice'
RAG_COMPONENT_SERVICE_URL = "/api/zae-ragcomponentservice/v1/query"
