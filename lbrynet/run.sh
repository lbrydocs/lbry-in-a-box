#!/bin/bash
if [ "$1" == "lbryum-only" ]; then
    sleep 15
    /app/bin/lbryum daemon start -D /data/lbryum
    tail -f /dev/null
elif [ "$1" == "reflector-cluster" ]; then
    sleep 15
    redis-server&
    /app/bin/prism-server&
    /app/bin/prism-worker&
    /app/bin/python /app/bin/lbrynet-daemon --verbose&
    tail -f /dev/null
else
    sleep 15
    /app/bin/python /app/bin/lbrynet-daemon --verbose
fi
