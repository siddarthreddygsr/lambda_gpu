import boto3
import os
import json
from botocore.exceptions import ClientError



def create_s3_bucket(bucket_name, region=None):
    s3_client = session.client('s3', region_name=region)

    try:
        if region is None:
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            location = {'LocationConstraint': region}
            s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration=location)
        print(f'Bucket {bucket_name} created successfully.')
    except ClientError as e:
        if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
            print(f'Bucket {bucket_name} already exists and is owned by you.')
        elif e.response['Error']['Code'] == 'BucketAlreadyExists':
            raise SystemExit(f'Bucket name {bucket_name} is already taken. Try a different bucket name.')
        else:
            print(f'Error creating bucket: {e}')
            raise
    s3_client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            'BlockPublicAcls': False,
            'IgnorePublicAcls': False,
            'BlockPublicPolicy': False,
            'RestrictPublicBuckets': False
        }
    )
    print("disabled block public access")

def upload_files_to_s3(bucket_name, folder_path):
    s3_client = session.client('s3')
    mime_types = {
        ".html" :  "text/html",
        ".css" : "text/css",
        ".js" : "application/javascript",
        ".ico" : "image/vnd.microsoft.icon",
        ".jpeg" : "image/jpeg",
        ".png" : "image/png",
        ".svg" : "image/svg+xml"
        }
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            s3_key = os.path.relpath(file_path, folder_path)

            _, ext = os.path.splitext(file)
            content_type = mime_types.get(ext, "application/octet-stream")
            try:
                s3_client.upload_file(file_path, bucket_name, s3_key, ExtraArgs={'ContentType': content_type})
                print(f'Uploaded {file_path} to s3://{bucket_name}/{s3_key} with content type {content_type}')
            except ClientError as e:
                print(f'Error uploading {file_path}: {e}')
                raise

def create_cloudfront_distribution(bucket_name):
    cloudfront_client = session.client('cloudfront')
    origin_id = f'S3-{bucket_name}'
    oac_list = cloudfront_client.list_origin_access_controls()
    oac_present = any(oac['Name'] == 'MyOriginAccessControl' for oac in oac_list['OriginAccessControlList']['Items'])

    if not oac_present:
        response = cloudfront_client.create_origin_access_control(
            OriginAccessControlConfig={
                'Name': 'ChatFEOriginAccessControl',
                'Description': 'Access control for my S3 bucket',
                'SigningProtocol': 'sigv4',
                'SigningBehavior': 'always',
                'OriginAccessControlOriginType': 's3'
            }
        )
        origin_access_control_id = response['OriginAccessControl']['Id']
    else:
        origin_access_control_id = next((oac['Id'] for oac in oac_list['OriginAccessControlList']['Items'] if oac['Name'] == 'MyOriginAccessControl'), None)

    distributions = cloudfront_client.list_distributions()
    distribution_exists = False
    distribution_id = ""
    if distributions['DistributionList']['Quantity'] > 0:
        for distribution in distributions['DistributionList']['Items']:
            if distribution['Origins']['Items'][0]['DomainName'] == f"{bucket_name}.s3.{region}.amazonaws.com":
                print("Distribution already exists.")
                distribution_exists = True
                distribution_id = distribution['Id']
                break
    if not distribution_exists:
        try:
            response = cloudfront_client.create_distribution(
                DistributionConfig={
                    'CallerReference': str(hash(bucket_name)),
                    "DefaultRootObject": "index.html",
                    'Origins': {
                        'Quantity': 1,
                        'Items': [
                            {
                                'Id': origin_id,
                                'DomainName': f'{bucket_name}.s3.{region}.amazonaws.com',
                                'S3OriginConfig': {
                                    'OriginAccessIdentity': ''
                                },
                                'OriginAccessControlId': origin_access_control_id
                            }
                        ]
                    },
                    'DefaultCacheBehavior': {
                        'TargetOriginId': origin_id,
                        'ViewerProtocolPolicy': 'redirect-to-https',
                        'AllowedMethods': {
                            'Quantity': 2,
                            'Items': ['HEAD', 'GET'],
                            'CachedMethods': {
                                'Quantity': 2,
                                'Items': ['HEAD', 'GET']
                            }
                        },
                        'ForwardedValues': {
                            'QueryString': False,
                            'Cookies': {
                                'Forward': 'none'
                            }
                        },
                        'MinTTL': 0,
                        'DefaultTTL': 86400,
                        'MaxTTL': 31536000
                    },
                    'Comment': 'CloudFront distribution for static website',
                    'Enabled': True
                }
            )
            distribution_id = response['Distribution']['Id']
            print(f'CloudFront distribution created with ID: {distribution_id}')
        except ClientError as e:
            print(f'Error creating CloudFront distribution: {e}')
            raise

    response = cloudfront_client.get_distribution_config(Id=distribution_id)
    distribution_config = response['DistributionConfig']
    distribution_config['Origins']['Items'][0]['OriginAccessControlId'] = origin_access_control_id
    etag = response['ETag']
    updated_response = cloudfront_client.update_distribution(DistributionConfig=distribution_config,Id=distribution_id, IfMatch=etag)
    s3_client = session.client('s3')
    sts_client = session.client('sts')
    response = sts_client.get_caller_identity()
    account_id = response['Account']
    try:
        response = s3_client.get_bucket_policy(Bucket=bucket_name)
        current_policy = json.loads(response['Policy'])
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucketPolicy':
            # If no policy exists, start with an empty policy structure
            print("no existing policy")

    new_policy = {
        "Version": "2008-10-17",
        "Id": "PolicyForCloudFrontPrivateContent",
        "Statement": [
            {
                "Sid": "AllowCloudFrontServicePrincipal",
                "Effect": "Allow",
                "Principal": {
                    "Service": "cloudfront.amazonaws.com"
                },
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceArn": f"arn:aws:cloudfront::{account_id}:distribution/{distribution_id}"
                    }
                }
            }
        ]
    }

    updated_policy_json = json.dumps(new_policy)
    
    s3_client.put_bucket_policy(Bucket=bucket_name, Policy=updated_policy_json)
    print(f'Updated bucket policy for {bucket_name}')
            

def setup_static_website(bucket_name, folder_path, region=None):
    create_s3_bucket(bucket_name, region)
    upload_files_to_s3(bucket_name, folder_path)
    create_cloudfront_distribution(bucket_name)

if __name__ == "__main__":
    bucket_name = 'dvdvc'
    folder_path = '/Users/siddarthreddy/workspace/pub_01/poc01/frontend'
    region = 'us-west-2'
    access_key = os.environ.get('ACCESS_KEY')
    secret_key = os.environ.get('SECRET_KEY')
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    setup_static_website(bucket_name, folder_path, region)