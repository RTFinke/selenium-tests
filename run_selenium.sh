#!/bin/bash
echo "Selenium start"
docker compose up -d
sleep 10
docker compose down
echo "Selenium done"
