#!/usr/bin/env bash
TOKEN_1=$(python postgrest/mint_jwt.py 1)   # Adrian Foscolo
TOKEN_2=$(python postgrest/mint_jwt.py 2)   # Marisol Quintero

curl -s "http://localhost:3000/residents" -H "Authorization: Bearer $TOKEN_1" | jq
curl -s "http://localhost:3000/residents" -H "Authorization: Bearer $TOKEN_2" | jq