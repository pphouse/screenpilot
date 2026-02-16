"""Example: Using the ScreenPilot REST API."""

import json
import time

import requests

BASE_URL = "http://localhost:8420"


def main():
    # Check server health
    resp = requests.get(f"{BASE_URL}/health")
    print(f"Server status: {resp.json()}")

    # Take a screenshot
    print("\nTaking screenshot...")
    resp = requests.post(f"{BASE_URL}/screenshot")
    data = resp.json()
    print(f"  Size: {data['width']}x{data['height']}")

    # Analyze the screen
    print("\nAnalyzing screen...")
    resp = requests.post(f"{BASE_URL}/analyze")
    analysis = resp.json()
    print(f"  Description: {analysis['description']}")
    print(f"  Elements found: {len(analysis['elements'])}")
    for el in analysis["elements"][:5]:
        print(f"    - {el['label']} ({el['element_type']}) at ({el['x']}, {el['y']})")

    # Find a specific element
    print("\nFinding 'search bar'...")
    resp = requests.post(f"{BASE_URL}/find", json={"target": "search bar"})
    if resp.status_code == 200:
        el = resp.json()
        print(f"  Found: {el['label']} at ({el['x']}, {el['y']}) confidence={el['confidence']:.0%}")

    # Run an automation task
    print("\nStarting task...")
    resp = requests.post(
        f"{BASE_URL}/task",
        json={"goal": "Open the terminal", "max_steps": 10},
    )
    task = resp.json()
    task_id = task["task_id"]
    print(f"  Task ID: {task_id}")

    # Poll for completion
    while True:
        time.sleep(2)
        resp = requests.get(f"{BASE_URL}/task/{task_id}")
        status = resp.json()
        print(f"  Status: {status['status']} (step {status['current_step']})")
        if status["status"] in ("completed", "failed", "stopped"):
            break

    print(f"\nTask finished: {status['status']}")


if __name__ == "__main__":
    main()
