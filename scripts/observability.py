#!/usr/bin/env python3
"""
CloudWatch observability for the AgentCore financial assistant.

  setup      Turn on CloudWatch Transaction Search (needed for GenAI Observability
             traces and for AgentCore Evaluations) and send Gateway + Memory
             logs and traces to CloudWatch. Safe to re-run.
  check      Report what is flowing: Transaction Search, Runtime logs, spans,
             vended log deliveries, Runtime metrics, and recent errors.
  dashboard  Create a CloudWatch dashboard and error/latency alarms for the Runtime.
  teardown   Remove what setup/dashboard created (scripts/teardown.sh does not).

Usage:
  uv run scripts/observability.py setup [--sampling 100]
  uv run scripts/observability.py check [--hours 1]
  uv run scripts/observability.py dashboard [--latency-ms 30000]
  uv run scripts/observability.py teardown
"""

import argparse
import json
import pathlib
import sys
import time

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUTS_FILE = REPO_ROOT / "cdk-outputs.json"
STACK_KEY = "supportAgentDemo-AgentCoreStack"
NAMESPACE = "AWS/Bedrock-AgentCore"
DASHBOARD = "supportAgentDemo-AgentCore"
ALARM_PREFIX = "supportAgentDemo-Runtime"
TS_POLICY_NAME = "AgentCoreTransactionSearch"


def outputs() -> dict:
    if not OUTPUTS_FILE.exists():
        sys.exit(f"ERROR: {OUTPUTS_FILE} not found. Run scripts/deploy.sh first.")
    return json.loads(OUTPUTS_FILE.read_text())[STACK_KEY]


def ok(msg):
    print(f"  [ok]   {msg}")


def warn(msg):
    print(f"  [warn] {msg}")


def vended_resources(o):
    """Gateway and Memory send logs/traces only after a CloudWatch delivery is configured."""
    gw_arn = f"arn:aws:bedrock-agentcore:{o['Region']}:{o['AccountId']}:gateway/{o['GatewayId']}"
    return [("gateway", o["GatewayId"], gw_arn), ("memory", o["MemoryId"], o["MemoryArn"])]


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------
def enable_transaction_search(o, sampling):
    region, account = o["Region"], o["AccountId"]
    xray = boto3.client("xray", region_name=region)
    logs = boto3.client("logs", region_name=region)

    dest = xray.get_trace_segment_destination()
    if dest.get("Destination") == "CloudWatchLogs" and dest.get("Status") == "ACTIVE":
        ok("Transaction Search already on (X-Ray spans -> CloudWatch Logs aws/spans)")
    else:
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "TransactionSearchXRayAccess",
                    "Effect": "Allow",
                    "Principal": {"Service": "xray.amazonaws.com"},
                    "Action": "logs:PutLogEvents",
                    "Resource": [
                        f"arn:aws:logs:{region}:{account}:log-group:aws/spans:*",
                        f"arn:aws:logs:{region}:{account}:log-group:/aws/application-signals/data:*",
                    ],
                    "Condition": {
                        "ArnLike": {"aws:SourceArn": f"arn:aws:xray:{region}:{account}:*"},
                        "StringEquals": {"aws:SourceAccount": account},
                    },
                }
            ],
        }
        logs.put_resource_policy(policyName=TS_POLICY_NAME, policyDocument=json.dumps(policy))
        xray.update_trace_segment_destination(Destination="CloudWatchLogs")
        ok("Transaction Search enabled. It can take ~10 minutes before spans show up.")

    if sampling is not None:
        xray.update_indexing_rule(Name="Default", Rule={"Probabilistic": {"DesiredSamplingPercentage": sampling}})
        ok(f"Trace indexing set to {sampling}% (above 1% is billed; spans are stored either way)")


def enable_vended_logs(o):
    region, account = o["Region"], o["AccountId"]
    logs = boto3.client("logs", region_name=region)
    for kind, rid, arn in vended_resources(o):
        group = f"/aws/vendedlogs/bedrock-agentcore/{rid}"
        try:
            logs.create_log_group(logGroupName=group)
        except logs.exceptions.ResourceAlreadyExistsException:
            pass
        group_arn = f"arn:aws:logs:{region}:{account}:log-group:{group}"

        pairs = [
            (
                "APPLICATION_LOGS",
                f"{rid}-logs",
                {
                    "deliveryDestinationType": "CWL",
                    "deliveryDestinationConfiguration": {"destinationResourceArn": group_arn},
                },
            ),
            ("TRACES", f"{rid}-traces", {"deliveryDestinationType": "XRAY"}),
        ]
        for log_type, base, dest_args in pairs:
            src = logs.put_delivery_source(name=f"{base}-source", logType=log_type, resourceArn=arn)
            dst = logs.put_delivery_destination(name=f"{base}-destination", **dest_args)
            try:
                logs.create_delivery(
                    deliverySourceName=src["deliverySource"]["name"],
                    deliveryDestinationArn=dst["deliveryDestination"]["arn"],
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConflictException":
                    raise
        ok(f"{kind}: logs -> {group}, traces -> X-Ray/aws/spans")


def cmd_setup(args):
    o = outputs()
    print("Transaction Search")
    enable_transaction_search(o, args.sampling)
    print("Gateway and Memory log/trace delivery")
    enable_vended_logs(o)
    print("\nRuntime traces need nothing else: the image runs under opentelemetry-instrument (ADOT).")
    print(
        f"Console: https://console.aws.amazon.com/cloudwatch/home?region={o['Region']}#gen-ai-observability/agent-core"
    )


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------
def insights(logs, groups, query, hours):
    end = int(time.time())
    try:
        qid = logs.start_query(logGroupNames=groups, startTime=end - hours * 3600, endTime=end, queryString=query)[
            "queryId"
        ]
    except logs.exceptions.ResourceNotFoundException:
        return None
    while True:
        r = logs.get_query_results(queryId=qid)
        if r["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            return r.get("results", [])
        time.sleep(1)


def count(logs, groups, filter_clause, hours):
    """Count matching events with Logs Insights; None if a log group does not exist."""
    query = f"{filter_clause} | stats count(*) as n" if filter_clause else "stats count(*) as n"
    res = insights(logs, groups, query, hours)
    if res is None:
        return None
    return int(float(res[0][0]["value"])) if res and res[0] else 0


def runtime_metrics(cw, o):
    """Find the Runtime's metric series (dimension sets differ by metric, so discover them)."""
    found = []
    for page in cw.get_paginator("list_metrics").paginate(Namespace=NAMESPACE):
        for m in page["Metrics"]:
            dims = {d["Name"]: d["Value"] for d in m["Dimensions"]}
            if any(o["RuntimeId"] in v or o["RuntimeName"] in v or o["RuntimeArn"] == v for v in dims.values()):
                found.append(m)
    return found


def cmd_check(args):
    o = outputs()
    region, hours = o["Region"], args.hours
    logs = boto3.client("logs", region_name=region)
    xray = boto3.client("xray", region_name=region)
    cw = boto3.client("cloudwatch", region_name=region)
    healthy = True

    print("Transaction Search")
    d = xray.get_trace_segment_destination()
    if d.get("Destination") == "CloudWatchLogs" and d.get("Status") == "ACTIVE":
        ok("on")
    else:
        healthy = False
        warn(f"off or pending ({d.get('Destination')}/{d.get('Status')}). Run: uv run scripts/observability.py setup")

    print(f"Runtime logs (last {hours}h)")
    group = f"/aws/bedrock-agentcore/runtimes/{o['RuntimeId']}-DEFAULT"
    total = count(logs, [group], "", hours)
    if total is None:
        healthy = False
        warn(f"{group} not found. The Runtime has not been invoked yet, or the role cannot write logs.")
    else:
        err_filter = "filter @message like /(?i)(error|exception|traceback)/"
        errors = count(logs, [group], err_filter, hours) or 0
        ok(f"{group}: {total} events, {errors} mentioning errors")
        if errors:
            last = insights(logs, [group], f"{err_filter} | sort @timestamp desc | limit 3 | fields @message", hours)
            for r in last or []:
                for f in r:
                    if f["field"] == "@message":
                        print(f"         {f['value'][:300]}")

    print(f"Spans in aws/spans (last {hours}h)")
    runtime_filter = f"filter @message like '{o['RuntimeId']}'"
    spans = count(logs, ["aws/spans"], runtime_filter, hours)
    if spans is None:
        healthy = False
        warn("aws/spans log group does not exist yet. Enable Transaction Search and invoke the agent.")
    elif spans == 0:
        healthy = False
        warn("no spans for this Runtime yet. Evaluations need these; invoke the agent and wait a few minutes.")
    else:
        model = count(logs, ["aws/spans"], f"{runtime_filter} | filter @message like 'gen_ai'", hours)
        ok(f"{spans} spans, {model} with gen_ai (model call) data")

    print("Gateway and Memory deliveries")
    names = set()
    for page in logs.get_paginator("describe_deliveries").paginate():
        for dlv in page["deliveries"]:
            names.add(dlv["deliverySourceName"])
    for kind, rid, _ in vended_resources(o):
        have = [t for t in ("logs", "traces") if f"{rid}-{t}-source" in names]
        if len(have) == 2:
            ok(f"{kind}: logs and traces delivered")
        else:
            healthy = False
            warn(f"{kind}: missing {set(['logs', 'traces']) - set(have)}. Run: uv run scripts/observability.py setup")

    print("Runtime metrics (AWS/Bedrock-AgentCore, last 24h)")
    metrics = runtime_metrics(cw, o)
    if not metrics:
        warn("no Runtime metric series yet (they appear after the first invocations)")
    for m in sorted(metrics, key=lambda m: m["MetricName"]):
        stat = "Average" if "Latency" in m["MetricName"] else "Sum"
        dp = cw.get_metric_statistics(
            Namespace=NAMESPACE,
            MetricName=m["MetricName"],
            Dimensions=m["Dimensions"],
            StartTime=time.time() - 86400,
            EndTime=time.time(),
            Period=86400,
            Statistics=[stat],
        ).get("Datapoints", [])
        val = round(dp[0][stat], 1) if dp else 0
        dims = ",".join(f"{d['Name']}" for d in m["Dimensions"])
        print(f"         {m['MetricName']:<28} {stat:<8} {val:<10} [{dims}]")

    print(f"\nConsole: https://console.aws.amazon.com/cloudwatch/home?region={region}#gen-ai-observability/agent-core")
    print("Overall:", "healthy" if healthy else "needs attention (see [warn] lines)")
    sys.exit(0 if healthy else 1)


# ---------------------------------------------------------------------------
# dashboard + alarms
# ---------------------------------------------------------------------------
def cmd_dashboard(args):
    o = outputs()
    region = o["Region"]
    cw = boto3.client("cloudwatch", region_name=region)
    metrics = runtime_metrics(cw, o)
    if not metrics:
        sys.exit("No Runtime metrics yet. Invoke the agent a few times (or run scripts/run_eval.py) and retry.")

    # Prefer the most specific series per metric name (most dimensions)
    best = {}
    for m in metrics:
        if m["MetricName"] not in best or len(m["Dimensions"]) > len(best[m["MetricName"]]["Dimensions"]):
            best[m["MetricName"]] = m

    def series(names, stat):
        out = []
        for n in names:
            m = best.get(n)
            if m:
                dims = [x for d in m["Dimensions"] for x in (d["Name"], d["Value"])]
                out.append([NAMESPACE, n, *dims, {"stat": stat, "label": n}])
        return out

    names = list(best)
    errors = [n for n in names if "Error" in n or "Throttle" in n]
    latency = [n for n in names if "Latency" in n]
    volume = [n for n in names if n not in errors + latency]
    log_group = f"/aws/bedrock-agentcore/runtimes/{o['RuntimeId']}-DEFAULT"

    widgets = []
    for i, (title, ms, stat) in enumerate(
        [
            ("Invocations and sessions", volume, "Sum"),
            ("Errors and throttles", errors, "Sum"),
            ("Latency (ms)", latency, "Average"),
        ]
    ):
        if ms:
            widgets.append(
                {
                    "type": "metric",
                    "x": (i % 3) * 8,
                    "y": 0,
                    "width": 8,
                    "height": 6,
                    "properties": {
                        "title": title,
                        "region": region,
                        "view": "timeSeries",
                        "period": 300,
                        "metrics": series(ms, stat),
                    },
                }
            )
    if latency:
        widgets.append(
            {
                "type": "metric",
                "x": 0,
                "y": 6,
                "width": 8,
                "height": 6,
                "properties": {
                    "title": "Latency p90 (ms)",
                    "region": region,
                    "period": 300,
                    "metrics": series(latency, "p90"),
                },
            }
        )
    widgets.append(
        {
            "type": "log",
            "x": 8,
            "y": 6,
            "width": 16,
            "height": 6,
            "properties": {
                "title": "Recent Runtime errors",
                "region": region,
                "view": "table",
                "query": f"SOURCE '{log_group}' | filter @message like /(?i)error|exception/ "
                "| sort @timestamp desc | limit 20 | fields @timestamp, @message",
            },
        }
    )
    cw.put_dashboard(DashboardName=DASHBOARD, DashboardBody=json.dumps({"widgets": widgets}))
    ok(f"dashboard {DASHBOARD}")

    for n in errors:
        if "Throttle" in n:
            continue
        m = best[n]
        cw.put_metric_alarm(
            AlarmName=f"{ALARM_PREFIX}-{n}",
            Namespace=NAMESPACE,
            MetricName=n,
            Dimensions=m["Dimensions"],
            Statistic="Sum",
            Period=300,
            EvaluationPeriods=1,
            Threshold=1,
            ComparisonOperator="GreaterThanOrEqualToThreshold",
            TreatMissingData="notBreaching",
            AlarmDescription=f"Runtime {n} in the last 5 minutes",
        )
        ok(f"alarm {ALARM_PREFIX}-{n} (>= 1 in 5 min)")
    for n in latency:
        m = best[n]
        cw.put_metric_alarm(
            AlarmName=f"{ALARM_PREFIX}-{n}-p90",
            Namespace=NAMESPACE,
            MetricName=n,
            Dimensions=m["Dimensions"],
            ExtendedStatistic="p90",
            Period=300,
            EvaluationPeriods=3,
            Threshold=args.latency_ms,
            ComparisonOperator="GreaterThanThreshold",
            TreatMissingData="notBreaching",
            AlarmDescription=f"Runtime p90 {n} above {args.latency_ms} ms",
        )
        ok(f"alarm {ALARM_PREFIX}-{n}-p90 (> {args.latency_ms} ms for 15 min)")
    print("Alarms have no notification target; add an SNS action in the console if you want emails.")
    print(f"Dashboard: https://console.aws.amazon.com/cloudwatch/home?region={region}#dashboards/dashboard/{DASHBOARD}")


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------
def cmd_teardown(args):
    o = outputs()
    region = o["Region"]
    cw = boto3.client("cloudwatch", region_name=region)
    logs = boto3.client("logs", region_name=region)

    alarms = [a["AlarmName"] for a in cw.describe_alarms(AlarmNamePrefix=ALARM_PREFIX)["MetricAlarms"]]
    if alarms:
        cw.delete_alarms(AlarmNames=alarms)
    try:
        cw.delete_dashboards(DashboardNames=[DASHBOARD])
    except ClientError:
        pass
    ok(f"removed dashboard and {len(alarms)} alarms")

    for page in logs.get_paginator("describe_deliveries").paginate():
        for dlv in page["deliveries"]:
            if any(dlv["deliverySourceName"].startswith(rid) for _, rid, _ in vended_resources(o)):
                logs.delete_delivery(id=dlv["id"])
    for kind, rid, _ in vended_resources(o):
        for t in ("logs", "traces"):
            for fn, name in (
                (logs.delete_delivery_source, f"{rid}-{t}-source"),
                (logs.delete_delivery_destination, f"{rid}-{t}-destination"),
            ):
                try:
                    fn(name=name)
                except ClientError:
                    pass
        ok(f"removed {kind} deliveries (log group /aws/vendedlogs/bedrock-agentcore/{rid} kept)")
    print("Transaction Search is account-wide and was left on.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--sampling", type=float, help="Trace indexing %% for Transaction Search (default: leave as is)")
    c = sub.add_parser("check")
    c.add_argument("--hours", type=int, default=1)
    d = sub.add_parser("dashboard")
    d.add_argument("--latency-ms", type=int, default=30000, help="p90 latency alarm threshold (default 30000)")
    sub.add_parser("teardown")
    args = p.parse_args()
    {"setup": cmd_setup, "check": cmd_check, "dashboard": cmd_dashboard, "teardown": cmd_teardown}[args.cmd](args)


if __name__ == "__main__":
    main()
