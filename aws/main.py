import os
import boto3
from services.s3.operations import S3Operations
from services.cloudfront.operations import CloudFrontOperations
import config


def setup_static_website(bucket_name, folder_path, cloudfrontfunction_name, ec2_endpoint, region):
    session = boto3.Session(
        aws_access_key_id=os.environ.get('ACCESS_KEY'),
        aws_secret_access_key=os.environ.get('SECRET_KEY'),
        region_name=region
    )

    s3_ops = S3Operations(session, region)
    cloudfront_ops = CloudFrontOperations(session)

    s3_ops.create_bucket(bucket_name)
    s3_ops.upload_files(bucket_name, folder_path)

    distribution_id = cloudfront_ops.setup_cloudfront(bucket_name, region, cloudfrontfunction_name, ec2_endpoint)

    sts_client = session.client('sts')
    account_id = sts_client.get_caller_identity()['Account']
    s3_ops.update_bucket_policy(bucket_name, distribution_id, account_id)


if __name__ == "__main__":
    bucket_name = config.BUCKET_NAME
    folder_path = config.FOLDER_PATH
    cloudfrontfunction_name = config.CLOUDFRONT_FUNCTION_NAME
    ec2_endpoint = config.EC2_ENDPOINT
    region = config.AWS_REGION

    setup_static_website(bucket_name, folder_path, cloudfrontfunction_name, ec2_endpoint, region)
