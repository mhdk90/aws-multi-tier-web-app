# AWS Multi-Tier Web Application in a Custom VPC

## Project Overview

This project demonstrates the deployment of a secure and scalable multi-tier web application on AWS using Python and Boto3.

The architecture includes a custom VPC, public and private subnets, Internet Gateway, NAT Gateway, EC2 instances, Application Load Balancer, Target Group, Auto Scaling Group, encrypted EBS volumes, and a Multi-AZ RDS MySQL database.

## Architecture

![Architecture Diagram](architecture/architecture-diagram.png)

## AWS Services Used

- Amazon VPC
- Public and private subnets
- Internet Gateway
- NAT Gateway
- EC2
- EBS
- Application Load Balancer
- Target Group
- Auto Scaling Group
- RDS MySQL
- Security Groups
- Python Boto3

## Network Design

| Component | CIDR Block | Availability Zone |
|---|---|---|
| VPC | 10.0.0.0/16 | us-east-1 |
| Public Subnet 1 | 10.0.10.0/24 | us-east-1a |
| Public Subnet 2 | 10.0.20.0/24 | us-east-1b |
| Private Subnet 1 | 10.0.100.0/24 | us-east-1a |
| Private Subnet 2 | 10.0.200.0/24 | us-east-1b |

## Deployment Steps

1. Create a custom VPC.
2. Create two public subnets.
3. Enable auto-assign public IP for public subnets.
4. Create two private subnets.
5. Create and attach an Internet Gateway.
6. Configure public route tables.
7. Create a NAT Gateway.
8. Configure private route tables.
9. Create security groups.
10. Launch EC2 instances in private subnets.
11. Install Apache using user data.
12. Create a Target Group.
13. Register EC2 instances with the Target Group.
14. Create an Application Load Balancer.
15. Create an ALB listener.
16. Configure Auto Scaling.
17. Create a Multi-AZ RDS MySQL database.
18. Test the application using the ALB DNS name.

## Security Design

- EC2 instances are deployed in private subnets.
- RDS is deployed in private subnets.
- The database accepts traffic only from the web/application security group.
- EBS volumes are encrypted.
- Private instances use NAT Gateway for outbound updates.
- The Application Load Balancer is the public entry point.

## Traffic Flow

User → Internet → Application Load Balancer → Private EC2 Instances → Private RDS Database

## What I Learned

- Custom AWS VPC design
- Public and private subnet architecture
- Internet Gateway and NAT Gateway configuration
- EC2 deployment in private subnets
- Application Load Balancer setup
- Target Group configuration
- Auto Scaling Group setup
- Multi-AZ RDS deployment
- Security group access control
- AWS automation using Python Boto3

## Important Note

This project is for learning and portfolio purposes. For production, SSH access should be restricted, credentials should be stored in AWS Secrets Manager, HTTPS should be enabled, and monitoring/logging should be added.
