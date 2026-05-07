#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Open the web page in the default browser
open http://localhost:5001 &

# Run the Flask server
python app.py
