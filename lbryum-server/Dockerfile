FROM python:2.7
MAINTAINER jobevers@lbry.io

RUN adduser --disabled-password --gecos '' lbryum
ADD lbryum-server/requirements.txt /tmp/requirements.txt
RUN DEBIAN_FRONTEND=noninteractive apt-get -q update \
 && DEBIAN_FRONTEND=noninteractive apt-get -qqy install apt-utils \
 && DEBIAN_FRONTEND=noninteractive apt-get -qqy install \
        unzip libleveldb1 libleveldb-dev \
 && rm -rf /var/lib/apt/lists/* \
 && pip install -qr /tmp/requirements.txt

ADD lbryum-server /code/lbryum-server
# this symlink is required so that lbryum-server can run in editable mode.
# Running in editable mode allows you to volume mount the source code,
# make changes and restart just the lbryum-server without having to rebuild
# the container.
RUN ln -s /code/lbryum-server/src/ /code/lbryum-server/lbryumserver \
 && pip install -e /code/lbryum-server/ \
 && mkdir -p /data/log && mkdir /data/lbryum-db && chown -R lbryum:lbryum /data

ADD lbrycrdd /usr/local/bin/lbrycrdd
ADD lbrycrd.conf /data/lbrycrd/lbrycrd.conf
ADD lbryum.conf /etc/lbryum.conf

# install lbryschema
# install the requirements
RUN apt-get update \
 && apt-get install -y  \
      python-protobuf

ADD lbryschema /src/lbryschema
RUN pip install -r /src/lbryschema/requirements.txt
RUN pip install -U /src/lbryschema


VOLUME /data
# the port that lbryum clients connect to.
EXPOSE 50001

# Would probably be worthwhile to actually add some
# process management to this, but this works for now.
ADD run.sh /usr/local/bin/run.sh
CMD ["/usr/local/bin/run.sh"]



