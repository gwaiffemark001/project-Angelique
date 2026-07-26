import sys
import os

# Ensure project root is on sys.path so imports work when running tests directly
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.tools import create_and_execute_skill


if __name__ == '__main__':
    instruction = "Compute the square of 7"
    result = create_and_execute_skill(instruction)
    print('Self-evolution test result:')
    print(result)
