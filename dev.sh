#!/bin/bash

# Golbazaar React Development Script
echo "🏪 Starting Golbazaar React Development..."

# Check if we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Please run this script from the apps/golbazaar directory"
    exit 1
fi

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

# Start development server
echo "🚀 Starting React development server..."
echo "📱 React app will be available at: http://localhost:3000"
echo "🔗 Frappe integration at: http://localhost:8000/golbazaar_react"
echo ""
echo "Press Ctrl+C to stop the development server"
echo ""

npm run dev






