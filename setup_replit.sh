#!/bin/bash

# Replit Setup Script
# Run this script to set up your Replit environment

echo "Setting up Replit environment..."

# Check if we're in the workspace directory
if [ ! -f "DeepInfamousDirectories/main.py" ]; then
  echo "Cloning repository..."
  git clone https://github.com/chickenbutt322/HP.git .
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Setup complete!"
echo "Build command: pip install -r requirements.txt"
echo "Run command: python DeepInfamousDirectories/main.py"