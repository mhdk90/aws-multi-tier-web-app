import boto3
import getpass
from botocore.exceptions import ClientError


# ============================================================
# AWS Multi-Tier Web Application Deployment using Python Boto3
# ============================================================
# This script creates:
# - Custom VPC
# - Public and private subnets
# - Internet Gateway
# - NAT Gateway
# - Route tables
# - EC2 instances in private subnets
# - Application Load Balancer
# - Target Group
# - Auto Scaling Group
# - Multi-AZ RDS MySQL database
#
# IMPORTANT:
# Do NOT hardcode AWS credentials, passwords, or private key files.
# The database password is requested securely at runtime.
# ============================================================


REGION = "us-east-1"
VPC_CIDR = "10.0.0.0/16"

PUBLIC_SUBNET_CIDRS = ["10.0.10.0/24", "10.0.20.0/24"]
PRIVATE_SUBNET_CIDRS = ["10.0.100.0/24", "10.0.200.0/24"]
AVAILABILITY_ZONES = ["us-east-1a", "us-east-1b"]

AMI_ID = "ami-0889a44b331db0194"
INSTANCE_TYPE = "t2.micro"

DB_USERNAME = "admin"


def safe_add_ingress_rule(ec2_client, group_id, ip_permissions):
    try:
        ec2_client.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=ip_permissions
        )
    except ClientError as error:
        if "InvalidPermission.Duplicate" in str(error):
            print("Ingress rule already exists. Skipping.")
        else:
            raise


def safe_add_egress_rule(ec2_client, group_id, ip_permissions):
    try:
        ec2_client.authorize_security_group_egress(
            GroupId=group_id,
            IpPermissions=ip_permissions
        )
    except ClientError as error:
        if "InvalidPermission.Duplicate" in str(error):
            print("Egress rule already exists. Skipping.")
        else:
            print(f"Egress rule could not be added: {error}")


def main():
    aws_profile = input("Enter your AWS CLI profile name: ")
    key_name = input("Enter your existing EC2 key pair name: ")
    db_password = getpass.getpass("Enter a secure RDS database password: ")

    session = boto3.session.Session(profile_name=aws_profile)

    ec2_client = session.client("ec2", region_name=REGION)
    ec2_resource = session.resource("ec2", region_name=REGION)
    elb_client = session.client("elbv2", region_name=REGION)
    autoscaling_client = session.client("autoscaling", region_name=REGION)
    rds_client = session.client("rds", region_name=REGION)

    # 1. Create VPC
    vpc_response = ec2_client.create_vpc(CidrBlock=VPC_CIDR)
    vpc_id = vpc_response["Vpc"]["VpcId"]

    ec2_client.create_tags(
        Resources=[vpc_id],
        Tags=[{"Key": "Name", "Value": "MultiTierVPC"}]
    )

    print(f"VPC created: {vpc_id}")

    # 2. Create public subnets
    public_subnet_ids = []

    for cidr, az in zip(PUBLIC_SUBNET_CIDRS, AVAILABILITY_ZONES):
        subnet_response = ec2_client.create_subnet(
            CidrBlock=cidr,
            VpcId=vpc_id,
            AvailabilityZone=az
        )

        subnet_id = subnet_response["Subnet"]["SubnetId"]
        public_subnet_ids.append(subnet_id)

        ec2_client.create_tags(
            Resources=[subnet_id],
            Tags=[{"Key": "Name", "Value": f"PublicSubnet-{az}"}]
        )

    print(f"Public subnets created: {public_subnet_ids}")

    # 3. Enable auto-assign public IP for public subnets
    for subnet_id in public_subnet_ids:
        ec2_client.modify_subnet_attribute(
            SubnetId=subnet_id,
            MapPublicIpOnLaunch={"Value": True}
        )

    print("Auto-assign public IP enabled for public subnets.")

    # 4. Create private subnets
    private_subnet_ids = []

    for cidr, az in zip(PRIVATE_SUBNET_CIDRS, AVAILABILITY_ZONES):
        subnet_response = ec2_client.create_subnet(
            CidrBlock=cidr,
            VpcId=vpc_id,
            AvailabilityZone=az
        )

        subnet_id = subnet_response["Subnet"]["SubnetId"]
        private_subnet_ids.append(subnet_id)

        ec2_client.create_tags(
            Resources=[subnet_id],
            Tags=[{"Key": "Name", "Value": f"PrivateSubnet-{az}"}]
        )

    print(f"Private subnets created: {private_subnet_ids}")

    # 5. Create Internet Gateway
    igw_response = ec2_client.create_internet_gateway()
    internet_gateway_id = igw_response["InternetGateway"]["InternetGatewayId"]

    ec2_client.create_tags(
        Resources=[internet_gateway_id],
        Tags=[{"Key": "Name", "Value": "MultiTierIGW"}]
    )

    print(f"Internet Gateway created: {internet_gateway_id}")

    # 6. Attach Internet Gateway to VPC
    ec2_client.attach_internet_gateway(
        InternetGatewayId=internet_gateway_id,
        VpcId=vpc_id
    )

    print("Internet Gateway attached to VPC.")

    # 7. Create public route table
    public_rt_response = ec2_client.create_route_table(VpcId=vpc_id)
    public_route_table_id = public_rt_response["RouteTable"]["RouteTableId"]

    ec2_client.create_tags(
        Resources=[public_route_table_id],
        Tags=[{"Key": "Name", "Value": "PublicRouteTable"}]
    )

    print(f"Public route table created: {public_route_table_id}")

    # 8. Associate public subnets with public route table
    for subnet_id in public_subnet_ids:
        ec2_client.associate_route_table(
            RouteTableId=public_route_table_id,
            SubnetId=subnet_id
        )

    print("Public subnets associated with public route table.")

    # 9. Add default route to Internet Gateway
    public_route_table = ec2_resource.RouteTable(public_route_table_id)

    public_route_table.create_route(
        DestinationCidrBlock="0.0.0.0/0",
        GatewayId=internet_gateway_id
    )

    print("Public route added: 0.0.0.0/0 -> Internet Gateway")

    # 10. Create NAT Gateway
    eip_response = ec2_client.allocate_address(Domain="vpc")

    nat_response = ec2_client.create_nat_gateway(
        AllocationId=eip_response["AllocationId"],
        SubnetId=public_subnet_ids[0]
    )

    nat_gateway_id = nat_response["NatGateway"]["NatGatewayId"]

    print(f"NAT Gateway creation started: {nat_gateway_id}")

    # 11. Create private route table
    private_rt_response = ec2_client.create_route_table(VpcId=vpc_id)
    private_route_table_id = private_rt_response["RouteTable"]["RouteTableId"]

    ec2_client.create_tags(
        Resources=[private_route_table_id],
        Tags=[{"Key": "Name", "Value": "PrivateRouteTable"}]
    )

    print(f"Private route table created: {private_route_table_id}")

    # 12. Associate private subnets with private route table
    for subnet_id in private_subnet_ids:
        ec2_client.associate_route_table(
            RouteTableId=private_route_table_id,
            SubnetId=subnet_id
        )

    print("Private subnets associated with private route table.")

    # 13. Wait for NAT Gateway
    print("Waiting for NAT Gateway to become available...")
    nat_waiter = ec2_client.get_waiter("nat_gateway_available")
    nat_waiter.wait(NatGatewayIds=[nat_gateway_id])

    print("NAT Gateway is available.")

    # 14. Add default route to NAT Gateway
    private_route_table = ec2_resource.RouteTable(private_route_table_id)

    private_route_table.create_route(
        DestinationCidrBlock="0.0.0.0/0",
        NatGatewayId=nat_gateway_id
    )

    print("Private route added: 0.0.0.0/0 -> NAT Gateway")

    # 15. Create security group for EC2 instances
    web_sg_response = ec2_client.create_security_group(
        Description="Security group for private web EC2 instances",
        GroupName="WebSG",
        VpcId=vpc_id
    )

    web_sg_id = web_sg_response["GroupId"]

    ec2_client.create_tags(
        Resources=[web_sg_id],
        Tags=[{"Key": "Name", "Value": "WebSG"}]
    )

    print(f"Web security group created: {web_sg_id}")

    # 16. Add ingress rules for EC2 instances
    safe_add_ingress_rule(
        ec2_client,
        web_sg_id,
        [
            {
                "FromPort": 22,
                "ToPort": 22,
                "IpProtocol": "tcp",
                "IpRanges": [
                    {
                        "CidrIp": "0.0.0.0/0",
                        "Description": "SSH access - restrict in production"
                    }
                ]
            },
            {
                "FromPort": 80,
                "ToPort": 80,
                "IpProtocol": "tcp",
                "IpRanges": [
                    {
                        "CidrIp": "0.0.0.0/0",
                        "Description": "HTTP access"
                    }
                ]
            },
            {
                "FromPort": 443,
                "ToPort": 443,
                "IpProtocol": "tcp",
                "IpRanges": [
                    {
                        "CidrIp": "0.0.0.0/0",
                        "Description": "HTTPS access"
                    }
                ]
            }
        ]
    )

    print("Ingress rules added to WebSG.")

    # 17. Add egress rule for EC2 instances
    safe_add_egress_rule(
        ec2_client,
        web_sg_id,
        [
            {
                "IpProtocol": "-1",
                "IpRanges": [
                    {
                        "CidrIp": "0.0.0.0/0",
                        "Description": "Allow outbound traffic"
                    }
                ]
            }
        ]
    )

    print("Egress rule checked for WebSG.")

    # 18. Launch EC2 instances in private subnets
    user_data_script_1 = """#!/bin/bash
yum update -y
yum install httpd -y
systemctl start httpd
systemctl enable httpd
echo "This is server 1 in AWS Region US-EAST-1A" > /var/www/html/index.html
"""

    user_data_script_2 = """#!/bin/bash
yum update -y
yum install httpd -y
systemctl start httpd
systemctl enable httpd
echo "This is server 2 in AWS Region US-EAST-1B" > /var/www/html/index.html
"""

    user_data_scripts = [user_data_script_1, user_data_script_2]
    instance_ids = []

    for subnet_id, user_data_script in zip(private_subnet_ids, user_data_scripts):
        instance_response = ec2_client.run_instances(
            ImageId=AMI_ID,
            InstanceType=INSTANCE_TYPE,
            KeyName=key_name,
            MinCount=1,
            MaxCount=1,
            SubnetId=subnet_id,
            UserData=user_data_script,
            BlockDeviceMappings=[
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "Encrypted": True,
                        "VolumeSize": 8,
                        "VolumeType": "gp2"
                    }
                }
            ],
            SecurityGroupIds=[web_sg_id]
        )

        instance_id = instance_response["Instances"][0]["InstanceId"]
        instance_ids.append(instance_id)

    # 19. Wait until instances are running
    print("Waiting for EC2 instances to run...")
    instance_waiter = ec2_client.get_waiter("instance_running")
    instance_waiter.wait(InstanceIds=instance_ids)

    print(f"EC2 instances are running: {instance_ids}")

    # 21. Create target group
    target_group_response = elb_client.create_target_group(
        Name="webTG",
        Protocol="HTTP",
        Port=80,
        VpcId=vpc_id,
        HealthCheckProtocol="HTTP",
        HealthCheckPort="80",
        HealthCheckEnabled=True
    )

    target_group_arn = target_group_response["TargetGroups"][0]["TargetGroupArn"]

    print(f"Target Group created: {target_group_arn}")

    # 22. Register EC2 instances to target group
    elb_client.register_targets(
        TargetGroupArn=target_group_arn,
        Targets=[
            {"Id": instance_id, "Port": 80}
            for instance_id in instance_ids
        ]
    )

    print("EC2 instances registered with Target Group.")

    # 23A. Create ALB security group
    alb_sg_response = ec2_client.create_security_group(
        Description="Security group for Application Load Balancer",
        GroupName="ALBSG",
        VpcId=vpc_id
    )

    alb_sg_id = alb_sg_response["GroupId"]

    ec2_client.create_tags(
        Resources=[alb_sg_id],
        Tags=[{"Key": "Name", "Value": "ALBSG"}]
    )

    print(f"ALB security group created: {alb_sg_id}")

    # 23B. Allow HTTP inbound to ALB
    safe_add_ingress_rule(
        ec2_client,
        alb_sg_id,
        [
            {
                "FromPort": 80,
                "ToPort": 80,
                "IpProtocol": "tcp",
                "IpRanges": [
                    {
                        "CidrIp": "0.0.0.0/0",
                        "Description": "Allow HTTP from internet"
                    }
                ]
            }
        ]
    )

    print("Ingress rule added to ALBSG.")

    # 23C. Allow ALB to send HTTP traffic to WebSG
    safe_add_egress_rule(
        ec2_client,
        alb_sg_id,
        [
            {
                "FromPort": 80,
                "ToPort": 80,
                "IpProtocol": "tcp",
                "UserIdGroupPairs": [
                    {
                        "GroupId": web_sg_id,
                        "Description": "Allow HTTP to WebSG"
                    }
                ]
            }
        ]
    )

    print("Egress rule checked for ALBSG.")

    # 23D. Create Application Load Balancer
    load_balancer_response = elb_client.create_load_balancer(
        Name="MultiTierLoadBalancer",
        Subnets=public_subnet_ids,
        SecurityGroups=[alb_sg_id],
        Scheme="internet-facing",
        Type="application",
        IpAddressType="ipv4"
    )

    load_balancer_arn = load_balancer_response["LoadBalancers"][0]["LoadBalancerArn"]
    load_balancer_dns = load_balancer_response["LoadBalancers"][0]["DNSName"]

    # 23E. Wait for ALB
    print("Waiting for Application Load Balancer to become available...")
    alb_waiter = elb_client.get_waiter("load_balancer_available")
    alb_waiter.wait(LoadBalancerArns=[load_balancer_arn])

    print(f"Application Load Balancer is available: {load_balancer_dns}")

    # 24. Create listener
    elb_client.create_listener(
        LoadBalancerArn=load_balancer_arn,
        Protocol="HTTP",
        Port=80,
        DefaultActions=[
            {
                "Type": "forward",
                "TargetGroupArn": target_group_arn
            }
        ]
    )

    print("ALB listener created.")

    # 25A. Create launch configuration
    autoscaling_client.create_launch_configuration(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        LaunchConfigurationName="multi-tier-launch-config",
        SecurityGroups=[web_sg_id],
        KeyName=key_name
    )

    print("Launch Configuration created.")

    # 25B. Create Auto Scaling Group
    autoscaling_client.create_auto_scaling_group(
        AutoScalingGroupName="MultiTierAutoScalingGroup",
        LaunchConfigurationName="multi-tier-launch-config",
        MinSize=1,
        MaxSize=3,
        DesiredCapacity=1,
        TargetGroupARNs=[target_group_arn],
        VPCZoneIdentifier=",".join(private_subnet_ids)
    )

    asg_response = autoscaling_client.describe_auto_scaling_groups(
        AutoScalingGroupNames=["MultiTierAutoScalingGroup"]
    )

    asg_arn = asg_response["AutoScalingGroups"][0]["AutoScalingGroupARN"]

    print(f"Auto Scaling Group created: {asg_arn}")

    # 26A. Create DB security group
    db_sg_response = ec2_client.create_security_group(
        Description="Security group for RDS database",
        GroupName="DBSG",
        VpcId=vpc_id
    )

    db_sg_id = db_sg_response["GroupId"]

    ec2_client.create_tags(
        Resources=[db_sg_id],
        Tags=[{"Key": "Name", "Value": "DBSG"}]
    )

    print(f"Database security group created: {db_sg_id}")

    # 26B. Allow MySQL access only from WebSG
    safe_add_ingress_rule(
        ec2_client,
        db_sg_id,
        [
            {
                "FromPort": 3306,
                "ToPort": 3306,
                "IpProtocol": "tcp",
                "UserIdGroupPairs": [
                    {
                        "GroupId": web_sg_id,
                        "Description": "Allow MySQL access from WebSG only"
                    }
                ]
            }
        ]
    )

    print("Database security group configured.")

    # 26C. Create DB subnet group
    rds_client.create_db_subnet_group(
        DBSubnetGroupDescription="RDS subnet group for private subnets",
        DBSubnetGroupName="multi-tier-rds-subnet-group",
        SubnetIds=private_subnet_ids
    )

    print("RDS DB Subnet Group created.")

    # 26D. Launch Multi-AZ RDS database
    rds_response = rds_client.create_db_instance(
        DBInstanceIdentifier="multi-tier-db-instance",
        DBInstanceClass="db.t3.micro",
        Engine="mysql",
        AllocatedStorage=20,
        MasterUsername=DB_USERNAME,
        MasterUserPassword=db_password,
        DBSubnetGroupName="multi-tier-rds-subnet-group",
        VpcSecurityGroupIds=[db_sg_id],
        MultiAZ=True,
        PubliclyAccessible=False,
        StorageEncrypted=True
    )

    rds_arn = rds_response["DBInstance"]["DBInstanceArn"]

    print("Waiting for RDS instance to become available...")
    rds_waiter = rds_client.get_waiter("db_instance_available")
    rds_waiter.wait(DBInstanceIdentifier="multi-tier-db-instance")

    rds_info = rds_client.describe_db_instances(
        DBInstanceIdentifier="multi-tier-db-instance"
    )

    rds_endpoint = rds_info["DBInstances"][0]["Endpoint"]["Address"]

    print("RDS instance is available.")
    print(f"RDS ARN: {rds_arn}")
    print(f"RDS endpoint: {rds_endpoint}")

    print("\nDeployment completed successfully.")
    print(f"Application URL: http://{load_balancer_dns}")


if __name__ == "__main__":
    main()
