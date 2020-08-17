#!/bin/bash

set -e
cd /usr/local/bin/alpha-rptr

# env
rm -f /etc/init.d/alpha-rptr
ln -s /usr/local/bin/alpha-rptr/init.d/alpha-rptr /etc/init.d/alpha-rptr

# force pull
git fetch origin
git reset --hard origin/master

# restart all service
service alpha-rptr restart
