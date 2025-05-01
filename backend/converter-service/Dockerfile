FROM python:3.13-rc

# Install pandoc and basic tools  
RUN apt-get update && \
    apt-get install -y pandoc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*  

WORKDIR /app  

# Use virtualenv if desired, but for Flask it's fine to use system-site-packages in this Docker image  
COPY requirements.txt .  
RUN pip install --no-cache-dir --upgrade pip  
RUN pip install --no-cache-dir -r requirements.txt  

COPY convert_service.py .  

EXPOSE 5000  
CMD ["python3", "convert_service.py"]