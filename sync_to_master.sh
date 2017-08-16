#!/bin/bash
# Sync all lbry repos to master
# if supplied with argument, sync lbry to that tag instead

if [ $# -eq 2 ]
then
    lbry_tag=$1
    lbryum_tag=$2
else
    lbry_tag=origin/master
    lbryum_tag=origin/master
fi

(cd lbrynet/lbry; git fetch origin; git checkout $lbry_tag)

(cd lbrynet/lbryum; git fetch origin; git checkout $lbryum_tag)

(cd lbryum-server/lbryum-server; git fetch origin; git checkout origin/master)

(cd lbrynet/lbryschema; git fetch origin; git checkout origin/master)
(cd lbryum-server/lbryschema; git fetch origin; git checkout origin/master)

