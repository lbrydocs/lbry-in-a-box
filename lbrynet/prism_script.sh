#!/bin/bash
# this makes sure the prism worker runs every second
while :
do
    /app/bin/prism-worker; /app/bin/rq worker -b
    sleep 1
done
