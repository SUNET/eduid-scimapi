FROM debian:stable

MAINTAINER eduid-dev <eduid-dev@SEGATE.SUNET.SE>

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get -y update && apt-get -y install \
    git \
    curl \
    python3-pip \
    python3.7-venv

COPY . /opt/eduid/eduid-scimapi
RUN (cd /opt/eduid/eduid-scimapi; git describe; git log -n 1) > /revision.txt
RUN rm -rf /opt/eduid/eduid-scimapi/.git
RUN python3.7 -m venv /opt/eduid/env
RUN /opt/eduid/env/bin/pip install -U pip wheel
RUN /opt/eduid/env/bin/pip install --index-url https://pypi.sunet.se -r /opt/eduid/eduid-scimapi/requirements.txt

EXPOSE "8000"
HEALTHCHECK --interval=27s CMD curl http://localhost:8000/status/healthy | grep -q STATUS_OK

WORKDIR "/opt/eduid/eduid-scimapi/src"
ENV GUNICORN_CMD_ARGS="--bind=0.0.0.0:8000"
CMD [ "/opt/eduid/env/bin/gunicorn", "eduid_scimapi.run:api" ]
