#!/bin/bash

# lbrycrdd is set to daemon-fy
/usr/local/bin/lbrycrdd -datadir=/data/lbrycrd
# force the server to reload from lbrycrd each time
#
# for some reason, on restart I'm getting a lot of
# {u'message': u"Can't read block from disk", u'code': -32603}
# errors from lbrycrd. Putting in a clean start seems to fix it.
rm -rf /data/lbryum-db
runuser -l lbryum -c 'lbryum-server --conf=/etc/lbryum.conf'
