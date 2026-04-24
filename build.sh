#!/usr/bin/env bash
# build.sh
# exit on error
set -o errexit

pip install -r requirements.txt
python manage.py migrate
python manage.py create_owner
python manage.py collectstatic --noinput
