#!/bin/bash
# Wait for the Flask app to become available (started by the artifact workflow)
echo "Waiting for Stream Recorder to start..."
for i in $(seq 1 60); do
    if curl -s -o /dev/null http://localhost:3000/; then
        echo "Stream Recorder is up!"
        break
    fi
    sleep 1
done

# Stay alive so the run button stays active
echo "App is running. Press Stop to shut down."
sleep infinity
