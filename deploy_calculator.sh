#!/bin/bash

TARGET_DIR=${TARGET_DIR:-/var/www/html/resources/activation}

# First, get the latest pyodide files and the specific periodictable wheel we need:
./activation/get_pyodide.sh

# Now copy all the necessary files to the target directory for deployment:
mkdir -p $TARGET_DIR
cp activation/index_pyodide_optimized.html $TARGET_DIR/index.html
cp activation/jquery* $TARGET_DIR/
cp activation/webworker.js $TARGET_DIR/
cp activation/favicon.ico $TARGET_DIR/
cp activation/periodictable_wheel_name.txt $TARGET_DIR/
cp cgi-bin/nact.py $TARGET_DIR/
cp -r activation/pyodide $TARGET_DIR/pyodide