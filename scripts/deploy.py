import boto3

# ============================================================
# AWS Multi-Tier Web Application Deployment using Python Boto3
# ============================================================

# IMPORTANT:
# - Replace "your-aws-profile" with your local AWS CLI profile name.
# - Replace "your-key-pair-name" with your existing EC2 key pair name.
# - Replace "CHANGE_ME_STRONG_PASSWORD" with a strong password.
# - Do NOT upload real AWS credentials or real passwords to GitHub.

REGION = "us-east-1"
AWS_PROFILE = "your-aws-profile"
KEY_NAME = "your-key-pair-name"
AMI_ID = "ami-0889a44b331db0194"
INSTANCE_TYPE = "t2.micro"

VPC_CIDR = "10.0.0.0/16"

PUBLIC_SUBNET_CIDRS = ["10.0.10.0/24", "10.0.20.0/24"]
PRIVATE_SUBNET_CIDRS = ["10.0.100.0/24", "10.0.200.0/24"]
AVAILABILITY_ZONES = ["us-east-1a", "us-east-1b"]

DB_USERNAME = "admin"
DB_PASSWORD = "CHANGE_ME_STRONG_PASSWORD"


def main():
    session = boto3.session.Session(profile_name=AWS_PROFILE)

    ec2_cli = session.client(service_name="ec2", region_name=REGION)
    ec2_resource = session.resource(service_name="ec2", region_name=REGION)

    elb_client = session.client("elbv2", region_name=REGION)
    autoscaling_client = session.client("autoscaling", region_name=REGION)
    rds_client = session.client("rds", region_name=REGION)

    # ------------------------------------------------------------
    # 1. Create a new VPC
    # ------------------------------------------------------------
    new_vpc = ec2_cli.create_vpc(CidrBlock=VPC_CIDR)
    vpc_id = new_vpc["Vpc"]["VpcId"]

    ec2_cli.create_tags(
        Resources=[vpc_id],
        Tags=[{"Key": "Name", "Value": "MultiTierVPC"}]
    )

    print(f"New VPC created successfully: {vpc_id}")

    # ------------------------------------------------------------
    # 2. Create public subnets
    # ------------------------------------------------------------
    public_subnet_ids = []

    for cidr, az in zip(PUBLIC_SUBNET_CIDRS, AVAILABILITY_ZONES):
        response = ec2_cli.create_subnet(
            CidrBlock=cidr,
            VpcId=vpc_id,
            AvailabilityZone=az
        )

        subnet_id = response["Subnet"]["SubnetId"]
        public_subnet_ids.append(subnet_id)

        ec2_cli.create_tags(
            Resources=[subnet_id],
            Tags=[{"Key": "Name", "Value": f"PublicSubnet-{az}"}]
        )

    print(f"Public subnets created: {public_subnet_ids}")

    # ------------------------------------------------------------
    # 3. Enable auto-assign public IP addresses for public subnets
    # ------------------------------------------------------------
    for subnet_id in public_subnet_ids:
        ec2_cli.modify_subnet_attribute(
            SubnetId=subnet_id,
            MapPublicIpOnLaunch={"Value": True}
        )

    print("Auto-assign public IP enabled for public subnets.")

    # ------------------------------------------------------------
    # 4. Create private subnets
    # ------------------------------------------------------------
    private_subnet_ids = []

    for cidr, az in zip(PRIVATE_SUBNET_CIDRS, AVAILABILITY_ZONES):
        response = ec2_cli.create_subnet(
            CidrBlock=cidr,
            VpcId=vpc_id,
            AvailabilityZone=az
        )

        subnet_id = response["Subnet"]["SubnetId"]
        private_subnet_ids.append(subnet_id)

        ec2_cli.create_tags(
            Resources=[subnet_id],
            Tags=[{"Key": "Name", "Value": f"PrivateSubnet-{az}"}]
        )

    print(f"Private subnets created: {private_subnet_ids}")

    # ------------------------------------------------------------
    # 5. Create the Internet Gateway
    # ------------------------------------------------------------
    response = ec2_cli.create_internet_gateway()
    internet_gateway_id = response["InternetGateway"]["InternetGatewayId"]

    ec2_cli.create_tags(
        Resources=[internet_gateway_id],
        Tags=[{"Key": "Name", "Value": "MultiTierIGW"}]
    )

    print(f"Internet Gateway created: {internet_gateway_id}")

    # ------------------------------------------------------------
    # 6. Attach the Internet Gateway to the VPC
    # ------------------------------------------------------------
    ec2_cli.attach_internet_gateway(
        InternetGatewayId=internet_gateway_id,
        VpcId=vpc_id
    )

    print("Internet Gateway attached to VPC.")

    # ------------------------------------------------------------
    # 7. Create route table for public subnets
    # ------------------------------------------------------------
    response = ec2_cli.create_route_table(VpcId=vpc_id)
    public_route_table_id = response["RouteTable"]["RouteTableId"]

    ec2_cli.create_tags(
        Resources=[public_route_table_id],
        Tags=[{"Key": "Name", "Value": "PublicRouteTable"}]
    )

    print(f"Public route table created: {public_route_table_id}")

    # ------------------------------------------------------------
    # 8. Associate public subnets with public route table
    # ------------------------------------------------------------
    for subnet_id in public_subnet_ids:
        ec2_cli.associate_route_table(
            RouteTableId=public_route_table_id,
            SubnetId=subnet_id
        )

    print("Public subnets associated with public route table.")

    # ------------------------------------------------------------
    # 9. Add default route to Internet Gateway
    # ------------------------------------------------------------
    public_route_table = ec2_resource.RouteTable(public_route_table_id)

    public_route_table.create_route(
        DestinationCidrBlock="0.0.0.0/0",
        GatewayId=internet_gateway_id
    )

    print("Default route added to public route table.")

    # ------------------------------------------------------------
    # 10. Create NAT Gateway
    # ------------------------------------------------------------
    allocation = ec2_cli.allocate_address(Domain="vpc")

    response = ec2_cli.create_nat_gateway(
        AllocationId=allocation["AllocationId"],
        SubnetId=public_subnet_ids[0]
    )

    nat_gateway_id = response["NatGateway"]["NatGatewayId"]

    print(f"NAT Gateway is being created: {nat_gateway_id}")

    # ------------------------------------------------------------
    # 11. Create route table for private subnets
    # ------------------------------------------------------------
    response = ec2_cli.create_route_table(VpcId=vpc_id)
    private_route_table_id = response["RouteTable"]["RouteTableId"]

    ec2_cli.create_tags(
        Resources=[private_route_table_id],
        Tags=[{"Key": "Name", "Value": "PrivateRouteTable"}]
    )

    print(f"Private route table created: {private_route_table_id}")

    # ------------------------------------------------------------
    # 12. Associate private subnets with private route table
    # ------------------------------------------------------------
    for subnet_id in private_subnet_ids:
        ec2_cli.associate_route_table(
            RouteTableId=private_route_table_id,
            SubnetId=subnet_id
        )

    print("Private subnets associated with private route table.")

    # ------------------------------------------------------------
    # 13. Wait until NAT Gateway is available
    # ------------------------------------------------------------
    waiter = ec2_cli.get_waiter("nat_gateway_available")

    print("Waiting for NAT Gateway to become available...")
    waiter.wait(NatGatewayIds=[nat_gateway_id])

    print("NAT Gateway is available.")

    # ------------------------------------------------------------
    # 14. Add default route to NAT Gateway
    # ------------------------------------------------------------
    private_route_table = ec2_resource.RouteTable(private_route_table_id)

    private_route_table.create_route(
        DestinationCidrBlock="0.0.0.0/0",
        NatGatewayId=nat_gateway_id
    )

    print("Default route added to private route table.")

    # ------------------------------------------------------------
    # 15. Create security group for EC2 instances
    # ------------------------------------------------------------
    response = ec2_cli.create_security_group(
        Description="Security group for private web/application EC2 instances",
        GroupName="WebSG",
        VpcId=vpc_id
    )

    web_sg_id = response["GroupId"]

    ec2_cli.create_tags(
        Resources=[web_sg_id],
        Tags=[{"Key": "Name", "Value": "WebSG"}]
    )

    print(f"WebSG created: {web_sg_id}")

    # ------------------------------------------------------------
    # 16. Add security group ingress rules for ports 22, 80, 443
    # ------------------------------------------------------------
    ec2_cli.authorize_security_group_ingress(
        GroupId=web_sg_id,
        IpPermissions=[
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

    print("Inbound rules added to WebSG.")

    # ------------------------------------------------------------
    # 17. Add egress rule to WebSG
    # ------------------------------------------------------------
    try:
        ec2_cli.authorize_security_group_egress(
            GroupId=web_sg_id,
            IpPermissions=[
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

        print("Outbound rule added to WebSG.")

    except Exception as error:
        print(f"Outbound rule may already exist: {error}")

    # ------------------------------------------------------------
    # 18. Launch EC2 instances in private subnets
    # ------------------------------------------------------------
    user_data_script_1 = """#!/bin/bash
yum update -y
yum install httpd -y
systemctl start httpd
systemctl enable httpd
echo "This is server 1 in AWS Region US-EAST-1 in AZ US-EAST-1A" > /var/www/html/index.html
"""

    user_data_script_2 = """#!/bin/bash
yum update -y
yum install httpd -y
systemctl start httpd
systemctl enable httpd
echo "This is server 2 in AWS Region US-EAST-1 in AZ US-EAST-1B" > /var/www/html/index.html
"""

    user_data_scripts = [user_data_script_1, user_data_script_2]

    instance_ids = []

    for subnet_id, user_data_script in zip(private_subnet_ids, user_data_scripts):
        response = ec2_cli.run_instances(
            ImageId=AMI_ID,
            InstanceType=INSTANCE_TYPE,
            KeyName=KEY_NAME,
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

        instance_id = response["Instances"][0]["InstanceId"]
        instance_ids.append(instance_id)

    # ------------------------------------------------------------
    # 19. Wait until all instances are running
    # ------------------------------------------------------------
    waiter = ec2_cli.get_waiter("instance_running")

    print("Waiting for EC2 instances to start...")
    waiter.wait(InstanceIds=instance_ids)

    print(f"EC2 instances are running: {instance_ids}")

    # ------------------------------------------------------------
    # 20. Create client objects for other services
    # Already created above:
    # - ELBv2 client
    # - Auto Scaling client
    # - RDS client
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # 21. Create Target Group
    # ------------------------------------------------------------
    response = elb_client.create_target_group(
        Name="webTG",
        Protocol="HTTP",
        Port=80,
        VpcId=vpc_id,
        HealthCheckProtocol="HTTP",
        HealthCheckPort="80",
        HealthCheckEnabled=True
    )

    target_group_arn = response["TargetGroups"][0]["TargetGroupArn"]

    print(f"Target Group created: {target_group_arn}")

    # ------------------------------------------------------------
    # 22. Register EC2 targets to Target Group
    # ------------------------------------------------------------
    elb_client.register_targets(
        TargetGroupArn=target_group_arn,
        Targets=[
            {"Id": instance_id, "Port": 80}
            for instance_id in instance_ids
        ]
    )

    print("EC2 instances registered with Target Group.")

    # ------------------------------------------------------------
    # 23A. Create ALB Security Group
    # ------------------------------------------------------------
    response = ec2_cli.create_security_group(
        Description="Security group for Application Load Balancer",
        GroupName="ALBSG",
        VpcId=vpc_id
    )

    alb_sg_id = response["GroupId"]

    ec2_cli.create_tags(
        Resources=[alb_sg_id],
        Tags=[{"Key": "Name", "Value": "ALBSG"}]
    )

    print(f"ALB Security Group created: {alb_sg_id}")

    # ------------------------------------------------------------
    # 23B. Add ingress rule to ALB SG
    # ------------------------------------------------------------
    ec2_cli.authorize_security_group_ingress(
        GroupId=alb_sg_id,
        IpPermissions=[
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

    print("Inbound HTTP rule added to ALBSG.")

    # ------------------------------------------------------------
    # 23C. Add egress rule from ALB SG to WebSG
    # ------------------------------------------------------------
    try:
        ec2_cli.authorize_security_group_egress(
            GroupId=alb_sg_id,
            IpPermissions=[
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

        print("Outbound HTTP rule added to ALBSG.")

    except Exception as error:
        print(f"Outbound rule may already exist: {error}")

    # ------------------------------------------------------------
    # 23D. Create Application Load Balancer
    # ------------------------------------------------------------
    response = elb_client.create_load_balancer(
        Name="MultiTierLoadBalancer",
        Subnets=public_subnet_ids,
        SecurityGroups=[alb_sg_id],
        Scheme="internet-facing",
        Type="application",
        IpAddressType="ipv4"
    )

    load_balancer_arn = response["LoadBalancers"][0]["LoadBalancerArn"]
    load_balancer_dns = response["LoadBalancers"][0]["DNSName"]

    # ------------------------------------------------------------
    # 23E. Wait until Load Balancer is available
    # ------------------------------------------------------------
    waiter = elb_client.get_waiter("load_balancer_available")

    print("Waiting for Application Load Balancer to become available...")
    waiter.wait(LoadBalancerArns=[load_balancer_arn])

    print(f"Application Load Balancer is available: {load_balancer_dns}")

    # ------------------------------------------------------------
    # 24. Create listener for Load Balancer
    # ------------------------------------------------------------
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

    print("HTTP listener created for ALB.")

    # ------------------------------------------------------------
    # 25A. Create Launch Configuration
    # ------------------------------------------------------------
    autoscaling_client.create_launch_configuration(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        LaunchConfigurationName="multi-tier-launch-config",
        SecurityGroups=[web_sg_id],
        KeyName=KEY_NAME
    )

    print("Launch Configuration created.")

    # ------------------------------------------------------------
    # 25B. Create Auto Scaling Group
    # ------------------------------------------------------------
    autoscaling_client.create_auto_scaling_group(
        AutoScalingGroupName="MultiTierAutoScalingGroup",
        LaunchConfigurationName="multi-tier-launch-config",
        MinSize=1,
        MaxSize=3,
        DesiredCapacity=1,
        TargetGroupARNs=[target_group_arn],
        VPCZoneIdentifier=",".join(private_subnet_ids)
    )

    response = autoscaling_client.describe_auto_scaling_groups(
        AutoScalingGroupNames=["MultiTierAutoScalingGroup"]
    )

    asg_arn = response["AutoScalingGroups"][0]["AutoScalingGroupARN"]

    print(f"Auto Scaling Group created: {asg_arn}")

    # ------------------------------------------------------------
    # 26A. Create DB Security Group
    # ------------------------------------------------------------
    response = ec2_cli.create_security_group(
        Description="Security group for RDS database",
        GroupName="DBSG",
        VpcId=vpc_id
    )

    db_sg_id = response["GroupId"]

    ec2_cli.create_tags(
        Resources=[db_sg_id],
        Tags=[{"Key": "Name", "Value": "DBSG"}]
    )

    print(f"Database Security Group created: {db_sg_id}")

    # ------------------------------------------------------------
    # 26B. Allow access to DB only from WebSG
    # ------------------------------------------------------------
    ec2_cli.authorize_security_group_ingress(
        GroupId=db_sg_id,
        IpPermissions=[
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

    print("Database security group allows MySQL only from WebSG.")

    # ------------------------------------------------------------
    # 26C. Create DB Subnet Group
    # ------------------------------------------------------------
    rds_client.create_db_subnet_group(
        DBSubnetGroupDescription="RDS subnet group for private subnets",
        DBSubnetGroupName="multi-tier-rds-subnet-group",
        SubnetIds=private_subnet_ids
    )

    print("RDS DB Subnet Group created.")

    # ------------------------------------------------------------
    # 26D. Launch Multi-AZ RDS Database
    # ------------------------------------------------------------
    response = rds_client.create_db_instance(
        DBInstanceIdentifier="multi-tier-db-instance",
        DBInstanceClass="db.t2.micro",
        Engine="mysql",
        AllocatedStorage=20,
        MasterUsername=DB_USERNAME,
        MasterUserPassword=DB_PASSWORD,
        DBSubnetGroupName="multi-tier-rds-subnet-group",
        VpcSecurityGroupIds=[db_sg_id],
        MultiAZ=True,
        PubliclyAccessible=False,
        StorageEncrypted=True
    )

    rds_arn = response["DBInstance"]["DBInstanceArn"]

    print("RDS instance is being created...")

    waiter = rds_client.get_waiter("db_instance_available")
    waiter.wait(DBInstanceIdentifier="multi-tier-db-instance")

    rds = rds_client.describe_db_instances(
        DBInstanceIdentifier="multi-tier-db-instance"
    )

    rds_address = rds["DBInstances"][0]["Endpoint"]["Address"]

    print("RDS instance is available.")
    print(f"RDS ARN: {rds_arn}")
    print(f"RDS Endpoint: {rds_address}")

    # ------------------------------------------------------------
    # Final output
    # ------------------------------------------------------------
    print("\nDeployment completed successfully.")
    print(f"Application Load Balancer DNS: http://{load_balancer_dns}")


if __name__ == "__main__":
    main()
