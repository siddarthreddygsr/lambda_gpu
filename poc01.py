from typing import cast
import boto3
import os
import json
import lib as lib

def createS3(tag, oaiId):
    # if (lib.isResourceCreated(tag, resources)):
    #     return
    
    # Initialize a session using Amazon S3 and CloudFront
    s3 = session.client('s3')

    # Define the local directory
    local_directory = r'/Users/siddarthreddy/workspace/pub_01/poc01/frontend'

    # Create the S3 bucket
    s3.create_bucket(Bucket=tag)

    # Add tags to the S3 bucket
    s3.put_bucket_tagging(
        Bucket=tag,
        Tagging={
            'TagSet': [
                {
                    'Key': 'Name',
                    'Value': tag
                }
            ]
        }
    )

    # Upload files from the local directory to the S3 bucket under the 'www' folder
    for root, dirs, files in os.walk(local_directory):
        for file in files:
            file_path = os.path.join(root, file)
            s3_key = os.path.relpath(file_path, local_directory)
            s3.upload_file(file_path, tag, f'www/{s3_key}')

    # Define the bucket policy to grant public read access
    # bucket_policy = {
    #     "Version": "2012-10-17",
    #     "Statement": [
    #         {
    #             "Effect": "Allow",
    #             "Principal": "*",
    #             "Action": "s3:GetObject",
    #             "Resource": f"arn:aws:s3:::{bucket_name}/www/*"
    #         }
    #     ]
    # }
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::cloudfront:user/CloudFront Origin Access Identity {oaiId}"
                },
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{tag}/*"
            }
        ]
    }

    # Convert the policy to a JSON string
    bucket_policy_json = json.dumps(bucket_policy)

    # Apply the bucket policy
    s3.put_bucket_policy(Bucket=tag, Policy=bucket_policy_json)

def createCloudFrontOAI(tag, bucketName):
    # if (lib.isResourceCreated(tag, resources)):
    #     return
    
    oai_response = cloudfront.create_cloud_front_origin_access_identity(
        CloudFrontOriginAccessIdentityConfig={
                'CallerReference': str(hash(bucketName)),
                'Comment': tag
            }
        )
    id = oai_response['CloudFrontOriginAccessIdentity']['Id']

    cloudfront.tag_resource(
        Resource=id,
        Tags={
            'Items':[
                {
                    'Key': 'Name',
                    'Value': tag
                }
            ]
        }
    )
    return id

def createCloudFront(tag, bucketName, oaiId):
    # if (lib.isResourceCreated(tag, resources)):
    #     return
    
    # Create a CloudFront distribution
    response = cloudfront.create_distribution(DistributionConfig={
        'CallerReference': str(hash(bucketName)),
        'Comment': tag,
        'Enabled': True,
        'Origins': {
            'Quantity': 1,
            'Items': [
                {
                    'Id': f'{tag}-s3-origin',
                    'DomainName': f'{bucketName}.s3.amazonaws.com',
                    'S3OriginConfig': {
                        'OriginAccessIdentity': f'origin-access-identity/cloudfront/{oaiId}'
                    }
                }
            ]
        },
        'DefaultCacheBehavior': {
            'TargetOriginId': f'{tag}-s3-origin',
            'ViewerProtocolPolicy': 'redirect-to-https',
            'AllowedMethods': {
                'Quantity': 2,
                'Items': ['GET', 'HEAD'],
                'CachedMethods': {
                    'Quantity': 2,
                    'Items': ['GET', 'HEAD']
                }
            },
            'Compress': True,
            'ForwardedValues': {
                'QueryString': False,
                'Cookies': {
                    'Forward': 'none'
                }
            },
            # 'MinTTL': 0,
            # 'DefaultTTL': 86400,
            # 'MaxTTL': 31536000
        },
        'PriceClass': 'PriceClass_100',
        'ViewerCertificate': {
            'CloudFrontDefaultCertificate': True
        },
        'Restrictions': {
            'GeoRestriction': {
                'RestrictionType': 'none',
                'Quantity': 0
            }
        },
        'HttpVersion': 'http2',
        'IsIPV6Enabled': True
    })

    # Add tags to the CloudFront distribution
    cloudfront_tagging = cloudfront.tag_resource(
        Resource=response['Distribution']['ARN'],
        Tags={
            'Items': [
                {
                    'Key': 'Name',
                    'Value': tag
                }
            ]
        }
    )

    return response['Distribution']['Id']

def createCloudFrontFunction(tag, cloudfrontdistrId):
    # if (lib.isResourceCreated(tag, resources)):
    #     return
    
    # Function code to add an HTTP-only cookie
    function_code = """
    function handler(event) {
    // Check if the request method is GET and the path is '/'
    if (event.request.method === "GET" && event.request.uri === "/") {
        // Get the current timestamp in milliseconds
        const time = Date.now();

        // Text to encrypt
        let text = "pr!ma24$";
        let encryptedText = "";
        for (let i = 0; i < text.length; i++) {
        encryptedText += String.fromCharCode(
            text.charCodeAt(i) ^ (time & 0xffff)
        );
        }

        // Create the HTTP-only cookie value
        var httponlyCookie = `id=${encryptedText}; HttpOnly`;

        // Set the HTTP-only cookie
        event.response.headers["set-cookie"] = [
        { key: "Set-Cookie", value: httponlyCookie },
        ];
    }

    return event.response;
    }
    """

    # Create the CloudFront function
    response = cloudfront.create_function(
        Name=tag,
        FunctionConfig={
            'Comment': 'Function to add an HTTP-only cookie with an ID',
            'Runtime': 'cloudfront-js-1.0'
        },
        FunctionCode=function_code
    )

    # Publish the function
    publish_response = cloudfront.publish_function(
        Name=tag,
        IfMatch=response['ETag']
    )

    function_arn = publish_response['FunctionSummary']['FunctionARN']

    # Attach the function to a CloudFront distribution

    # Get the current distribution configuration
    distribution_config = cloudfront.get_distribution_config(Id=cloudfrontdistrId)
    etag = distribution_config['ETag']
    config = distribution_config['DistributionConfig']

    # Update the default cache behavior to include the function association
    config['DefaultCacheBehavior']['FunctionAssociations'] = {
        'Quantity': 1,
        'Items': [
            {
                'FunctionARN': function_arn,
                'EventType': 'viewer-response'
            }
        ]
    }

    # Update the distribution with the new configurationd
    update_response = cloudfront.update_distribution(
        Id=cloudfrontdistrId,
        IfMatch=etag,
        DistributionConfig=config
    )

if __name__ == "__main__":
    # resources = lib.listResources()
    bucketname = 'poc01-s3-bucket'
    access_key = ""
    secret_key = ""
    session = boto3.Session(
           aws_access_key_id=access_key,
           aws_secret_access_key=secret_key
       )
    cloudfront = session.client('cloudfront')
    oaiId = createCloudFrontOAI('poc01-oai', bucketname)

    createS3(bucketname, oaiId)
    createCloudFront('poc01-cloudfrontdistribution', bucketname, oaiId)
    createCloudFrontFunction('poc01-cloudfrontfunction-01')
