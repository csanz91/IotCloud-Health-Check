#!/bin/bash

while :
do
  date
  echo "--- Start"
  python main.py
  echo "ending"
  RET=$?
  if [ ${RET} -ne 0 ];
  then
    echo "Exit status not 0"
    echo "Sleep 120"
    sleep 10
  fi
  date
  echo "Sleep 60"
  sleep 5
done