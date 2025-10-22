# encoding = utf-8

import os
import sys
import time
import datetime
import string
import json

from elasticsearch import Elasticsearch, serializer, compat, exceptions
from elasticsearch.helpers import scan

class JSONSerializer4Python(serializer.JSONSerializer):
    def dumps(self, data):
        if isinstance(data, compat.string_types):
            return data
        try:
            return json.dumps(data, default=self.default, ensure_ascii=True)
        except (ValueError, TypeError) as e:
            raise exceptions.SerializationError(data, e)

def isCheckpoint(check_file, _id):
    with open(check_file, 'r') as file:
        log_list = file.read().splitlines()
        return (_id in log_list)

def write2Checkpoint(check_file, _id):
    with open(check_file, 'a') as file:
        file.write(_id + '\n')

def write2Splunk(helper, ew, data, dt_time, opt_cust_source_type, opt_elasticsearch_indice):
    event = helper.new_event(
        data,
        time=dt_time,
        host=None,
        source=opt_elasticsearch_indice,
        sourcetype=opt_cust_source_type,
        done=True,
        unbroken=True
    )
    try:
        ew.write_event(event)
    except Exception as e:
        raise e

def search_index(instance_url, port, user, secret, index_name, datetime_field, from_date, size, ca_certs_path):
    """
    ?????????? ?????? ??????????, ??????????????? ????????? ???????.
    """

    # ??????? ?????? Elasticsearch
    if ca_certs_path:
        client = Elasticsearch(
            hosts=[{
                "host": instance_url,
                "port": port,
                "scheme": "https"
            }],
            verify_certs=False,
            ca_certs=ca_certs_path,
            headers={"Content-Type": "application/json"},
            basic_auth=(user, secret)
        )
    else:
        client = Elasticsearch(
            hosts=[{
                "host": instance_url,
                "port": port,
                "scheme": "https"
            }],
            verify_certs=False,
            headers={"Content-Type": "application/json"},
            basic_auth=(user, secret)
        )

    # ????????? ?????? ?????? ? _source ? query
    search_query = {
        "_source": [
            "@timestamp",
            "dbs-app-version",
            "dbs-client-ip",
            "dbs-customer-id",
            "dbs-customer-type",
            "dbs-device-id",
            "dbs-device-model",
            "dbs-device-type",
            "dbs-email",
            "dbs-http-message-type",
            "dbs-individual-id",
            "dbs-lang",
            "dbs-login-type",
            "dbs-mobile-number",
            "dbs-request-id",
            "dbs-residency",
            "dbs-shield-session-id",
            "dbs-source",
            "dbs-uri",
            "dbs-user-agent",
            "dbs-user-id",
            "dbs-user-role",
            "container.image.name",
            "kubernetes.container.name",
            "kubernetes.deployment.name",
            "kubernetes.namespace",
            "nginx.access.raw_request_line",
            "nginx.access.forwarded_host",
            "nginx.access.upstream_status",
            "nginx.access.remote_ip_list",
            "message",
            "level"
     ],
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            datetime_field: {
                                "gte": "now-" + from_date,
                                "lte": "now"
                            }
                        }
                    }
                ],
                "should": [
                    # ???? 1: (dbs-source ? {bff-mobile, bff-web-business, bff-dbs, bff-web})
                    #         AND (dbs-http-message-type ? {Request, REQUEST})
                    {
                        "bool": {
                            "must": [
                                {
                                    "bool": {
                                        "should": [
                                            {"term": {"dbs-source": "bff-mobile"}},
                                            {"term": {"dbs-source": "bff-web-business"}},
                                            {"term": {"dbs-source": "bff-dbs"}},
                                            {"term": {"dbs-source": "bff-web"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                },
                                {
                                    "bool": {
                                        "should": [
                                            {"term": {"dbs-http-message-type": "Request"}},
                                            {"term": {"dbs-http-message-type": "REQUEST"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                            ]
                        }
                    },
                    # ???? 2: message ???????? ???? ?? ?????? ????
                    {
                        "bool": {
                            "should": [
                                {
                                    "match_phrase": {
                                        "message": "We returned a fake response"
                                    }
                                },
                                {
                                    "match_phrase": {
                                        "message": "Shield webhook received with shieldSignature"
                                    }
                                }
                            ],
                            "minimum_should_match": 1
                        }
                    },
                    # ???? 3: kubernetes.deployment.name = "ms-otp" AND dbs-source = "bff-mobile" AND message = "/v1/internal/otp/sms/send" AND (message ???????? [Request] ??? [Response] ??? [Error])
                    {
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.deployment.name": "ms-otp"}},
                                {"term": {"dbs-source": "bff-mobile"}},
								{"match_phrase": {"message": "/v1/internal/otp/sms/send"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"match_phrase": {"message": "[Request]"}},
                                            {"match_phrase": {"message": "[Response]"}},
                                            {"match_phrase": {"message": "[Error]"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                            ]
                        }
                    },
					{
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.deployment.name": "ms-otp"}},
                                {"term": {"dbs-source": "bff-mobile"}},
								{"match_phrase": {"message": "/v1/internal/otp/sms/verify"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"match_phrase": {"message": "[Request]"}},
                                            {"match_phrase": {"message": "[Response]"}},
                                            {"match_phrase": {"message": "[Error]"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                            ]
                        }
                    },
                    #### processing logs from api gateway
                   {
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.namespace" : "guavapay-cardium-cpg-prod"}},
                                {"term": {"kubernetes.deployment.name": "api-gw-cpg-prod-kong"}},
								{"term": {"kubernetes.container.name": "proxy"}}
                                
                            ]
                        }
                    },
                    # processing logs from nginx
                    {
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.namespace" : "guavapay-cardium-cpg-prod"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"term": {"kubernetes.deployment.name": "nginx-custom-payment-page"}},
                                            {"term": {"kubernetes.deployment.name": "ui-payment-page"}},
                                            {"term": {"kubernetes.deployment.name": "ui-ecwid-app"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                                
                            ]
                        }
                    },
                    #   3 namespace with errors
                    {
                        "bool": {
                            "must": [
                                {
                                    "bool": {
                                        "should": [
                                           {"term": {"kubernetes.namespace" : "guavapay-cardium-cpg-prod"}},
                                           {"term": {"kubernetes.namespace" : "guavapay-ccp-prod"}},
                                           {"term": {"kubernetes.namespace" : "guavapay-cms-prod"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                },
                                {
                                    "bool": {
                                        "should": [
                                            {"term": {"level": "ERROR"}},
                                            {"term": {"level": "WARN"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                                
                            ]
                        }
                    },
                         #  new EPG Access Denied
                     {
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.namespace" : "guavapay-card-gw-prod"}},
                                {"term": {"kubernetes.deployment.name" : "ms-epg"}},
                                {"match_phrase": {"message": "Access denied"}},
                                {"match_phrase": {"message": "EPGClient"}},
                                {"term": {"class": "com.guavapay.epg.logger.CustomFeignLogger"}}
                            ]
                        }
                    },
                    # mLsim balance 
                    {
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.namespace" : "guavapay-common-prod"}},
                                {"term": {"kubernetes.deployment.name" : "ms-sms-lsim"}},
                                {"match_phrase": {"message": "INSUFFICIENT_BALANCE"}}
                            ]
                        }
                    },
                    #Mitto api timeout error

                     {
                        "bool": {
                            "must": [
                                {"term": {"kubernetes.namespace" : "guavapay-common-prod"}},
                                {"term": {"kubernetes.deployment.name" : "ms-sms-mitto"}},
                                {"term": {"level": "ERROR"}},
                                {"match_phrase": {"message": "timeout"}},
                                {"match_phrase": {"message": "POST https://rest.mittoapi.net/sms"}}
                            ]
                        }
                    },





                    # new part guavapay-ccp-prod   ms-acs
                    {
                        "bool": {
                            "must": [

                                 {"term": {"kubernetes.namespace" : "guavapay-ccp-prod"}},
                                 {"term": {"kubernetes.deployment.name": "ms-acs"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"match_phrase": {"message": "SMS delivery"}},
                                            {"match_phrase": {"message": "#send: error:"}},
                                            {"match_phrase": {"message": "OOB delivery"}}
                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                            ]
                        }
                    },
                  # new part guavapay-ccp-prod   ms-3ds
                    {
                        "bool": {
                            "must": [

                                 {"term": {"kubernetes.namespace" : "guavapay-ccp-prod"}},
                                 {"term": {"kubernetes.deployment.name": "ms-3ds"}},
                                {
                                    "bool": {
                                        "should": [
                                            {"match_phrase": {"message": "#execute: Challenge timeout expired, threeDSServerTransId:"}},
                                            {"match_phrase": {"message": "#processAReq:"}},
                                            {"match_phrase": {"message": "#executePreparation: PReq processing error"}},
                                            {"match_phrase": {"message": "#executePreparation: PRes is Error"}},
                                            {"match_phrase": {"message": "#executePreparation: Unexpected error occurred"}},
                                            {"match_phrase": {"message": "#execute: Challenge timeout expired, threeDSServerTransId:"}},
                                            {"match_phrase": {"message": "#execute: RReq after Cres timeout expired, threeDSServerTransId:"}},
                                            {"match_phrase": {"message": "#processAReq: handle a ThreeDSError"}},



                                        ],
                                        "minimum_should_match": 1
                                    }
                                }
                            ]
                        }
                    }

                ],
                "must_not": [
                    {"term": {"dbs-uri": "POST /v1/operation/auth/otp/sms/verify"}},
					{"term": {"dbs-uri": "POST /v1/internal/business-auth/check-mfa"}},
					{"term": {"dbs-uri": "POST /v1/business-auth/check-mfa"}},
					{"term": {"dbs-uri": "POST /v1/operation/auth/authenticator/verify"}},
					{"term": {"dbs-uri": "POST /v1/mobile/public/auth/verify/mobile-number"}},
					{"term": {"dbs-uri": "POST /v1/public/auth/verify/mobile-number"}},
					{"term": {"dbs-uri": "POST /v1/mobile/delete-user-flow/mobile-number/verify-and-delete-account"}},
					{"term": {"dbs-uri": "POST /v1/mobile/public/auth/verify/email"}},
					{"term": {"dbs-uri": "POST /v1/public/auth/verify/email"}},
					{"term": {"dbs-uri": "POST /v1/auth/delete-user-flow/mobile-number/verify-and-delete-account"}},
					{"term": {"dbs-uri": "POST /v1/internal/onboarding-flow/8630b8dd-0cb9-486f-abc6-e9e7cdd5f343/email/verify"}},
                ],
                "minimum_should_match": 1
            }
        }
    }

    # ???????? ?????????????? ?????? ???????? ? ????????? query (??? ??????????????? ????????????)
    scan_results = scan(
        client=client,
        index=index_name,
        query=search_query,
        size=size,
        scroll="1m"
    )

    all_hits = []
    for doc in scan_results:
        all_hits.append(doc)

    return all_hits

def validate_input(helper, definition):
    elasticsearch_instance_url = definition.parameters.get('elasticsearch_instance_url', None)
    port = definition.parameters.get('port', None)
    ca_certs_path = definition.parameters.get('ca_certs_path', None)
    user = definition.parameters.get('user', None)
    secret = definition.parameters.get('secret', None)
    elasticsearch_indice = definition.parameters.get('elasticsearch_indice', None)
    date_field_name = definition.parameters.get('date_field_name', None)
    time_preset = definition.parameters.get('time_preset', None)
    cust_source_type = definition.parameters.get('cust_source_type', None)

def collect_events(helper, ew):
    opt_elasticsearch_instance_url = helper.get_arg('elasticsearch_instance_url')
    opt_port = int(helper.get_arg('port'))
    opt_ca_certs_path = helper.get_arg('ca_certs_path')
    opt_user = helper.get_arg('user')
    opt_secret = helper.get_arg('secret')
    opt_elasticsearch_indice = helper.get_arg('elasticsearch_indice')
    opt_date_field_name = helper.get_arg('date_field_name')
    opt_time_preset = helper.get_arg('time_preset')
    opt_cust_source_type = helper.get_arg('cust_source_type')

    if opt_cust_source_type == '':
        opt_cust_source_type = 'json'

    opt_ca_certs_path = opt_ca_certs_path.strip()
    size = 1000  

    results = search_index(
        opt_elasticsearch_instance_url,
        opt_port,
        opt_user,
        opt_secret,
        opt_elasticsearch_indice,
        opt_date_field_name,
        opt_time_preset,
        size,
        opt_ca_certs_path
    )

    check_file = os.path.join('/', os.path.dirname(os.path.abspath(__file__)), 'checkpoint', 'checkpointElastic')

    for doc in results:
        dt_time = doc['_source'].get(opt_date_field_name, None)
        _id = doc['_id']
        data = json.dumps(doc['_source'], ensure_ascii=False)

        if not isCheckpoint(check_file, _id):
            write2Checkpoint(check_file, _id)
            write2Splunk(helper, ew, data, dt_time, opt_cust_source_type, opt_elasticsearch_indice)
