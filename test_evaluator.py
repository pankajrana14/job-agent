"""
test_evaluator.py – Verify the LLM evaluator works independently.

Sends a few hand-crafted job descriptions to the LLM and prints its verdict.
Run this first to confirm your LLM API key works before running a full scrape.

Usage:
    python test_evaluator.py
"""

import sys

# Fix Windows console encoding so Unicode box-drawing characters render correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from utils import setup_logging
logger = setup_logging()

from evaluator import evaluate_job, get_profile_text, LLM_MODEL
from config import LLM_MATCH_THRESHOLD

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

def _c(col, txt): return f"{col}{txt}{_RESET}"

# ---------------------------------------------------------------------------
# Test jobs – mix of obvious matches, unusual titles, and rejects
# ---------------------------------------------------------------------------

TEST_JOBS = [
    {
        "title": "Autonomy Stack Engineer (m/f/d)",
        "company": "Tier Mobility GmbH",
        "location": "Berlin, Deutschland",
        "platform": "Test",
        "experience_level": "",
        "description": """
We are looking for a motivated engineer to join our autonomy team.
You will develop and maintain our autonomous navigation stack for e-scooters.

Requirements:
- 0–2 years of experience (recent graduates welcome)
- Python and C++ development skills
- Experience with ROS2 or similar robotics frameworks
- Familiarity with sensor data processing (lidar, IMU, GPS)
- Linux, Git, Docker

Nice to have: SLAM, point cloud processing, PyTorch
        """.strip(),
    },
    {
        "title": "Softwareentwickler autonome Systeme (m/w/d)",
        "company": "Continental AG",
        "location": "München, Deutschland",
        "platform": "Test",
        "experience_level": "Berufseinsteiger",
        "description": """
Für unser ADAS-Team suchen wir einen Softwareentwickler für autonome Fahrfunktionen.

Ihre Aufgaben:
- Entwicklung von Algorithmen für die Umfeldwahrnehmung
- Integration von Kamera- und Radarsensoren
- Implementierung in C++ auf Embedded-Plattformen

Anforderungen:
- Studienabschluss in Informatik, Elektrotechnik oder verwandtem Bereich
- Erste Erfahrungen mit C++ und Python
- Kenntnisse in Bildverarbeitung oder maschinellem Lernen von Vorteil
- Erste Berufserfahrung oder Praktika willkommen
        """.strip(),
    },
    {
        "title": "Senior Cloud Infrastructure Engineer",
        "company": "Some Bank AG",
        "location": "Frankfurt, Deutschland",
        "platform": "Test",
        "experience_level": "Senior",
        "description": """
We are looking for a Senior Cloud Infrastructure Engineer with 7+ years of experience.

Requirements:
- 7+ years of experience in cloud infrastructure (AWS, Azure, GCP)
- Strong Terraform and Kubernetes skills
- Experience managing large-scale financial systems
- No machine learning or robotics involved
        """.strip(),
    },
    {
        "title": "Werkstudent Perception / Computer Vision (m/w/d)",
        "company": "Robotics Startup Munich",
        "location": "München, Deutschland",
        "platform": "Test",
        "experience_level": "Werkstudent",
        "description": """
Du arbeitest bei uns als Werkstudent im Bereich Computer Vision und Wahrnehmung.

Aufgaben:
- Entwicklung von Deep-Learning-Modellen für Objekterkennung und Tracking
- Arbeit mit 3D-Punktwolken und LiDAR-Daten
- Verwendung von PyTorch, Python, OpenCV
- Integration in unser ROS2-basiertes Robotersystem

Voraussetzungen:
- Studium in Informatik, Maschinenbau oder ähnlichem
- Grundkenntnisse in Python und ML
- Interesse an Robotik und autonomen Systemen
        """.strip(),
    },
    {
        "title": "Marketing Manager DACH",
        "company": "Consumer Goods GmbH",
        "location": "Hamburg, Deutschland",
        "platform": "Test",
        "experience_level": "",
        "description": """
We are looking for an experienced Marketing Manager for the DACH region.
You will develop and execute marketing campaigns, manage social media channels,
and coordinate with our sales team. No technical background required.
3-5 years of marketing experience expected.
        """.strip(),
    },
]

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'═'*70}")
    print(f"  LLM Evaluator Test  –  model: {_c(_CYAN, LLM_MODEL)}")
    print(f"  Match threshold: {LLM_MATCH_THRESHOLD}/10")
    print(f"{'═'*70}")
    print(f"  Profile loaded: {len(get_profile_text())} characters")
    print(f"  Jobs to evaluate: {len(TEST_JOBS)}")
    print(f"{'═'*70}\n")

    passed = 0
    for idx, job in enumerate(TEST_JOBS, 1):
        print(f"  [{idx}/{len(TEST_JOBS)}] Evaluating: {_c(_BOLD, job['title'])}")
        print(f"           Company : {job['company']}")

        try:
            result = evaluate_job(job)
        except Exception as exc:
            print(f"  {_c(_RED, f'[ERROR] {exc}')}\n")
            continue

        verdict = _c(_GREEN, f"MATCH  ({result['score']}/10)") if result["match"] \
                  else _c(_RED,   f"REJECT ({result['score']}/10)")
        print(f"           Verdict : {verdict}")
        print(f"           Reason  : {result['reason'][:120]}{'…' if len(result['reason'])>120 else ''}")

        if result["match"]:
            passed += 1

        print()

    print(f"{'═'*70}")
    print(f"  Results: {_c(_GREEN, str(passed))} matched / {len(TEST_JOBS)} evaluated")
    print(f"  Expected: jobs 1, 2, 4 = match  |  jobs 3, 5 = reject")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted.")
        sys.exit(0)
