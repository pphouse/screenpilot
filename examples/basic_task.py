"""Example: Run a basic automation task with ScreenPilot."""

from screenpilot.agent import ScreenPilotAgent
from screenpilot.config import LLMConfig, ScreenPilotConfig

# Configure with Anthropic Claude
config = ScreenPilotConfig(
    llm=LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
    )
)

# Create the agent
agent = ScreenPilotAgent(config)

# Register step callback for real-time feedback
def on_step(step):
    status = "OK" if step.action_result.success else "FAIL"
    print(f"  Step {step.step_number}: {step.action.action_type.value} [{status}]")
    if step.action.reasoning:
        print(f"    Reasoning: {step.action.reasoning[:80]}")

agent.on_step(on_step)

# Run the task
print("Starting automation task...")
result = agent.run(
    goal="Open the file manager and list the contents of the home directory",
    max_steps=20,
)

# Print results
print(f"\nResult: {'SUCCESS' if result.success else 'FAILED'}")
print(f"Steps: {result.num_steps}")
print(f"Time: {result.total_time:.1f}s")
if result.error:
    print(f"Error: {result.error}")
