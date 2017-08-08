#!/bin/bash
if [ "$1" == "lbryum-only" ]; then
    sleep 15
    /app/bin/lbryum daemon start -D /data/lbryum
    tail -f /dev/null
elif [ "$1" == "reflector-cluster" ]; then
    sleep 15
    /app/bin/rq worker&
    redis-server&
    /app/bin/prism-server&
    /src/prism_script.sh&
    /app/bin/python /app/bin/lbrynet-daemon --verbose

else
    sleep 15
    /app/bin/python /app/bin/lbrynet-daemon --verbose
fi
