import configparser
import boto3

def getAwsSession(name='external01'):
    config = configparser.ConfigParser()
    config.read(r'C:\Users\user\.aws\credentials')

    if name in config:
        aws_access_key_id = config[name]['aws_access_key_id']
        aws_secret_access_key = config[name]['aws_secret_access_key']
        aws_session_token = config[name]['aws_session_token']
        return boto3.Session(aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)
    else:
        raise ValueError(f"Profile {name} not found in the configuration file.")
    
def listResources():
    session = getAwsSession()
    client = session.client('resourcegroupstaggingapi')
    paginator = client.get_paginator('get_resources')
    resources = []

    for page in paginator.paginate():
        resources.extend(page['ResourceTagMappingList'])

    return resources

def isResourceCreated(tag, resources=None):
    resources = listResources() if resources is None else resources
    
    for resource in resources:
        for resource_tag in resource['Tags']:
            if resource_tag['Key'] == tag['Key'] and resource_tag['Value'] == tag['Value']:
                return True
    return False
