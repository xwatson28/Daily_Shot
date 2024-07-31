#!/bin/bash

# Start the Flask server in the background
python3 flask_server.py &

# Start the Gmail export script in the background
python3 gmail_export.py &

# Start the Streamlit app
streamlit run streamlit_app.py
