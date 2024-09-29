import json
import os
from botocore.exceptions import ClientError
from tqdm import tqdm


class S3Operations:
    def __init__(self, session, region=None):
        self.s3_client = session.client('s3', region_name=region)
        self.region = region

    def create_bucket(self, bucket_name):
        try:
            if self.region is None:
                self.s3_client.create_bucket(Bucket=bucket_name)
            else:
                location = {'LocationConstraint': self.region}
                self.s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration=location)
            print(f'Bucket {bucket_name} created successfully.')
        except ClientError as e:
            if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
                print(f'Bucket {bucket_name} already exists and is owned by you.')
            elif e.response['Error']['Code'] == 'BucketAlreadyExists':
                raise SystemExit(f'Bucket name {bucket_name} is already taken. Try a different bucket name.')
            else:
                print(f'Error creating bucket: {e}')
                raise

        # self.s3_client.put_public_access_block(
        #     Bucket=bucket_name,
        #     PublicAccessBlockConfiguration={
        #         'BlockPublicAcls': False,
        #         'IgnorePublicAcls': False,
        #         'BlockPublicPolicy': False,
        #         'RestrictPublicBuckets': False
        #     }
        # )
        # print("Disabled block public access")

    def upload_files(self, bucket_name, folder_path):
        mime_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".ico": "image/vnd.microsoft.icon",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".svg": "image/svg+xml"
        }

        all_files = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                all_files.append(os.path.join(root, file))

        with tqdm(total=len(all_files), unit='file') as pbar:
            for file_path in all_files:
                s3_key = os.path.relpath(file_path, folder_path)
                _, ext = os.path.splitext(file_path)
                content_type = mime_types.get(ext.lower(), "application/octet-stream")
                try:
                    pbar.set_description(f'Uploading {s3_key}')
                    self.s3_client.upload_file(file_path, bucket_name, s3_key, ExtraArgs={'ContentType': content_type})
                    pbar.update(1)
                except ClientError as e:
                    print(f'\nError uploading {file_path}: {e}')
                    raise

    def update_bucket_policy(self, bucket_name, cloudfront_distribution_id, account_id):
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
                            "AWS:SourceArn": f"arn:aws:cloudfront::{account_id}:distribution/{cloudfront_distribution_id}"
                        }
                    }
                }
            ]
        }

        updated_policy_json = json.dumps(new_policy)
        self.s3_client.put_bucket_policy(Bucket=bucket_name, Policy=updated_policy_json)
        print(f'Updated bucket policy for {bucket_name}')
