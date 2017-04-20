#!/bin/bash
if [ "$1" == "lbryum-only" ]; then
    /app/bin/lbryum daemon start -D /data/lbryum
    tail -f /dev/null
else
    sleep 15 
    /app/bin/python /app/bin/lbrynet-daemon --verbose
fi
