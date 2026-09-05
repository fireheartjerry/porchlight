"""Alternative, auto-generated architecture diagram (needs the `diagrams` lib + graphviz `dot`).

The README ships the hand-authored ``docs/architecture.svg`` instead — see
``docs/diagram/render.mjs``, which rasterises it to ``docs/architecture.png`` at 2x with
Playwright. This script is kept as a second opinion on the topology and deliberately writes
somewhere else so it can never overwrite the hand-made pair.

Run:  python docs/diagram/make_architecture.py   ->  docs/diagram/architecture-generated.{png,svg}
"""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import User, Users
from diagrams.programming.framework import React

OUT = Path(__file__).resolve().parent / "architecture-generated"

GRAPH_ATTR = {
    "fontsize": "22",
    "bgcolor": "white",
    "pad": "0.5",
    "nodesep": "0.6",
    "ranksep": "0.9",
    "splines": "ortho",
    "labelloc": "t",
}
NODE_ATTR = {"fontsize": "13", "fontname": "Helvetica"}
EDGE_ATTR = {"fontsize": "11", "fontname": "Helvetica", "color": "#666666"}
AMBER = "#d97706"

with Diagram(
    "Porchlight  ·  Strands Agents on Amazon Bedrock AgentCore",
    filename=str(OUT),
    outformat=["png", "svg"],
    show=False,
    direction="TB",
    graph_attr=GRAPH_ATTR,
    node_attr=NODE_ATTR,
    edge_attr=EDGE_ATTR,
):
    coordinator = User("Coordinator\n(taps Decision Cards)")
    volunteers = Users("Volunteers & requesters\nemail · SMS · form · paper slip")

    with Cluster("The Porch  (web UI)"):
        ui = React("React app\nDecision Cards · Quiet Log · Trace")
        cdn = CloudFront("CloudFront + S3")

    with Cluster("API layer"):
        api = Lambda("FastAPI on Lambda\nFunction URL + SSE")
        table = Dynamodb("DynamoDB\nrequests · volunteers\ndecisions · quiet log")
        sched = Eventbridge("EventBridge Scheduler\nhourly sweep · nightly brief")

    with Cluster("Amazon Bedrock AgentCore"):
        with Cluster("AgentCore Runtime  ·  Strands Graph (intake → matcher → outreach ⟲ → steward)"):
            intake = Bedrock("intake\nHaiku 4.5")
            matcher = Bedrock("matcher\nSonnet 4.6")
            outreach = Bedrock("outreach\nSonnet 4.6")
            steward = Bedrock("steward\nHaiku 4.5")
        memory = Bedrock("AgentCore Memory\nlong-term volunteer &\nrequester facts")
        obs = Cloudwatch("AgentCore Observability\nOTEL traces")
        sessions = S3("S3 session store\ninterrupt state")

    coordinator >> ui >> cdn >> api
    volunteers >> Edge(label="inbound requests") >> api
    api - table
    sched >> api
    api >> Edge(label="invoke_agent_runtime\n(session = request id)") >> intake
    intake >> Edge(label="AidRequest") >> matcher
    matcher >> Edge(label="MatchPlan") >> outreach
    outreach >> Edge(label="accepted") >> steward
    card_label = "Strands intervention → interrupt\n= Decision Card"
    outreach >> Edge(label=card_label, color=AMBER, style="bold") >> api
    matcher >> Edge(style="dashed", label="recall") >> memory
    steward >> Edge(label="remember") >> memory
    steward >> obs
    outreach >> sessions
    steward >> Edge(label="confirmations · reminders (SES/SNS)") >> volunteers

print(f"wrote {OUT}.png and {OUT}.svg")
