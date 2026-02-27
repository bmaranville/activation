#!/bin/bash

TARGET_DIR=${TARGET_DIR:-/var/www/html/resources/n-lengths}

python -m util.scattering_table_html $TARGET_DIR 
