# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port Uvicorn will run on
EXPOSE 8000

# Run the MCP server
CMD ["uvicorn", "tollbooth_agent:mcp_app", "--host", "0.0.0.0", "--port", "8000"]
