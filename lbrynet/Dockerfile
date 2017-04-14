FROM python:2.7
MAINTAINER jobevers@lbry.io

# install the requirements
RUN apt-get update \
 && apt-get install -y  \
      libgmp3-dev build-essential \
      git libssl-dev libffi-dev \
      python-protobuf

# doing the requirements first allows them to be cached
ADD lbry/requirements.txt /src/lbry/requirements.txt
RUN virtualenv /app \
 && /app/bin/pip install -r /src/lbry/requirements.txt

ADD lbryschema /src/lbryschema
RUN /app/bin/pip install -r /src/lbryschema/requirements.txt
RUN /app/bin/pip install -U /src/lbryschema

ADD lbryum /src/lbryum
RUN /app/bin/pip install -U /src/lbryum

# build the app from source
ADD lbry/ /src/lbry
RUN /app/bin/pip install /src/lbry

RUN mkdir -p /data /data/lbryum /data/lbrynet /data/Downloads \
 && mkdir -p /home/lbry/.lbrynet

VOLUME /data
ADD data /data
# this is temporary; eventually all
# lbrynet data should go in /data/lbrynet
VOLUME /home/lbry/.lbrynet

# until Docker fixes the ability to change
# the ownership of ADDed files, we have
# to run as root, unfortunately
# USER lbry


# UPNP would be silly for this
ENV LBRY_USE_UPNP=false

ENV LBRY_LBRYUM_WALLET_DIR=/data/lbryum \
 LBRY_DATA_DIR=/data/lbrynet \
 LBRY_DOWNLOAD_DIRECTORY=/data/Downloads \
 LBRY_BITTREX_FEED=http://fake-bittrex:8003/data \
 LBRY_REFLECTOR_SERVERS=reflector:5566

EXPOSE 3333 4444 5279 5566

ADD run.sh /app/bin/run.sh
# TODO: create a way to disable the UI
CMD ["/app/bin/run.sh"]




