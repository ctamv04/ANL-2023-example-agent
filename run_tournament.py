import json
import os
from pathlib import Path
import time

from utils.runners import run_tournament

RESULTS_DIR = Path("results", time.strftime('%Y%m%d-%H%M%S'))

# create results directory if it does not exist
if not RESULTS_DIR.exists():
    RESULTS_DIR.mkdir(parents=True)

# Settings to run a negotiation session:
#   You need to specify the classpath of 2 agents to start a negotiation. Parameters for the agent can be added as a dict (see example)
#   You need to specify the preference profiles for both agents. The first profile will be assigned to the first agent.
#   You need to specify a time deadline (is milliseconds (ms)) we are allowed to negotiate before we end without agreement.
tournament_settings = {
    "agents": [
        {
            "class": "agents.group4_agent.andreea_agent.OurFinalAgent",
            "parameters": {"storage_dir": "agent_storage/OurFinalAgent"},
        },
        {
            "class": "agents.ANL2022.agent007.agent007.Agent007",
            "parameters": {"storage_dir": "agent_storage/Agent007"},
        },
        {
            "class": "agents.ANL2022.procrastin_agent.procrastin_agent.ProcrastinAgent",
            "parameters": {"storage_dir": "agent_storage/ProcrastinAgent"},
        },
        {
            "class": "agents.ANL2022.AgentFO2.AgentFO2.AgentFO2",
            "parameters": {"storage_dir": "agent_storage/AgentFO2"},
        },
        {
            "class": "agents.ANL2022.agent4410.agent_4410.Agent4410",
            "parameters": {"storage_dir": "agent_storage/Agent4410"},
        },
        {
            "class": "agents.ANL2022.gea_agent.gea_agent.GEAAgent",
            "parameters": {"storage_dir": "agent_storage/AgentFO2"},
        },
        {
            "class": "agents.CSE3210.agent3.agent3.Agent3",
        },
        {
            "class": "agents.CSE3210.agent22.agent22.Agent22",
        },
        {
            "class": "agents.CSE3210.agent27.agent27.Agent27",
        },
        {
            "class": "agents.CSE3210.agent32.agent32.Agent32",
        },
        {
            "class": "agents.CSE3210.agent52.agent52.Agent52",
        },
        {
            "class": "agents.CSE3210.agent58.agent58.Agent58",
        },
    ],
    "profile_sets": [
        ["domains/domain37/profileA.json", "domains/domain37/profileB.json"],
        ["domains/domain39/profileA.json", "domains/domain39/profileB.json"],
        ["domains/domain05/profileA.json", "domains/domain05/profileB.json"],
        ["domains/domain04/profileA.json", "domains/domain04/profileB.json"],
        ["domains/domain14/profileA.json", "domains/domain14/profileB.json"],
        ["domains/domain21/profileA.json", "domains/domain21/profileB.json"],
        ["domains/domain30/profileA.json", "domains/domain30/profileB.json"],
        ["domains/domain47/profileA.json", "domains/domain47/profileB.json"],
        ["domains/domain02/profileA.json", "domains/domain02/profileB.json"],
        ["domains/domain31/profileA.json", "domains/domain31/profileB.json"],
        ["domains/domain27/profileA.json", "domains/domain27/profileB.json"],
        ["domains/domain49/profileA.json", "domains/domain49/profileB.json"],
        ["domains/domain08/profileA.json", "domains/domain08/profileB.json"],
        ["domains/domain43/profileA.json", "domains/domain43/profileB.json"],
        ["domains/domain21/profileA.json", "domains/domain21/profileB.json"],
        ["domains/domain03/profileA.json", "domains/domain03/profileB.json"],
        ["domains/domain21/profileA.json", "domains/domain21/profileB.json"],
        ["domains/domain25/profileA.json", "domains/domain25/profileB.json"],
        ["domains/domain48/profileA.json", "domains/domain48/profileB.json"],
        ["domains/domain35/profileA.json", "domains/domain35/profileB.json"],

    ],
    "deadline_time_ms": 10000,
}

# run a session and obtain results in dictionaries
tournament_steps, tournament_results, tournament_results_summary = run_tournament(tournament_settings)

# save the tournament settings for reference
with open(RESULTS_DIR.joinpath("tournament_steps.json"), "w", encoding="utf-8") as f:
    f.write(json.dumps(tournament_steps, indent=2))
# save the tournament results
with open(RESULTS_DIR.joinpath("tournament_results.json"), "w", encoding="utf-8") as f:
    f.write(json.dumps(tournament_results, indent=2))
# save the tournament results summary
tournament_results_summary.to_csv(RESULTS_DIR.joinpath("tournament_results_summary.csv"))
