from botocore.exceptions import ClientError


class CloudFrontOperations:
    def __init__(self, session):
        self.cloudfront_client = session.client('cloudfront')
        self.sts_client = session.client('sts')

    def get_or_create_origin_access_control(self):
        oac_name = 'S3OriginAccessControl'
        oac_id = self.get_existing_oac(oac_name)

        if not oac_id:
            oac_id = self.create_origin_access_control(oac_name)

        return oac_id

    def get_existing_oac(self, oac_name):
        oac_list = self.cloudfront_client.list_origin_access_controls()
        for oac in oac_list['OriginAccessControlList']['Items']:
            if oac['Name'] == oac_name:
                return oac['Id']
        return None

    def create_origin_access_control(self, oac_name):
        response = self.cloudfront_client.create_origin_access_control(
            OriginAccessControlConfig={
                'Name': oac_name,
                'Description': 'Access control for my S3 bucket',
                'SigningProtocol': 'sigv4',
                'SigningBehavior': 'always',
                'OriginAccessControlOriginType': 's3'
            }
        )
        return response['OriginAccessControl']['Id']

    def get_existing_distribution(self, bucket_name, region):
        distributions = self.cloudfront_client.list_distributions()
        if distributions['DistributionList']['Quantity'] > 0:
            for distribution in distributions['DistributionList']['Items']:
                if distribution['Origins']['Items'][0]['DomainName'] == f"{bucket_name}.s3.{region}.amazonaws.com":
                    return distribution['Id'], distribution['DomainName']
        return None, None

    def create_distribution(self, bucket_name, region, origin_access_control_id):
        origin_id = f'S3-{bucket_name}'
        try:
            response = self.cloudfront_client.create_distribution(
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
            return response['Distribution']['Id']
        except ClientError as e:
            print(f'Error creating CloudFront distribution: {e}')
            raise

    def update_distribution_oac(self, distribution_id, origin_access_control_id):
        response = self.cloudfront_client.get_distribution_config(Id=distribution_id)
        distribution_config = response['DistributionConfig']
        distribution_config['Origins']['Items'][0]['OriginAccessControlId'] = origin_access_control_id
        etag = response['ETag']
        self.cloudfront_client.update_distribution(DistributionConfig=distribution_config, Id=distribution_id, IfMatch=etag)

    def create_or_update_cloudfront_function(self, cloudfrontfunction_name, ec2_endpoint):
        function_template_path = f'resources/{cloudfrontfunction_name}.js'

        with open(function_template_path, 'r') as file:
            template_function = file.read()

        function_code = template_function.replace('<EC2_ENDPOINT>', ec2_endpoint)

        list_response = self.cloudfront_client.list_functions()
        function_exists = any(func['Name'] == cloudfrontfunction_name for func in list_response['FunctionList']['Items'])

        if function_exists:
            print(f"Function '{cloudfrontfunction_name}' already exists. Updating...")

            existing_function = self.cloudfront_client.describe_function(Name=cloudfrontfunction_name)

            update_response = self.cloudfront_client.update_function(
                Name=cloudfrontfunction_name,
                IfMatch=existing_function['ETag'],
                FunctionConfig={
                    'Comment': f'Updated function for {cloudfrontfunction_name}',
                    'Runtime': 'cloudfront-js-1.0'
                },
                FunctionCode=function_code
            )
            e_tag = update_response['ETag']
        else:
            print(f"Function '{cloudfrontfunction_name}' does not exist. Creating...")
            create_response = self.cloudfront_client.create_function(
                Name=cloudfrontfunction_name,
                FunctionConfig={
                    'Comment': f'Function for {cloudfrontfunction_name}',
                    'Runtime': 'cloudfront-js-1.0'
                },
                FunctionCode=function_code
            )
            e_tag = create_response['ETag']

        self.cloudfront_client.publish_function(
            Name=cloudfrontfunction_name,
            IfMatch=e_tag
        )
        print(f"Function '{cloudfrontfunction_name}' has been published:")

        return e_tag

    def associate_function_with_distribution(self, distribution_id, function_name):
        response = self.cloudfront_client.get_distribution_config(Id=distribution_id)
        cache_behaviour_configs = response['DistributionConfig']['CacheBehaviors']['Items']
        if cache_behaviour_configs:
            for config in cache_behaviour_configs:
                if config['FunctionAssociations'] and config['FunctionAssociations']['Quantity'] > 0:
                    for function in config['FunctionAssociations']['Items']:
                        if function_name in function['FunctionARN']:
                            return

        distribution_config = response['DistributionConfig']
        etag = response['ETag']
        new_behavior = {
            'PathPattern': '*',
            'TargetOriginId': distribution_config['DefaultCacheBehavior']['TargetOriginId'],
            'ViewerProtocolPolicy': 'redirect-to-https',
            'AllowedMethods': {
                'Quantity': 7,
                'Items': ['HEAD', 'DELETE', 'POST', 'GET', 'OPTIONS', 'PUT', 'PATCH'],
                'CachedMethods': {
                    'Quantity': 2,
                    'Items': ['HEAD', 'GET']
                }
            },
            'MinTTL': 0,
            'DefaultTTL': 0,
            'MaxTTL': 0,
            'Compress': False,
            'SmoothStreaming': False,
            'ForwardedValues': {
                'QueryString': True,
                'Cookies': {'Forward': 'all'},
                'Headers': {
                    'Quantity': 3,
                    'Items': ['Sec-WebSocket-Key', 'Sec-WebSocket-Version', 'Sec-WebSocket-Protocol']
                },
                'QueryStringCacheKeys': {
                    'Quantity': 0,
                },
            },
            "LambdaFunctionAssociations": {
                "Quantity": 0
            },
            'FieldLevelEncryptionId': "",
            'FunctionAssociations': {
                'Quantity': 1,
                'Items': [
                    {
                        'FunctionARN': f"arn:aws:cloudfront::{self.sts_client.get_caller_identity()['Account']}:function/{function_name}",
                        'EventType': 'viewer-request'
                    }
                ]
            }
        }

        if 'CacheBehaviors' not in distribution_config:
            distribution_config['CacheBehaviors'] = {'Quantity': 0, 'Items': []}
        if 'Items' not in distribution_config['CacheBehaviors']:
            distribution_config['CacheBehaviors']['Items'] = []
        distribution_config['CacheBehaviors']['Items'].append(new_behavior)
        distribution_config['CacheBehaviors']['Quantity'] += 1

        response = self.cloudfront_client.update_distribution(
            DistributionConfig=distribution_config,
            Id=distribution_id,
            IfMatch=etag
        )

        print(f"CloudFront function '{function_name}' has been associated with distribution '{distribution_id}' for redirecting requests to EC2.")

    def setup_cloudfront(self, bucket_name, region, cloudfrontfunction_name, ec2_endpoint):
        origin_access_control_id = self.get_or_create_origin_access_control()

        distribution_id, domain = self.get_existing_distribution(bucket_name, region)
        if not distribution_id:
            distribution_id = self.create_distribution(bucket_name, region, origin_access_control_id)
            print(f'CloudFront distribution created with ID: {distribution_id}')
        else:
            print(f'Existing CloudFront distribution found with ID: {distribution_id}, hosted at {domain}')
            self.update_distribution_oac(distribution_id, origin_access_control_id)
            print(f'Updated existing distribution with new Origin Access Control {origin_access_control_id}')

        self.create_or_update_cloudfront_function(cloudfrontfunction_name, ec2_endpoint)
        self.associate_function_with_distribution(distribution_id, cloudfrontfunction_name)

        return distribution_id
