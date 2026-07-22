import sys
import os

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brain.cognitive_loop import run_cognitive_loop

def main():
    print("🟢 Angelique v2 - Cognitive Architecture Online")
    print("Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("👋 Shutting down...")
            break
            
        # Pass everything to the Brain. The Brain decides what to do.
        response = run_cognitive_loop(user_input)
        print(f"\nAngelique: {response}\n")

if __name__ == "__main__":
    main()