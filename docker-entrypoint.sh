#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py seed_data

# demo admin for local/dev use, only if the env vars are set (see docker-compose.yml)
if [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput >/dev/null 2>&1 \
        && echo "Created demo admin $DJANGO_SUPERUSER_EMAIL" \
        || echo "Demo admin $DJANGO_SUPERUSER_EMAIL already exists"
fi

exec "$@"
