#!/usr/bin/python3

import os, sys, json
from urllib.parse import parse_qs
import dbm

db = dbm.open('backtests.db', 'c')

method = os.environ["REQUEST_METHOD"]
query = parse_qs(os.environ["QUERY_STRING"])
key = query["key"][0]

result = {}

if method == "GET": 

    if "do" not in query:
        do = "get"
    else:
        do = query["do"][0]

    if do == "get":
        try:
            result[key] = db[key].decode()
            result["result"] = "success"
        except KeyError:
            result["result"] = "not-found"

    if do == "delete":
        try:
            del db[key]
            result["result"] = "success"
        except KeyError:
            result["result"] = "not-found"

elif method == "POST":
    value = json.loads(sys.stdin.read(int(os.environ["CONTENT_LENGTH"])))
    db[key] = json.dumps(value, sort_keys=True)
    result["result"] = "success"
else:
    result["result"] = "not-supported"

print("Content-Type: application/json\n\n")
print(json.dumps(result)) 
