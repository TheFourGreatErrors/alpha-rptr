#!/bin/bash -xe

scp restart.sh root@ec2-34-241-54-119.eu-west-1.compute.amazonaws.com:restart.sh
ssh -A root@ec2-34-241-54-119.eu-west-1.compute.amazonaws.com /bin/bash restart.sh
