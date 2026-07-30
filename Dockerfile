FROM python:3.12-slim

WORKDIR /app

# Install dependencies first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port Render expects
EXPOSE 10000

# Explicitly run the python script so all threads (Bot + Scanner + Web) start
CMD ["python", "main.py"]
