#!/bin/sh

# I dislike this because it...
# - introduces an otherwise un-used ENV variable
# - doesn't seem specific to using a postgres database
# - adds a dependency on netcat
# - can (should?) be handled by orchesation tools
#
# if [ "$DATABASE" = "postgres" ]
# then
#     echo "Waiting for postgres..."

#     while ! nc -z $SQL_HOST $SQL_PORT; do
#       sleep 0.1
#     done

#     echo "PostgreSQL started"
# fi

python3 ellington_web/manage.py ensure_paths
python3 ellington_web/manage.py makemigrations
python3 ellington_web/manage.py migrate
python ellington_web/manage.py sqlsequencereset locations | python ellington_web/manage.py dbshell
python3 ellington_web/manage.py collectstatic --no-input

exec "$@"