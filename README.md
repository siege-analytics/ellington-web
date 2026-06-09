# ellington-web

Ellington web application — Django on the GeoDjango Simple Template ([siege-analytics/geodjango_simple_template](https://github.com/siege-analytics/geodjango_simple_template)). Consumes the [`siege-analytics/ellington-systems`](https://github.com/siege-analytics/ellington-systems) engine. Part of [ellington-systems#12](https://github.com/siege-analytics/ellington-systems/issues/12).

Production deploys to the cyberpower microk8s cluster at [https://ellington.siegeanalytics.com](https://ellington.siegeanalytics.com). Manifests live in [siege-analytics/ellington-web-manifests](https://github.com/siege-analytics/ellington-web-manifests).

## Layout

```
app/
  ellington_web/             # Django project root
    ellington_web/           # project module (settings, asgi, urls, celery)
    locations/               # GST sample app — placeholder until sub-2d
    manage.py
docker/                      # Dockerfile, entrypoint, nginx config
conf/                        # gunicorn / django / postgres / build config
compose.yaml                 # local dev (NOT production — that's k8s)
Makefile                     # `make build`, `make up`, `make migrate`, etc.
```

## Local development

```bash
make build       # build container images
make up          # start the stack (Django + PostGIS + nginx)
make migrate     # run Django migrations
make shell       # shell into the webserver container
```

Once up: `http://localhost:8000/` (Django), `http://localhost:8001/` (nginx).

## Status

- **sub-1 (k8s substrate):** done — site serves at `ellington.siegeanalytics.com` behind LetsEncrypt + Authentik
- **sub-2 (GST instantiation):** in progress
- **sub-3** Master Timeline + iReal Pro ingestion, **sub-4** audio pipeline, **sub-5** LLM coach: upcoming

## License

Apache 2.0. See [LICENSE](LICENSE).
