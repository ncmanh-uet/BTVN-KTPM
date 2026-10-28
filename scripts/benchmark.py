"""Compare the same user read with persistent connections, paced below gateway limit."""
import argparse
import json
import math
import statistics
import time

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--token", required=True)
parser.add_argument("--samples", type=int, default=50)
parser.add_argument("--user-id", type=int, default=1)
args = parser.parse_args()
if args.samples < 2:
    parser.error("--samples must be >= 2")
results = {"direct": [], "gateway": []}
urls = {"direct": f"http://127.0.0.1:8001/users/{args.user_id}",
        "gateway": f"http://127.0.0.1:8000/users/{args.user_id}"}
with httpx.Client(headers={"Authorization": f"Bearer {args.token}"}, timeout=10, trust_env=False) as client:
    time.sleep(1.1)
    for url in urls.values():
        client.get(url).raise_for_status()
    time.sleep(0.15)
    for i in range(args.samples):
        # Alternate order to reduce systematic timing bias.
        for name in (list(urls) if i % 2 == 0 else list(reversed(urls))):
            start = time.perf_counter()
            response = client.get(urls[name])
            elapsed = (time.perf_counter()-start)*1000
            response.raise_for_status()
            results[name].append(elapsed)
        time.sleep(0.15)
summary = {}
for name, values in results.items():
    summary[name] = {"samples": len(values), "mean_ms": statistics.mean(values),
                     "median_ms": statistics.median(values),
                     "p95_ms": sorted(values)[math.ceil(0.95*len(values))-1]}
summary["mean_overhead_ms"] = summary["gateway"]["mean_ms"]-summary["direct"]["mean_ms"]
with open("benchmark.json", "w", encoding="utf-8") as output:
    json.dump({"summary": summary, "raw_ms": results}, output, indent=2)
print(json.dumps(summary, indent=2))
