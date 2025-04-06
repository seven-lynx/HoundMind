import os
import random
import time

# List of Python files in the current directory
python_files = [f for f in os.listdir() if f.endswith('.py')]

if not python_files:
    print("No Python files found in the current directory.")
else:
    while True:
        selected_file = random.choice(python_files)
        print(f"Running: {selected_file}")
        os.system(f'python {selected_file}')
        time.sleep(30)